"""Read-only demo and Alibaba Cloud adapters. No implicit data-source fallback."""

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Protocol
from cloudops.models import Resource, Sample, Quote
from cloudops import store
from cloudops.rules import window


class CloudError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Provider(Protocol):
    def resources(self, region: str) -> list[Resource]: ...
    def samples(
        self, resource: Resource, start: datetime, end: datetime
    ) -> list[Sample]: ...
    def specs(self, resource: Resource) -> list[dict]: ...
    def quote(self, resource: Resource, spec: str) -> Quote: ...


def seed_demo() -> None:
    """Idempotently refresh only the six named workbench demo resources."""
    start, end = window()
    scenarios = [
        ("idle", "低利用率", 3, 18),
        ("normal", "正常负载", 35, 50),
        ("busy", "持续高负载", 82, 88),
        ("spike", "低均值高峰值", 3, 18),
        ("missing", "缺失内存监控", 3, None),
        ("stopped", "已停止实例", 0, 0),
    ]
    for key, name, cpu, mem in scenarios:
        resource = Resource(
            id=f"demo-{key}",
            name=name,
            environment="demo",
            region="cn-beijing",
            instance_type="demo.g8a.4xlarge",
            family="demo.g8a",
            cpu=16,
            memory_gb=64,
            status="Stopped" if key == "stopped" else "Running",
            updated_at=datetime.now(timezone.utc),
        )
        samples = []
        for i in range(2016):
            peak = 95 if key == "spike" and i == 1000 else cpu
            samples.append(
                Sample(
                    timestamp=start + timedelta(seconds=300 * i),
                    cpu=cpu,
                    memory=mem,
                    cpu_max=peak,
                    memory_max=mem,
                ).model_dump(mode="json")
            )
        payload = {
            "resource": resource.model_dump(mode="json"),
            "samples": samples,
            "window_end": end.isoformat(),
        }
        store.execute(
            "INSERT INTO ops_demo_resources(id,payload) VALUES(%s,%s) ON DUPLICATE KEY UPDATE payload=VALUES(payload)",
            (resource.id, json.dumps(payload, ensure_ascii=False)),
        )


class DemoProvider:
    def resources(self, region: str) -> list[Resource]:
        return [
            Resource.model_validate(store.decode(row["payload"])["resource"])
            for row in store.rows(
                "SELECT payload FROM ops_demo_resources ORDER BY id LIMIT 20"
            )
            if store.decode(row["payload"])["resource"]["region"] == region
        ]

    def samples(
        self, resource: Resource, start: datetime, end: datetime
    ) -> list[Sample]:
        rows = store.rows(
            "SELECT payload FROM ops_demo_resources WHERE id=%s", (resource.id,)
        )
        if not rows:
            raise CloudError("NotFound", "演示实例不存在")
        return [
            Sample.model_validate(s)
            for s in store.decode(rows[0]["payload"])["samples"]
        ]

    def specs(self, resource: Resource) -> list[dict]:
        return [
            {"id": "demo.g8a.2xlarge", "family": "demo.g8a", "cpu": 8, "memory_gb": 32}
        ]

    def quote(self, resource: Resource, spec: str) -> Quote:
        prices = {"demo.g8a.4xlarge": 4.0, "demo.g8a.2xlarge": 2.0}
        return Quote(
            amount=prices[spec],
            currency="CNY",
            region=resource.region,
            os=resource.os,
            source="示例价格，非真实云报价",
        )


def regions() -> list[str]:
    return [
        s.strip()
        for s in os.getenv("ALIYUN_REGIONS", "cn-beijing").split(",")
        if s.strip()
    ]


def configured() -> bool:
    return bool(
        os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
        and os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
    )


class AliyunProvider:
    """Official SDK requests only; injected clients support offline contract tests."""

    def __init__(self, ecs=None, cms=None, region=None):
        if ecs is not None and cms is not None:
            self.ecs, self.cms = ecs, cms
            return
        if not configured():
            raise CloudError(
                "NotConfigured",
                "阿里云尚未配置只读凭据，请在服务端 agent/.env 填写配置并重启",
            )
        from alibabacloud_ecs20140526.client import Client as ECS
        from alibabacloud_cms20190101.client import Client as CMS
        from alibabacloud_tea_openapi.models import Config

        config = Config(
            access_key_id=os.environ["ALIBABA_CLOUD_ACCESS_KEY_ID"],
            access_key_secret=os.environ["ALIBABA_CLOUD_ACCESS_KEY_SECRET"],
            security_token=os.getenv("ALIBABA_CLOUD_SECURITY_TOKEN"),
            region_id=region or regions()[0],
        )
        self.ecs = ECS(config)
        self.cms = CMS(config)

    def _call(self, service: str, action: str, **params) -> dict:
        from alibabacloud_ecs20140526 import models as ecs_models
        from alibabacloud_cms20190101 import models as cms_models
        from alibabacloud_tea_util.models import RuntimeOptions

        allowed = {
            "describe_instances",
            "describe_instance_types",
            "describe_price",
            "describe_metric_list",
        }
        if action not in allowed:
            raise CloudError("ForbiddenAction", "不允许调用此云操作")
        models = ecs_models if service == "ecs" else cms_models
        name = "".join(part.capitalize() for part in action.split("_")) + "Request"
        request = getattr(models, name)(**params)
        for attempt in range(2):
            try:
                response = getattr(
                    self.ecs if service == "ecs" else self.cms, action + "_with_options"
                )(
                    request,
                    RuntimeOptions(
                        connect_timeout=3000, read_timeout=8000, autoretry=False
                    ),
                )
                body = response.body.to_map()
                if body.get("Success") is False:
                    raise CloudError("MonitoringUnavailable", "云监控未返回成功结果")
                return body
            except CloudError:
                raise
            except Exception as exc:
                # SDK exception messages can contain request details. Never propagate them.
                code = str(getattr(exc, "code", ""))
                transient = any(
                    k in code.lower()
                    for k in ("throttl", "timeout", "serviceunavailable")
                ) or isinstance(exc, TimeoutError)
                if transient and attempt == 0:
                    time.sleep(0.2)
                    continue
                if any(
                    k in code.lower()
                    for k in ("access", "auth", "forbid", "signature", "permission")
                ):
                    raise CloudError(
                        "AccessDenied", "阿里云凭据或只读权限校验失败"
                    ) from None
                raise CloudError(
                    "CloudUnavailable",
                    "云接口超时、限流或不可用，请检查连接及权限后重试",
                ) from None
        raise CloudError("CloudUnavailable", "云接口不可用")

    def resources(self, region: str) -> list[Resource]:
        result = []
        token = None
        seen = set()
        for _ in range(10):
            body = self._call(
                "ecs",
                "describe_instances",
                region_id=region,
                max_results=100,
                next_token=token,
            )
            for item in body.get("Instances", {}).get("Instance", []):
                if item["InstanceId"] in seen:
                    continue
                seen.add(item["InstanceId"])
                result.append(
                    Resource(
                        id=item["InstanceId"],
                        name=item.get("InstanceName") or item["InstanceId"],
                        environment="aliyun",
                        region=region,
                        instance_type=item["InstanceType"],
                        family=item.get("InstanceTypeFamily")
                        or ".".join(item["InstanceType"].split(".")[:2]),
                        cpu=item["Cpu"],
                        memory_gb=item["Memory"] / 1024,
                        status=item["Status"],
                        billing=item.get("InstanceChargeType", "Unknown"),
                        spot=item.get("SpotStrategy", "NoSpot") != "NoSpot",
                        os=item.get("OSType", "linux").lower(),
                        updated_at=datetime.now(timezone.utc),
                    )
                )
            token = body.get("NextToken")
            if not token:
                return result
        raise CloudError(
            "ResourceLimit", "资源超过首版 1000 台读取上限，请缩小环境地域范围"
        )

    def samples(
        self, resource: Resource, start: datetime, end: datetime
    ) -> list[Sample]:
        merged = {}
        for field, metric in [
            ("cpu", "CPUUtilization"),
            ("memory", "memory_usedutilization"),
        ]:
            token = None
            seen = set()
            for _ in range(20):
                body = self._call(
                    "cms",
                    "describe_metric_list",
                    namespace="acs_ecs_dashboard",
                    metric_name=metric,
                    period="300",
                    dimensions=json.dumps([{"instanceId": resource.id}]),
                    start_time=str(int(start.timestamp() * 1000)),
                    end_time=str(int(end.timestamp() * 1000)),
                    length="1440",
                    next_token=token,
                    region_id=resource.region,
                )
                points = json.loads(body.get("Datapoints") or "[]")
                if not isinstance(points, list):
                    raise CloudError("InvalidMetrics", "监控返回格式不正确")
                for p in points:
                    stamp = float(p["timestamp"])
                    stamp = stamp / 1000 if stamp > 1e11 else stamp
                    timestamp = datetime.fromtimestamp(stamp, timezone.utc)
                    # Duplicate metric points must not silently replace each other.
                    key = (field, stamp)
                    entry = merged.setdefault(stamp, {"timestamp": timestamp})
                    if key in seen:
                        entry[field] = None
                        entry[field + "_max"] = None
                        continue
                    seen.add(key)
                    entry[field] = p.get("Average")
                    entry[field + "_max"] = p.get("Maximum")
                next_token = body.get("NextToken")
                if not next_token:
                    break
                if next_token == token:
                    raise CloudError("PaginationError", "监控分页未推进")
                token = next_token
            else:
                raise CloudError("MetricLimit", "监控分页超过上限")
        try:
            return [Sample.model_validate(s) for s in merged.values()]
        except (ValueError, TypeError):
            raise CloudError("InvalidMetrics", "监控值不在有效范围") from None

    def specs(self, resource: Resource) -> list[dict]:
        specs = []
        token = None
        for _ in range(10):
            body = self._call(
                "ecs",
                "describe_instance_types",
                instance_type_family=resource.family,
                max_results=100,
                next_token=token,
            )
            specs.extend(
                {
                    "id": s["InstanceTypeId"],
                    "family": s["InstanceTypeFamily"],
                    "cpu": s["CpuCoreCount"],
                    "memory_gb": s["MemorySize"],
                }
                for s in body.get("InstanceTypes", {}).get("InstanceType", [])
            )
            next_token = body.get("NextToken")
            if not next_token:
                return specs
            if next_token == token:
                raise CloudError("PaginationError", "规格分页未推进")
            token = next_token
        raise CloudError("SpecLimit", "实例规格超过读取上限")

    def quote(self, resource: Resource, spec: str) -> Quote:
        if resource.os not in ("linux", "windows"):
            raise CloudError(
                "PriceUnavailable", "操作系统类型不明确，无法进行同系统询价"
            )
        body = self._call(
            "ecs",
            "describe_price",
            region_id=resource.region,
            resource_type="instance",
            instance_type=spec,
            price_unit="Hour",
            period=1,
            amount=1,
            io_optimized="optimized",
            instance_network_type="vpc",
            platform="Windows" if resource.os == "windows" else "Linux",
        )
        price = body.get("PriceInfo", {}).get("Price", {})
        # OriginalPrice avoids presenting promotional discounts as a durable saving.
        details = [
            d
            for d in price.get("DetailInfos", {}).get("DetailInfo", [])
            if d.get("Resource") == "instanceType"
        ]
        if (
            len(details) != 1
            or details[0].get("OriginalPrice") is None
            or not price.get("Currency")
        ):
            raise CloudError("PriceUnavailable", "未获得可比较的计算规格报价")
        return Quote(
            amount=details[0]["OriginalPrice"],
            currency=price["Currency"],
            region=resource.region,
            os=resource.os,
            source="阿里云 DescribePrice 原价询价（非实际账单）",
        )


def provider(environment: str, region: str) -> Provider:
    if environment not in ("demo", "aliyun"):
        raise CloudError("InvalidEnvironment", "环境不存在")
    if region not in (["cn-beijing"] if environment == "demo" else regions()):
        raise CloudError("InvalidRegion", "地域不在服务端允许列表")
    return DemoProvider() if environment == "demo" else AliyunProvider(region=region)
