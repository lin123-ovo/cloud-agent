"""Source labels are taken from actual tool payloads, not generated citations."""

import re
from core.language import tr


def grounded_sources(answer: str, messages) -> str:
    sources = set()
    for message in messages:
        if getattr(message, "type", "") != "tool":
            continue
        content = message.content
        if not isinstance(content, str):
            continue
        sources.update(re.findall(r"【来源: ([^；】\n]+)", content))
    body = re.split(
        r"(?:答案来源|Answer sources?|Answer Sources?|Sources?)\s*[:：]",
        answer,
        maxsplit=1,
    )[0].rstrip()
    if not sources:
        return tr(
            "本次未取得能够支持回答的知识库证据，请补充具体产品型号或问题；目前无法确认相关参数或政策。"
        )
    return (
        tr("以下依据项目演示知识库回答。")
        + "\n\n"
        + body
        + "\n\n"
        + tr("答案来源：")
        + "\n"
        + "\n".join("- " + tr(source) for source in sorted(sources))
    )
