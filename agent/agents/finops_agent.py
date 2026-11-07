"""FinOps node delegates authoritative analysis to the shared workbench service."""

import asyncio
from core.language import language, tr
from langchain_core.messages import AIMessage
from cloudops import service
from cloudops.providers import CloudError


class FinOpsAgentNode:
    def __init__(self):
        pass

    async def __call__(self, state):
        metadata = state.get("metadata", {})
        environment = metadata.get("environment", "demo")
        region = metadata.get("region", "cn-beijing")
        try:
            ids = metadata.get("instance_ids")
            if ids is None:
                resources = await asyncio.to_thread(
                    service.resources, environment, region
                )
                ids = [r["id"] for r in resources]
            task = await asyncio.to_thread(
                service.create_task, environment, region, ids, language=language.get()
            )
            text = (
                f"Analysis report created: {task['id']}. Source: {tr(task['source'])}. Open Analysis history to review the rule results and evidence."
                if language.get() == "en"
                else f"已创建 {task['source']} 分析报告：{task['id']}。请在分析记录中查看规则结论和证据。"
            )
        except CloudError as exc:
            text = tr(str(exc))
        return {"messages": [AIMessage(content=text)], "next_agent": ""}
