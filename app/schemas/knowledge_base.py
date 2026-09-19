"""知识库 Pydantic 模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    description: str = Field(default="", max_length=2048)
    owner: str = Field(default="", max_length=128)
    visibility: Literal["private", "internal", "public"] = "internal"


class KnowledgeBaseUpdate(BaseModel):
    description: str | None = Field(default=None, max_length=2048)
    owner: str | None = Field(default=None, max_length=128)
    visibility: Literal["private", "internal", "public"] | None = None


class KnowledgeBaseStatusUpdate(BaseModel):
    status: Literal["active", "archived"]


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str
    owner: str
    visibility: str
    status: str
    created_at: datetime | str
    updated_at: datetime | str


class KnowledgeBaseListResponse(BaseModel):
    total: int
    items: list[KnowledgeBaseResponse]
