"""问答交互 Pydantic 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class QAInteractionCreate(BaseModel):
    base_id: str = Field(min_length=1, max_length=64)
    question: str = Field(min_length=1, max_length=2048)
    answer: str = Field(default="")
    source_doc_ids: list[str] = Field(default_factory=list)
    asker: str = Field(default="", max_length=128)
    latency_ms: int = Field(default=0, ge=0, le=600000)


class QAFeedbackUpdate(BaseModel):
    feedback: Literal["none", "up", "down"]


class QAInteractionResponse(BaseModel):
    id: str
    base_id: str
    question: str
    answer: str
    source_doc_ids: list[str]
    asker: str
    feedback: str
    latency_ms: int
    status: str
    created_at: datetime | str


class QAInteractionListResponse(BaseModel):
    total: int
    items: list[QAInteractionResponse]
