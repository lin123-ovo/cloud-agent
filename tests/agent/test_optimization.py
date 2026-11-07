import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from core.retrieval import Passage, lexical_search, fuse, rerank, tokens
from core.runtime import bounded_node
from tools.graph_tool import validate_read_query, execute_read
from agents.orchestrator import OrchestratorAgent
from agents.billing_agent import UserIdInjector
from langchain_mcp_adapters.interceptors import MCPToolCallRequest
from schemas.chat import ChatRequest
from pydantic import ValidationError


def test_bm25_exact_model_and_unknown():
    docs = [
        Passage("ecs.g8a.xlarge 4 vCPU", "a.md"),
        Passage("ecs.c7.large 2 vCPU", "b.md"),
    ]
    assert lexical_search("ecs.g8a.xlarge", docs)[0] == docs[0]
    assert lexical_search("量子咖啡", docs) == []
    assert lexical_search("", docs) == []
    assert "退款" in tokens("退款规则")


def test_rrf_deduplicates_and_rewards_consensus():
    a, b, c = (Passage(x, x + ".md") for x in "abc")
    assert fuse([[a, b, b], [b, c]])[0] == b
    assert len(fuse([[a, a], [a]])) == 1


@pytest.mark.parametrize(
    "query",
    [
        "MATCH (n) DELETE n RETURN n",
        "CALL dbms.components() YIELD name RETURN name",
        "MATCH (n) RETURN n; MATCH (b) RETURN b",
        "MATCH (n) SET n.x=1 RETURN n",
        "MATCH (n) /*safe*/ RETURN n",
        "MATCH (n)-[*]->(b) RETURN b",
        "MATCH (n) RETURN n UNION MATCH (b) RETURN b",
        "MATCH (n) FOREACH (x IN [1] | CREATE ()) RETURN n",
        "MATCH (n) CALL { CREATE () } RETURN n",
        "RETURN 1",
        "",
    ],
)
def test_rejects_graph_writes_and_unsupported_syntax(query):
    with pytest.raises(ValueError):
        validate_read_query(query)


def test_graph_read_literals_and_parameterization():
    assert "LIMIT 20" in validate_read_query("MATCH (n {name:'CREATE'}) RETURN n")
    assert "$keywords" in validate_read_query(
        "MATCH (n) WHERE any(k IN $keywords WHERE n.id CONTAINS k) RETURN n"
    )


def test_read_uses_explicit_transaction_and_bound_params():
    class Result:
        def data(self):
            return {"ok": 1}

    class Tx:
        def run(self, query, params):
            assert "$keywords" in query
            assert params == {"keywords": ["x' OR true"]}
            return [Result()]

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute_read(self, fn):
            return fn(Tx())

    class Driver:
        def session(self, **kw):
            assert kw["default_access_mode"] == "READ"
            return Session()

    assert execute_read(
        SimpleNamespace(_driver=Driver(), _database="neo4j"),
        "MATCH (n) WHERE n.id IN $keywords RETURN n",
        {"keywords": ["x' OR true"]},
    ) == [{"ok": 1}]


def test_router_context_and_metadata_reset():
    llm = SimpleNamespace(
        ainvoke=AsyncMock(
            return_value=SimpleNamespace(
                content=json.dumps(
                    {
                        "agent": "recommendation_agent",
                        "needs_clarification": False,
                        "clarification": "",
                    }
                )
            )
        )
    )
    state = {
        "messages": [
            ("user", "Java+MySQL"),
            ("assistant", "预算呢"),
            ("user", "500以内"),
        ],
        "metadata": {"environment": "demo", "is_finops_workflow": True},
        "memory_context": "历史偏好",
    }
    result = asyncio.run(OrchestratorAgent(llm).route(state))
    assert result["next_agent"] == "recommendation_agent"
    assert result["metadata"]["is_finops_workflow"] is False
    assert state["metadata"]["is_finops_workflow"] is True
    assert len(llm.ainvoke.call_args.args[0]) == 5


@pytest.mark.parametrize(
    "output",
    [
        "deep_research_agent",
        '{"agent":"evil"}',
        '{"agent":"billing_agent","extra":1}',
        '{"agent":"billing_agent","needs_clarification":true}',
    ],
)
def test_invalid_route_clarifies(output):
    llm = SimpleNamespace(
        ainvoke=AsyncMock(return_value=SimpleNamespace(content=output))
    )
    result = asyncio.run(OrchestratorAgent(llm).route({"messages": []}))
    assert result["metadata"]["routing"]["needs_clarification"]
    assert result["next_agent"] == "product_agent"


def test_tool_identity_fail_closed_and_override():
    handler = AsyncMock(return_value="ok")
    request = MCPToolCallRequest(
        name="query_user_orders", args={"user_id": "victim"}, server_name="cloud"
    )
    with pytest.raises(PermissionError):
        asyncio.run(UserIdInjector()(request, handler))
    handler.assert_not_called()
    request.runtime = SimpleNamespace(
        config={"configurable": {"user_id": "server-owner"}}
    )
    assert asyncio.run(UserIdInjector()(request, handler)) == "ok"
    assert handler.call_args.args[0].args["user_id"] == "server-owner"


def test_non_identity_tool_unchanged():
    handler = AsyncMock(return_value="ok")
    req = MCPToolCallRequest(
        name="search_product_catalog", args={"keyword": "ecs"}, server_name="cloud"
    )
    asyncio.run(UserIdInjector()(req, handler))
    assert handler.call_args.args[0].args == {"keyword": "ecs"}


def test_bounded_node_no_replay():
    async def slow(state):
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError):
        asyncio.run(bounded_node("slow", slow, timeout=0.001)({}))


@pytest.mark.parametrize(
    "data",
    [
        {"query": "   "},
        {"query": "x", "session_id": 'a" OR true'},
        {"query": "x", "user_id": None},
    ],
)
def test_request_validation(data):
    with pytest.raises(ValidationError):
        ChatRequest(**data)


def test_rerank_failure_and_low_evidence(monkeypatch):
    import core.retrieval as retrieval
    import httpx

    monkeypatch.setenv("RERANK_MODEL", "test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dummy")
    docs = [Passage("A", "a.md"), Passage("B", "b.md")]

    def fail(*a, **kw):
        raise httpx.ConnectError("do not log credentials")

    monkeypatch.setattr(retrieval.httpx, "post", fail)
    assert rerank("q", docs) == docs
    monkeypatch.setenv("RERANK_MIN_SCORE", "0.5")
    monkeypatch.setattr(
        retrieval.httpx,
        "post",
        lambda *a, **kw: SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "output": {"results": [{"index": 1, "relevance_score": 0.1}]}
            },
        ),
    )
    assert rerank("q", docs) == []


def test_vector_outage_keeps_local_evidence(monkeypatch):
    from tools import vector_tool

    def unavailable():
        raise ConnectionError("secret")

    monkeypatch.setattr(vector_tool, "_get_milvus_store", unavailable)
    monkeypatch.delenv("RERANK_MODEL", raising=False)
    result = vector_tool.query_vector_db.invoke({"query": "ecs.g8a.xlarge 网卡"})
    assert "ecs_product_info.md" in result
    assert "secret" not in result


def test_chat_error_terminal_event_and_redaction(monkeypatch):
    from service import chat_service

    monkeypatch.setattr(
        chat_service, "_extract_memory_context", AsyncMock(return_value="")
    )
    monkeypatch.setattr(
        chat_service,
        "graph",
        SimpleNamespace(ainvoke=AsyncMock(side_effect=RuntimeError("secret"))),
    )

    async def collect():
        return [x async for x in chat_service.stream_chat("什么是VPC", "server", "s")]

    chunks = asyncio.run(collect())
    assert "secret" not in "".join(chunks)
    assert "RequestFailed" in "".join(chunks)
    assert json.loads(chunks[-1][6:])["done"] is True


def test_endpoint_ignores_browser_identity(monkeypatch):
    import router.chat as router

    seen = []

    async def stream(*args, **kwargs):
        seen.append(args)
        yield 'data: {"done":true}\n\n'

    monkeypatch.setattr(router, "stream_chat", stream)
    monkeypatch.setenv("CLOUDAGENT_OPERATOR_ID", "server-owner")

    async def run():
        response = await router.chat_endpoint(
            ChatRequest(query="订单", user_id="victim")
        )
        return [chunk async for chunk in response.body_iterator]

    asyncio.run(run())
    assert seen[0][1] == "server-owner"


def test_standalone_tool_and_public_exports_import_in_fresh_process():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from tools.graph_tool import query_knowledge_graph; from core import AgentGraphManager; from agents import ProductAgentNode",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_business_tools_reject_direct_identity_bypass(monkeypatch):
    from mcp_servers import cloud_platform_server as server

    monkeypatch.setenv("CLOUDAGENT_OPERATOR_ID", "owner")

    def db_forbidden():
        raise AssertionError("Unauthorized DB access")

    monkeypatch.setattr(server, "get_db_connection", db_forbidden)
    assert "拒绝访问" in server.query_user_orders("victim")
    assert "拒绝访问" in server.query_user_instances("victim")
    assert "limit" in server.query_user_orders("owner", 0)
    assert "limit" in server.query_user_instances("owner", True)
    assert "拒绝访问" in server.analyze_instance_usage("i-victim", "victim")


def test_mcp_promotion_schema_not_overwritten():
    from mcp_servers.cloud_platform_server import mcp

    tools = asyncio.run(mcp.list_tools())
    tools = [tool for tool in tools if tool.name == "get_promotion_materials"]
    assert len(tools) == 1
    assert "product_id" in tools[0].inputSchema["properties"]


def test_real_environment_cannot_use_demo_catalog():
    node = AsyncMock()
    result = asyncio.run(
        bounded_node("recommendation_agent", node)(
            {"metadata": {"environment": "aliyun"}}
        )
    )
    node.assert_not_called()
    assert "尚未接入" in result["messages"][0].content


def test_recommendation_does_not_invent_billing_period_or_bundle():
    from agents.recommendation_agent import render_catalog

    answer = render_catalog(
        [{"product_id": "p", "product_name": "ECS示例", "price": 299}]
    )
    assert "¥299" in answer
    assert "/年" not in answer
    assert "201元" not in answer
    assert "计费周期" in answer
    assert "示例" in answer


def test_citations_only_from_returned_tool_payload():
    from core.evidence import grounded_sources

    message = SimpleNamespace(type="tool", content="【来源: real.md；片段: 123】退款")
    answer = grounded_sources("答案正文\n答案来源：\n- invented.md", [message])
    assert "real.md" in answer and "invented.md" not in answer
    assert "答案来源" not in grounded_sources("没有记录\n答案来源：\n- 图谱未找到", [])
