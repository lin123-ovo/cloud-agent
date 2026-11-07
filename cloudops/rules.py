"""Deterministic, conservative seven-day utilization assessment."""

from datetime import datetime, timedelta, timezone
from cloudops.models import Resource, Sample, Quote

RULE_VERSION = "2026-10-31.v1"
PERIOD = 300


def window(now: datetime | None = None) -> tuple[datetime, datetime]:
    end = (
        (now or datetime.now(timezone.utc))
        .astimezone(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
    )
    return end - timedelta(days=7), end


def summarize(samples: list[Sample], start: datetime, end: datetime) -> dict:
    expected = int((end - start).total_seconds() // PERIOD)
    if expected <= 0:
        raise ValueError("监控窗口必须为正数")
    points: dict[datetime, Sample] = {}
    rejected = 0
    duplicates = set()
    for sample in samples:
        t = sample.timestamp
        if t.tzinfo is None or not start <= t < end or t.timestamp() % PERIOD != 0:
            rejected += 1
            continue
        if t in points:
            # Ambiguous duplicate buckets are excluded rather than picking a favorable value.
            duplicates.add(t)
            rejected += 1
        else:
            points[t] = sample
    for t in duplicates:
        points.pop(t, None)
    result = {"expected_points": expected, "rejected_points": rejected}
    for name in ("cpu", "memory"):
        values = [
            getattr(s, name) for s in points.values() if getattr(s, name) is not None
        ]
        peaks = [
            getattr(s, name + "_max")
            for s in points.values()
            if getattr(s, name) is not None and getattr(s, name + "_max") is not None
        ]
        result[name] = {
            "average": round(sum(values) / len(values), 3) if values else None,
            "maximum": max(peaks) if peaks else None,
            "coverage": round(len(values) / expected, 5),
            "peak_coverage": round(len(peaks) / expected, 5),
            "points": len(values),
        }
    return result


def assess(
    resource: Resource, samples: list[Sample], start: datetime, end: datetime
) -> dict:
    metrics = summarize(samples, start, end)
    cpu, mem = metrics["cpu"], metrics["memory"]
    risks = []
    peak = (cpu["maximum"] is not None and cpu["maximum"] >= 80) or (
        mem["maximum"] is not None and mem["maximum"] >= 85
    )
    if peak:
        risks.append("存在负载峰值，请先检查业务高峰及容量要求")
    if resource.status != "Running":
        diagnosis = "stopped"
        risks.append("实例未运行，不生成降配候选")
    elif (
        cpu["coverage"] < 0.9
        or mem["coverage"] < 0.9
        or cpu["peak_coverage"] < 0.9
        or mem["peak_coverage"] < 0.9
    ):
        diagnosis = "insufficient_data"
        risks.append("内存监控不可用" if not mem["points"] else "监控覆盖率不足 90%")
        if cpu["peak_coverage"] < 0.9 or mem["peak_coverage"] < 0.9:
            risks.append("峰值监控覆盖率不足 90%")
        if cpu["coverage"] < 0.9:
            risks.append("CPU 监控覆盖率不足 90%")
    elif peak:
        diagnosis = "peak_risk"
    elif (
        cpu["average"] < 10
        and cpu["maximum"] < 40
        and mem["average"] < 30
        and mem["maximum"] < 60
    ):
        diagnosis = "low_utilization"
    else:
        diagnosis = "normal"
    return {
        "resource": resource.model_dump(mode="json"),
        "metrics": metrics,
        "diagnosis": diagnosis,
        "risks": risks,
        "candidate": None,
        "savings": None,
        "pricing_note": "未计算费用",
        "rule_version": RULE_VERSION,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
    }


def select_candidate(
    resource: Resource, result: dict, specs: list[dict]
) -> dict | None:
    if result["diagnosis"] != "low_utilization":
        return None
    cpu_peak = result["metrics"]["cpu"]["maximum"] * 2
    mem_peak = result["metrics"]["memory"]["maximum"] * 2
    if cpu_peak >= 80 or mem_peak >= 85:
        result["risks"].append("容量减半后预计峰值过高，不建议降配")
        return None
    valid = [
        s
        for s in specs
        if s["family"] == resource.family
        and s["cpu"] * 2 == resource.cpu
        and s["memory_gb"] * 2 == resource.memory_gb
    ]
    if not valid:
        result["risks"].append("无同规格族且 CPU、内存恰为一半的候选规格")
        return None
    candidate = sorted(valid, key=lambda s: s["id"])[0].copy()
    candidate.update(projected_cpu_max=cpu_peak, projected_memory_max=mem_peak)
    result["risks"].append(
        "线性负载估算仅用于筛选，实际变更前需压测并核对可用区库存与兼容性"
    )
    return candidate


def estimate(resource: Resource, current: Quote, target: Quote) -> dict | None:
    if resource.billing != "PostPaid" or resource.spot:
        return None
    if (
        current.currency != target.currency
        or current.unit != target.unit
        or current.unit != "Hour"
    ):
        return None
    if (
        current.region != target.region
        or current.region != resource.region
        or current.os != target.os
        or current.os != resource.os
    ):
        return None
    if target.amount >= current.amount:
        return None
    return {
        "current_hourly": current.amount,
        "target_hourly": target.amount,
        "monthly_equivalent_saving": round((current.amount - target.amount) * 730, 2),
        "currency": current.currency,
        "hours": 730,
        "source": current.source,
        "scope": "仅计算规格询价对比，排除磁盘、网络、优惠；不是实际账单或保证节省金额",
    }
