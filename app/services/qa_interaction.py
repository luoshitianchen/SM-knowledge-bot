"""问答交互服务层：问答记录埋点与反馈。"""
from __future__ import annotations

import json
import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import internal_write_allowed
from app.models.qa_interaction import QAInteraction
from app.repositories import knowledge_base as base_repo
from app.repositories import qa_interaction as repo
from app.schemas.qa_interaction import QAInteractionCreate
from app.services.audit import record_audit


def _interaction_to_dict(i: QAInteraction) -> dict:
    return {
        "id": i.id, "base_id": i.base_id, "question": i.question,
        "answer": i.answer or "",
        "source_doc_ids": json.loads(i.source_doc_ids or "[]"),
        "asker": i.asker or "", "feedback": i.feedback,
        "latency_ms": i.latency_ms, "status": i.status,
        "created_at": i.created_at.isoformat() if i.created_at else "",
    }


class QAInteractionService:
    @staticmethod
    async def list_interactions(
        session: AsyncSession, limit: int = 100, offset: int = 0,
        base_id: str | None = None, status_filter: str | None = None,
        keyword: str | None = None,
    ) -> dict:
        items = await repo.list_interactions(
            session, limit=limit, offset=offset, base_id=base_id,
            status=status_filter, keyword=keyword,
        )
        total = await repo.count_interactions(
            session, base_id=base_id, status=status_filter, keyword=keyword
        )
        return {"total": total, "items": [_interaction_to_dict(i) for i in items]}

    @staticmethod
    async def get_interaction(session: AsyncSession, interaction_id: str) -> dict:
        item = await repo.get_interaction(session, interaction_id)
        if not item:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "问答记录不存在")
        return _interaction_to_dict(item)

    @staticmethod
    async def record_interaction(
        session: AsyncSession, payload: QAInteractionCreate, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        base = await base_repo.get_base(session, payload.base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        if base.status != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "仅 active 知识库可问答")
        item = QAInteraction(
            id=str(uuid.uuid4()), base_id=payload.base_id, question=payload.question,
            answer=payload.answer,
            source_doc_ids=json.dumps(payload.source_doc_ids, ensure_ascii=False),
            asker=payload.asker, latency_ms=payload.latency_ms,
            status="answered" if payload.answer else "failed",
        )
        item = await repo.create_interaction(session, item)
        await record_audit(session, "qa.recorded", "internal",
                           f"base_id={payload.base_id}", request)
        return _interaction_to_dict(item)

    @staticmethod
    async def submit_feedback(
        session: AsyncSession, interaction_id: str, feedback: str, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        item = await repo.get_interaction(session, interaction_id)
        if not item:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "问答记录不存在")
        if feedback not in ("none", "up", "down"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法反馈值")
        item.feedback = feedback
        item = await repo.update_interaction(session, item)
        await record_audit(session, "qa.feedback", "internal",
                           f"interaction_id={interaction_id} feedback={feedback}", request)
        return _interaction_to_dict(item)
