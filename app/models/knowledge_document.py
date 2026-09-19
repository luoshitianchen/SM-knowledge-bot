"""知识文档模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class KnowledgeDocument(Base):
    """知识文档：知识库内的单篇文档，含正文与向量化分块状态。"""

    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint("base_id", "title", name="uq_doc_base_title"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    doc_type: Mapped[str] = mapped_column(String(16), default="markdown")
    status: Mapped[str] = mapped_column(String(16), default="parsing", index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
