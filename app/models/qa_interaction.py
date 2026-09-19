"""问答交互记录模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class QAInteraction(Base):
    """问答交互记录：一次检索问答的问题、答案与反馈埋点。"""

    __tablename__ = "qa_interactions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, default="")
    source_doc_ids: Mapped[str] = mapped_column(Text, default="[]")
    asker: Mapped[str] = mapped_column(String(128), default="")
    feedback: Mapped[str] = mapped_column(String(16), default="none")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="answered", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
