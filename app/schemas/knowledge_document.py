"""知识文档 Pydantic 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeDocumentCreate(BaseModel):
    base_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=256)
    content: str = Field(default="")
    doc_type: Literal["markdown", "pdf", "txt", "html"] = "markdown"


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    content: str | None = None
    chunk_count: int | None = Field(default=None, ge=0)


class KnowledgeDocumentStatusUpdate(BaseModel):
    status: Literal["parsing", "ready", "failed"]


class KnowledgeDocumentResponse(BaseModel):
    id: str
    base_id: str
    title: str
    content: str
    doc_type: str
    status: str
    chunk_count: int
    created_at: datetime | str
    updated_at: datetime | str


class KnowledgeDocumentListResponse(BaseModel):
    total: int
    items: list[KnowledgeDocumentResponse]
