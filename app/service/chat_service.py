import asyncio
import json
import sys
import os

# 初始化 Agent 和 Graph
AGENT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent"
)
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

from core.workflow.graph_manager import AgentGraphManager
from core.memory.memory_manager import MemoryManager
from infra.cache import semantic_cache
from core.runtime import event, request_id
from core.language import language as response_language, tr
import time
import uuid

# Global variables for graph and memory
graph = None
memory = None


async def init_agent_system():
    global graph, memory
    if graph is None:
        print("🚀 初始化 Multi-Agent 图编排...")
        graph_manager = AgentGraphManager()
        graph = graph_manager.build_graph()

        print("🧠 初始化 Memory 系统...")
        from config import get_settings

        settings = get_settings()
        memory = MemoryManager(
            redis_url=settings.redis_url,
            redis_ttl=settings.redis_ttl,
            milvus_host=settings.milvus_host,
            milvus_port=settings.milvus_port,
            milvus_api_key=settings.milvus_api_key,
            embedding_api_key=settings.dashscope_api_key,
        )
        await memory.initialize()
        await semantic_cache.initialize()
        print("✅ Agent 系统初始化完成！")


async def _extract_memory_context(user_id: str, session_id: str, query: str) -> str:
    context_parts = []
    if memory and memory.short_term.available:
        history = await memory.short_term.get_messages(user_id, session_id)
        if history:
            recent_history = history[-10:] if len(history) > 10 else history
            context_parts.append("【近期对话历史】:")
            for msg in recent_history:
                role = "User" if msg["role"] == "user" else "Assistant"
                context_parts.append(f"{role}: {msg['content']}")

    if memory and memory.long_term.available:
        prefs = await memory.long_term.retrieve_relevant(user_id, query)
        if prefs:
            context_parts.append("\n【用户长期偏好/背景】:")
            for p in prefs:
                context_parts.append(f"- {p}")

    return "\n".join(context_parts)


async def _stream_chat_impl(
    query: str,
    user_id: str,
    session_id: str,
    environment: str = "demo",
    region: str = "cn-beijing",
    instance_ids: list[str] | None = None,
):
    q = query.casefold()
    if any(
        word in q
        for word in (
            "降本",
            "降配",
            "成本优化",
            "资源闲置",
            "利用率",
            "监控分析",
            "费用太高",
            "账单太贵",
            "reduce costs",
            "cost optimization",
            "cost optimisation",
            "underutilized",
            "underutilised",
            "downsizing",
            "utilization analysis",
            "utilisation analysis",
        )
    ):
        from cloudops import service as ops
        from cloudops.providers import CloudError

        try:
            ids = instance_ids
            if ids is None:
                inventory = await asyncio.to_thread(ops.resources, environment, region)
                ids = [r["id"] for r in inventory]
            if not ids:
                raise CloudError("EmptyResources", "当前环境和地域没有可分析的实例")
            task = await asyncio.to_thread(
                ops.create_task,
                environment,
                region,
                ids,
                language=response_language.get(),
            )
            yield f"data: {json.dumps({'report': {'id':task['id'],'environment':environment,'status':task['status']}})}\n\n"
            text = (
                f"Cloud resource analysis created. Source: {tr(task['source'])}. Open the report to review monitoring evidence, candidate types and execution steps."
                if response_language.get() == "en"
                else f"已创建云资源分析任务，数据来源：{task['source']}。请打开分析报告查看监控依据、候选规格及执行步骤。"
            )
            yield f"data: {json.dumps({'content':text})}\n\n"
        except CloudError as exc:
            yield f"data: {json.dumps({'content':tr(str(exc)),'error':exc.code})}\n\n"
        yield f"data: {json.dumps({'done':True})}\n\n"
        return
    if environment == "aliyun" and any(
        word in q
        for word in (
            "账单",
            "订单",
            "海报",
            "返佣",
            "billing",
            "orders",
            "poster",
            "commission",
        )
    ):
        yield f"data: {json.dumps({'content':tr('当前阿里云环境只接入 ECS 资源、监控和计算规格询价，尚未接入真实账单、订单或营销服务。')})}\n\n"
        yield f"data: {json.dumps({'done':True})}\n\n"
        return
    if any(word in q for word in ("实例", "服务器", "instances", "servers")) and any(
        word in q
        for word in (
            "查询",
            "查看",
            "列出",
            "名下",
            "所有",
            "list",
            "show",
            "my",
            "all",
        )
    ):
        from cloudops import service as ops
        from cloudops.providers import CloudError

        try:
            inventory = await asyncio.to_thread(ops.resources, environment, region)
            if "running" in q or "运行中" in q:
                inventory = [
                    resource
                    for resource in inventory
                    if resource["status"] == "Running"
                ]
            text = f"数据来源：{'演示数据' if environment=='demo' else '阿里云只读接口'}，地域：{region}。\n\n"
            if response_language.get() == "en":
                text = f"Source: {tr('演示数据' if environment == 'demo' else '阿里云只读接口')}; region: {region}.\n\n"
            text += "\n".join(
                f"- {r['id']}: {r['instance_type']}, {r['status']}, {r['cpu']} vCPU / {r['memory_gb']} GiB"
                for r in inventory
            ) or (
                "No instances found."
                if response_language.get() == "en"
                else "当前没有实例。"
            )
        except CloudError as exc:
            text = tr(str(exc))
        yield f"data: {json.dumps({'content':text})}\n\n"
        yield f"data: {json.dumps({'done':True})}\n\n"
        return
    # Responses may depend on history and live tools: do not reuse unversioned legacy QA cache.
    cache_hit = None
    if cache_hit:
        response_text = cache_hit["answer"]
        print(
            f"⚡ 语义缓存命中: {cache_hit['level']} distance={cache_hit['distance']:.4f} matched='{cache_hit['matched_question']}'"
        )
    else:
        print("🏃 进入 Agent 工作流推理...")
        mem_context = await _extract_memory_context(user_id, session_id, query)
        state = {
            "messages": [("user", query)],
            "user_id": user_id,
            "session_id": session_id,
            "memory_context": mem_context,
            "next_agent": "",
            "metadata": {
                "environment": environment,
                "region": region,
                "instance_ids": instance_ids,
                "language": response_language.get(),
            },
        }
        config = {"configurable": {"user_id": user_id}}
        config["recursion_limit"] = 24
        result = await asyncio.wait_for(
            graph.ainvoke(state, config=config), timeout=150
        )
        response_text = result["messages"][-1].content

    # 保存短时记忆
    if memory and memory.short_term.available:
        turn = [
            {"role": "user", "content": query},
            {"role": "assistant", "content": response_text},
        ]
        await memory.save_conversation(user_id, session_id, turn)

    # 流式返回大模型结果
    chunk_size = 120
    for i in range(0, len(response_text), chunk_size):
        chunk = response_text[i : i + chunk_size]
        yield f"data: {json.dumps({'content': chunk})}\n\n"
        await asyncio.sleep(0)

    yield f"data: {json.dumps({'done': True})}\n\n"


async def stream_chat(
    query: str,
    user_id: str,
    session_id: str,
    environment: str = "demo",
    region: str = "cn-beijing",
    instance_ids: list[str] | None = None,
    language: str = "zh",
):
    """SSE boundary: correlation id, bounded workflow and sanitized terminal errors."""
    if language not in {"zh", "en"}:
        raise ValueError("Unsupported response language")
    language_token = response_language.set(language)
    token = request_id.set(uuid.uuid4().hex)
    started = time.monotonic()
    try:
        yield "data: " + json.dumps({"request_id": request_id.get()}) + "\n\n"
        async for chunk in _stream_chat_impl(
            query, user_id, session_id, environment, region, instance_ids
        ):
            yield chunk
    except asyncio.CancelledError:
        event("chat", status="cancelled")
        raise
    except Exception as exc:
        # Last-resort streaming boundary; never expose provider errors or credentials.
        event("chat", status="failed", error=type(exc).__name__)
        yield "data: " + json.dumps(
            {"error": "RequestFailed", "content": tr("本次请求未完成，请稍后重试。")},
            ensure_ascii=False,
        ) + "\n\n"
        yield 'data: {"done": true}\n\n'
    finally:
        event("chat_finished", elapsed_ms=round((time.monotonic() - started) * 1000))
        request_id.reset(token)
        response_language.reset(language_token)
