"""Validated intent routing with bounded calls and conversation context."""

import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from pydantic import ValidationError
from openai import OpenAIError
from core.routing import RouteDecision, ROUTING_PROMPT
from core.language import instruction, language
from core.runtime import event, invoke_model


class OrchestratorAgent:
    def __init__(self, llm=None):
        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        self.llm = llm or ChatOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            model=os.getenv("MODEL", "qwen-plus"),
            base_url=os.getenv(
                "BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
            ),
            temperature=0,
            timeout=25,
            max_retries=0,
        )

    async def route(self, state):
        messages = list(state.get("messages", []))[-10:]
        context = state.get("memory_context", "")[-6000:]
        try:
            response = await invoke_model(
                self.llm,
                [
                    SystemMessage(content=ROUTING_PROMPT + instruction()),
                    HumanMessage(content="背景数据：\n" + context),
                ]
                + messages,
            )
            decision = RouteDecision.model_validate_json(response.content)
            if decision.needs_clarification and not decision.clarification.strip():
                raise ValueError("Missing clarification")
            status = "ok"
        except (
            ValidationError,
            ValueError,
            TypeError,
            OpenAIError,
            TimeoutError,
        ) as exc:
            decision = RouteDecision(
                agent="product_agent",
                needs_clarification=True,
                clarification=(
                    "Would you like product information, order details, configuration advice or cost analysis?"
                    if language.get() == "en"
                    else "你想了解产品知识、查询个人账单、选择配置，还是分析资源成本？"
                ),
            )
            status = type(exc).__name__
        metadata = dict(state.get("metadata") or {})
        metadata.update(
            is_finops_workflow=decision.agent == "finops_agent",
            routing=decision.model_dump(),
        )
        event(
            "routing",
            agent=decision.agent,
            status=status,
            needs_clarification=decision.needs_clarification,
        )
        return {"next_agent": decision.agent, "metadata": metadata}
