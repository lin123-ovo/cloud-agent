import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from pydantic import ValidationError
from core.language import language, tr, instruction
from core.evidence import grounded_sources
from agents.recommendation_agent import render_catalog
from schemas.chat import ChatRequest
from cloudops.report_english import markdown_english


def test_language_schema_defaults_and_rejects_invalid():
    assert ChatRequest(query="hello").language == "zh"
    assert ChatRequest(query="hello", language="en").language == "en"
    with pytest.raises(ValidationError):
        ChatRequest(query="hello", language="de")


def test_english_catalog_preserves_price_and_identifiers():
    token = language.set("en")
    try:
        answer = render_catalog(
            [{"product_name": "第八代企业级通用型实例 ecs.g8a.xlarge", "price": 299}]
        )
        assert "ecs.g8a.xlarge" in answer and "¥299" in answer
        assert "billing periods" in answer and "/year" not in answer
        assert "第八代" not in answer
    finally:
        language.reset(token)


def test_english_evidence_retains_real_filename():
    token = language.set("en")
    try:
        answer = grounded_sources(
            "One refund. Sources: invented.md",
            [
                SimpleNamespace(
                    type="tool",
                    content="【来源: billing_and_refund_policy.md；片段:abc】退款",
                )
            ],
        )
        assert "Sources:" in answer and "billing_and_refund_policy.md" in answer
        assert "invented.md" not in answer
        assert "No supporting" in grounded_sources("x", [])
    finally:
        language.reset(token)


def test_language_context_does_not_leak_between_concurrent_requests():
    async def request(lang):
        token = language.set(lang)
        try:
            await asyncio.sleep(0)
            return tr("演示数据"), instruction()
        finally:
            language.reset(token)

    async def run():
        return await asyncio.gather(request("en"), request("zh"))

    en, zh = asyncio.run(run())
    assert en[0] == "Demo data" and zh[0] == "演示数据"
    assert "English" in en[1] and "中文" in zh[1]
    assert language.get() == "zh"


def test_english_report_keeps_numbers_ids_and_original_data():
    task = {
        "source": "演示数据",
        "region": "cn-beijing",
        "status": "succeeded",
        "rule_version": "v1",
        "results": [
            {
                "resource": {"name": "低利用率", "id": "demo-idle"},
                "diagnosis": "low_utilization",
                "metrics": {
                    n: {"average": 3, "maximum": 18, "coverage": 1}
                    for n in ["cpu", "memory"]
                },
                "risks": ["监控覆盖率不足 90%"],
                "candidate": {"id": "demo.g8a.2xlarge"},
                "savings": {
                    "monthly_equivalent_saving": 1460,
                    "currency": "CNY",
                    "hours": 730,
                    "scope": "仅计算规格询价对比，排除磁盘、网络、优惠；不是实际账单或保证节省金额",
                    "source": "示例价格，非真实云报价",
                },
                "pricing_note": "",
            }
        ],
    }
    before = copy.deepcopy(task)
    report = markdown_english(task)
    assert "Cloud resource analysis report" in report
    assert "1460 CNY (730 hours)" in report and "demo.g8a.2xlarge" in report
    assert "Monitoring coverage is below 90%" in report
    assert task == before


def test_chat_endpoint_forwards_language_and_uses_server_identity(monkeypatch):
    import router.chat as router

    seen = []

    async def stream(*args, **kwargs):
        seen.append((args, kwargs))
        yield 'data: {"done":true}\n\n'

    monkeypatch.setattr(router, "stream_chat", stream)
    monkeypatch.setenv("CLOUDAGENT_OPERATOR_ID", "owner")

    async def run():
        result = await router.chat_endpoint(
            ChatRequest(query="hi", language="en", user_id="victim")
        )
        return [chunk async for chunk in result.body_iterator]

    asyncio.run(run())
    assert seen[0][0][1] == "owner" and seen[0][1]["language"] == "en"


def test_english_stream_error_is_localized_and_context_resets(monkeypatch):
    from service import chat_service

    monkeypatch.setattr(
        chat_service, "_extract_memory_context", AsyncMock(return_value="")
    )
    monkeypatch.setattr(
        chat_service,
        "graph",
        SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("secret"))),
    )

    async def run():
        chunks = [
            x
            async for x in chat_service.stream_chat(
                "hello", "owner", "s", language="en"
            )
        ]
        assert language.get() == "zh"
        return "".join(chunks)

    answer = asyncio.run(run())
    assert "secret" not in answer and "could not be completed" in answer


def test_english_inventory_uses_resource_fast_path(monkeypatch):
    from service import chat_service
    from cloudops import service

    monkeypatch.setattr(
        service,
        "resources",
        lambda *args: [
            {
                "id": "demo-idle",
                "instance_type": "demo.g8a.4xlarge",
                "status": "Running",
                "cpu": 16,
                "memory_gb": 64,
            }
        ],
    )

    async def run():
        return [
            x
            async for x in chat_service.stream_chat(
                "List all my instances", "owner", "s", language="en"
            )
        ]

    events = [json.loads(x[6:]) for x in asyncio.run(run())]
    content = "".join(e.get("content", "") for e in events)
    assert "Source: Demo data" in content and "demo-idle" in content


def test_english_cost_intent_emits_report_event(monkeypatch):
    from service import chat_service
    from cloudops import service

    seen = []

    def create(*args, **kwargs):
        seen.append(kwargs["language"])
        return {"id": "report-id", "status": "queued", "source": "演示数据"}

    monkeypatch.setattr(service, "create_task", create)

    async def run():
        return [
            x
            async for x in chat_service.stream_chat(
                "Reduce costs for my servers",
                "owner",
                "s",
                instance_ids=["demo-idle"],
                language="en",
            )
        ]

    events = [json.loads(x[6:]) for x in asyncio.run(run())]
    assert any(e.get("report", {}).get("id") == "report-id" for e in events)
    assert seen == ["en"]


def test_english_running_instances_excludes_stopped(monkeypatch):
    from service import chat_service
    from cloudops import service

    monkeypatch.setattr(
        service,
        "resources",
        lambda *args: [
            {
                "id": "running-id",
                "instance_type": "demo.x",
                "status": "Running",
                "cpu": 16,
                "memory_gb": 64,
            },
            {
                "id": "stopped-id",
                "instance_type": "demo.x",
                "status": "Stopped",
                "cpu": 16,
                "memory_gb": 64,
            },
        ],
    )

    async def run():
        return [
            x
            async for x in chat_service.stream_chat(
                "List my running instances", "owner", "s", language="en"
            )
        ]

    events = [json.loads(x[6:]) for x in asyncio.run(run())]
    content = "".join(e.get("content", "") for e in events)
    assert "running-id" in content and "stopped-id" not in content
