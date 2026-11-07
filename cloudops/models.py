"""Validated provider-neutral resource and metric types."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class Resource(BaseModel):
    id: str
    name: str
    environment: Literal["demo", "aliyun"]
    region: str
    instance_type: str
    family: str
    cpu: int = Field(gt=0)
    memory_gb: float = Field(gt=0)
    status: str
    billing: str = "PostPaid"
    spot: bool = False
    os: str = "linux"
    updated_at: datetime


class Sample(BaseModel):
    model_config = {"allow_inf_nan": False}
    timestamp: datetime
    cpu: float | None = Field(default=None, ge=0, le=100)
    memory: float | None = Field(default=None, ge=0, le=100)

    cpu_max: float | None = Field(default=None, ge=0, le=100)
    memory_max: float | None = Field(default=None, ge=0, le=100)


class Quote(BaseModel):
    model_config = {"allow_inf_nan": False}
    amount: float = Field(ge=0)
    currency: str
    unit: str = "Hour"
    region: str
    os: str
    source: str
