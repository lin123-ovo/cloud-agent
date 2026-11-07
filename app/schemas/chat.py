from pydantic import BaseModel, Field
from typing import Literal


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=8000, pattern=r"\S")
    user_id: str = Field(
        default="user_1001", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    session_id: str = Field(
        default="default_session",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    environment: Literal["demo", "aliyun"] = "demo"
    language: Literal["zh", "en"] = "zh"
    region: str = Field(default="cn-beijing", max_length=40)
    instance_ids: list[str] | None = Field(default=None, max_length=20)


class ChatResponse(BaseModel):
    status: str
    reply: str
    user_id: str
    session_id: str
