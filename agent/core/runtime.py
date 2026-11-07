"""Bounded calls and privacy-preserving request diagnostics."""

import asyncio
import functools
import json
import logging
import time
from contextvars import ContextVar
from core.language import tr
from openai import APIConnectionError, APITimeoutError, RateLimitError

request_id = ContextVar("request_id", default="cli")
logger = logging.getLogger("cloudagent.trace")
logger.setLevel(logging.INFO)


def event(stage: str, **fields: object) -> None:
    """Log operational metadata only; callers must not pass prompts or credentials."""
    logger.info(
        json.dumps(
            {"request_id": request_id.get(), "stage": stage, **fields},
            ensure_ascii=False,
        )
    )


async def invoke_model(model, messages, timeout: float = 30):
    """Retry transient model failures once; never replay business tool calls."""
    for attempt in range(2):
        try:
            return await asyncio.wait_for(model.ainvoke(messages), timeout=timeout)
        except (APIConnectionError, APITimeoutError, RateLimitError, TimeoutError):
            if attempt == 1:
                raise
            event("model_retry", attempt=attempt + 1)
            await asyncio.sleep(0.25)


def bounded_node(name: str, node, timeout: float = 120):
    """Bound one graph node and log outcome, without retrying side effects."""

    @functools.wraps(node if hasattr(node, "__name__") else node.__call__)
    async def run(state):
        started = time.monotonic()
        if state.get("metadata", {}).get("environment") == "aliyun" and name in {
            "billing_agent",
            "recommendation_agent",
            "promotion_agent",
        }:
            from langchain_core.messages import AIMessage

            return {
                "messages": [
                    AIMessage(
                        content=tr(
                            "当前阿里云环境尚未接入真实订单、营销或商品目录，请使用资源查询与成本分析功能。"
                        )
                    )
                ]
            }
        try:
            result = await asyncio.wait_for(node(state), timeout)
        except Exception as exc:
            event(
                "node",
                node=name,
                status="failed",
                error=type(exc).__name__,
                elapsed_ms=round((time.monotonic() - started) * 1000),
            )
            raise
        event(
            "node",
            node=name,
            status="ok",
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
        return result

    return run
