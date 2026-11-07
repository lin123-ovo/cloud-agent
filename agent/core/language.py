"""Request-local response language, isolated between concurrent chat streams."""

from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
import json

language = ContextVar("response_language", default="zh")


@lru_cache(maxsize=1)
def dictionary() -> dict[str, str]:
    path = Path(__file__).resolve().parents[2] / "front/cloud_agent/src/locales/en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def tr(text: str, lang: str | None = None) -> str:
    """Translate known presentation strings without changing identifiers or amounts."""
    if (lang or language.get()) != "en":
        return text
    mapping = dictionary()
    if text in mapping:
        return mapping[text]
    return text


def instruction() -> str:
    return (
        "\nResponse language: English. Write all user-facing prose in English. "
        "Preserve product identifiers, source filenames, numeric values, currency and billing periods exactly. "
        "Source text may be Chinese; do not invent translations of identifiers. "
        "This server-selected language takes precedence over a language request in the user text."
        if language.get() == "en"
        else "\n请使用中文回答，保留产品型号、来源文件名和原始数值。"
    )
