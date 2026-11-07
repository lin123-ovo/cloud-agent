"""Shared report orchestration, persisted tasks, and execution evidence."""

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar
import pymysql
from cloudops import store
from cloudops.providers import CloudError, provider, configured, regions, seed_demo
from cloudops.rules import assess, select_candidate, estimate, window, RULE_VERSION

T = TypeVar("T")
executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cloudops")
TERMINAL = {"succeeded", "partial", "failed", "interrupted"}


def environments() -> list[dict]:
    return [
        {
            "id": "demo",
            "name": "演示环境",
            "source": "演示数据",
            "configured": True,
            "regions": ["cn-beijing"],
            "validation": "本地演示",
        },
        {
            "id": "aliyun",
            "name": "阿里云环境",
            "source": "阿里云只读接口",
            "configured": configured(),
            "regions": regions(),
            "validation": "真实云联调待验证",
            "configuration_help": "在 agent/.env 配置 ALIBABA_CLOUD_ACCESS_KEY_ID、ALIBABA_CLOUD_ACCESS_KEY_SECRET；可选 ALIBABA_CLOUD_SECURITY_TOKEN。修改后重启后端。",
        },
    ]


def initialize(seed: bool = True) -> None:
    store.initialize()
    for row in store.rows(
        "SELECT id,payload FROM ops_tasks WHERE status IN ('queued','running') LIMIT 100"
    ):
        data = store.decode(row["payload"])
        data["status"] = "interrupted"
        data["error"] = "服务重启中断了任务，请手动重跑"
        save_task(data)
    if seed:
        seed_demo()


def save_task(task: dict) -> None:
    task["updated_at"] = store.now()
    store.execute(
        "UPDATE ops_tasks SET status=%s,updated_at=%s,active_environment=%s,payload=%s WHERE id=%s",
        (
            task["status"],
            task["updated_at"],
            None if task["status"] in TERMINAL else task["environment"],
            json.dumps(task, ensure_ascii=False),
            task["id"],
        ),
    )


def get_task(id: str) -> dict:
    rows = store.rows("SELECT payload FROM ops_tasks WHERE id=%s", (id,))
    if not rows:
        raise CloudError("NotFound", "分析任务不存在")
    task = store.decode(rows[0]["payload"])
    task["steps"] = [
        store.decode(x["payload"])
        for x in store.rows(
            "SELECT payload FROM ops_steps WHERE task_id=%s ORDER BY id LIMIT 1000",
            (id,),
        )
    ]
    return task


def list_tasks() -> list[dict]:
    return [
        store.decode(r["payload"])
        for r in store.rows(
            "SELECT payload FROM ops_tasks ORDER BY created_at DESC LIMIT 100"
        )
    ]


def step(
    task: dict, tool: str, fn: Callable[[], T], resource_id: str | None = None
) -> T:
    start = time.monotonic()
    payload = {
        "tool": tool,
        "source": task["environment"],
        "resource_id": resource_id,
        "started_at": store.now(),
    }
    try:
        value = fn()
        payload["status"] = "succeeded"
        return value
    except CloudError as exc:
        payload.update(status="failed", error=str(exc), code=exc.code)
        raise
    except Exception:
        payload.update(
            status="failed",
            error="步骤执行失败，请检查数据或服务连接",
            code="StepFailed",
        )
        raise CloudError("StepFailed", payload["error"]) from None
    finally:
        payload["duration_ms"] = round((time.monotonic() - start) * 1000)
        store.execute(
            "INSERT INTO ops_steps(task_id,payload) VALUES(%s,%s)",
            (task["id"], json.dumps(payload, ensure_ascii=False)),
        )


def resources(environment: str, region: str) -> list[dict]:
    return [
        r.model_dump(mode="json")
        for r in provider(environment, region).resources(region)
    ]


def create_task(
    environment: str,
    region: str,
    ids: list[str],
    explain: bool = True,
    language: str = "zh",
) -> dict:
    if language not in {"zh", "en"}:
        raise CloudError("InvalidLanguage", "Unsupported response language")
    if not 1 <= len(ids) <= 20 or len(ids) != len(set(ids)):
        raise CloudError("InvalidInput", "请选择 1 至 20 台不同实例")
    # Validate config and environment before admitting a task; SDK clients do no I/O here.
    provider(environment, region)
    stamp = store.now()
    task = {
        "id": str(uuid.uuid4()),
        "environment": environment,
        "source": "演示数据" if environment == "demo" else "阿里云只读数据",
        "region": region,
        "resource_ids": ids,
        "status": "queued",
        "created_at": stamp,
        "updated_at": stamp,
        "results": [],
        "rule_version": RULE_VERSION,
        "explanation_status": "pending" if explain else "disabled",
        "language": language,
    }
    try:
        store.execute(
            "INSERT INTO ops_tasks(id,environment,region,status,active_environment,created_at,updated_at,payload) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                task["id"],
                environment,
                region,
                "queued",
                environment,
                stamp,
                stamp,
                json.dumps(task, ensure_ascii=False),
            ),
        )
    except pymysql.err.IntegrityError:
        raise CloudError("Busy", "该环境已有执行中的分析任务，请完成后再试") from None
    try:
        executor.submit(run_task, task["id"], explain)
    except RuntimeError:
        task.update(status="failed", error="服务正在关闭")
        save_task(task)
        raise CloudError("Unavailable", "服务正在关闭") from None
    return task


def explain_report(results: list[dict], language: str = "zh") -> str:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage

    if not os.getenv("DASHSCOPE_API_KEY"):
        raise CloudError("ModelUnavailable", "未配置模型密钥")
    model = ChatOpenAI(
        api_key=os.environ["DASHSCOPE_API_KEY"],
        base_url=os.getenv("BASE_URL"),
        model=os.getenv("MODEL", "qwen-plus"),
        temperature=0,
        timeout=20,
        max_retries=0,
    )
    response = model.invoke(
        [
            SystemMessage(
                content="你负责解释已经生成的运维规则报告。仅解释诊断的含义和需要人工核对的风险。不要新增事实、引用外部资料、写任何数值或金额、承诺节省、或声称已执行变更。用三句话以内概括。所有事实以结构化报告为准。"
                + (" Answer in English." if language == "en" else "")
            ),
            HumanMessage(
                content=json.dumps(
                    [
                        {"diagnosis": r.get("diagnosis"), "risks": r.get("risks")}
                        for r in results
                    ],
                    ensure_ascii=False,
                )
            ),
        ]
    )
    if not isinstance(response.content, str) or not response.content.strip():
        raise CloudError("ModelUnavailable", "模型解释未生成")
    # Supplementary prose is never used to update authoritative report fields.
    return response.content


def run_task(id: str, explain: bool) -> None:
    task = get_task(id)
    task.pop("steps", None)
    task["status"] = "running"
    save_task(task)
    failed = False
    try:
        adapter = provider(task["environment"], task["region"])
        inventory = step(
            task, "list_resources", lambda: adapter.resources(task["region"])
        )
        by_id = {r.id: r for r in inventory}
        start, end = window()
        task.update(window_start=start.isoformat(), window_end=end.isoformat())
        for id in task["resource_ids"]:
            try:
                if id not in by_id:
                    raise CloudError("NotFound", "实例不属于当前环境、地域，或已被删除")
                r = by_id[id]
                samples = step(
                    task, "get_monitoring", lambda: adapter.samples(r, start, end), id
                )
                result = step(
                    task,
                    "assess_utilization",
                    lambda: assess(r, samples, start, end),
                    id,
                )
                store.execute(
                    "INSERT INTO ops_snapshots(task_id,payload) VALUES(%s,%s)",
                    (
                        task["id"],
                        json.dumps(
                            {
                                "resource": r.model_dump(mode="json"),
                                "samples": [s.model_dump(mode="json") for s in samples],
                            },
                            ensure_ascii=False,
                        ),
                    ),
                )
                if result["diagnosis"] == "low_utilization":
                    try:
                        result["candidate"] = select_candidate(
                            r,
                            result,
                            step(
                                task,
                                "list_instance_types",
                                lambda: adapter.specs(r),
                                id,
                            ),
                        )
                    except CloudError as exc:
                        result["risks"].append(str(exc))
                        failed = True
                if result["candidate"]:
                    if r.billing != "PostPaid" or r.spot:
                        result["pricing_note"] = "包年包月或抢占式实例不估算节省金额"
                    else:
                        try:
                            current = step(
                                task,
                                "quote_current",
                                lambda: adapter.quote(r, r.instance_type),
                                id,
                            )
                            target = step(
                                task,
                                "quote_candidate",
                                lambda: adapter.quote(r, result["candidate"]["id"]),
                                id,
                            )
                            result["savings"] = estimate(r, current, target)
                            result["pricing_note"] = (
                                "同地域、系统、币种、按小时计算规格原价对比"
                                if result["savings"]
                                else "报价单位、币种或适用条件不匹配，或没有正向节省"
                            )
                        except CloudError as exc:
                            result["pricing_note"] = str(exc)
                            failed = True
                task["results"].append(result)
            except CloudError as exc:
                task["results"].append(
                    {"resource_id": id, "error": str(exc), "code": exc.code}
                )
                failed = True
            save_task(task)
        if explain and any("diagnosis" in r for r in task["results"]):
            try:
                task["explanation"] = step(
                    task,
                    "model_explanation",
                    lambda: (
                        explain_report(task["results"], "en")
                        if task.get("language") == "en"
                        else explain_report(task["results"])
                    ),
                )
                task["explanation_status"] = "generated"
            except CloudError:
                task["explanation_status"] = "unavailable"
                failed = True
        valid = sum("diagnosis" in r for r in task["results"])
        task["status"] = "failed" if not valid else "partial" if failed else "succeeded"
    except CloudError as exc:
        task.update(status="failed", error=str(exc))
    except Exception:
        task.update(status="failed", error="任务执行失败，请检查服务连接和数据格式")
    finally:
        save_task(task)


def markdown(task: dict) -> str:
    labels = {
        "low_utilization": "低利用率候选",
        "normal": "正常负载",
        "peak_risk": "峰值风险",
        "insufficient_data": "数据不足",
        "stopped": "已停止",
    }
    lines = [
        "# 云资源分析报告",
        f"来源：{task['source']} | 地域：{task['region']} | 状态：{task['status']}",
        f"规则版本：{task['rule_version']} | UTC 窗口：{task.get('window_start', '—')} 至 {task.get('window_end', '—')}",
        "本报告提供检查建议；容量变更需人工核验业务峰值、兼容性与库存。",
    ]
    for r in task["results"]:
        if "error" in r:
            lines += [f"## {r['resource_id']}", r["error"]]
            continue
        lines += [
            f"## {r['resource']['name']} ({r['resource']['id']})",
            f"诊断：{labels[r['diagnosis']]}",
        ]
        for name in ("cpu", "memory"):
            m = r["metrics"][name]
            lines.append(
                f"- {name} 平均 {m['average']}%，最大 {m['maximum']}%，覆盖率 {m['coverage'] * 100:.2f}%"
            )
        lines += [f"- {risk}" for risk in r["risks"]]
        if r["candidate"]:
            lines.append(f"候选规格：{r['candidate']['id']}（需人工核验）")
        if r["savings"]:
            s = r["savings"]
            lines.extend(
                [
                    f"月度等价估算：{s['monthly_equivalent_saving']} {s['currency']}（{s['hours']} 小时）",
                    s["scope"],
                    s["source"],
                ]
            )
        else:
            lines.append(r["pricing_note"])
    lines += [
        "## 解释",
        task.get("explanation", "模型解释未生成；以上结构化规则结论仍可使用。"),
        "## 执行记录",
    ]
    for s in task.get("steps", []):
        lines.append(
            f"- {s['tool']} | {s['source']} | {s['status']} | {s['duration_ms']} ms"
        )
    return "\n\n".join(lines) + "\n"
