"""知识库服务层：知识库全生命周期管理。"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import internal_write_allowed
from app.models.knowledge_base import KnowledgeBase
from app.repositories import knowledge_base as repo
from app.repositories import knowledge_document as doc_repo
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services.audit import record_audit


def _base_to_dict(b: KnowledgeBase) -> dict:
    return {
        "id": b.id, "name": b.name, "description": b.description or "",
        "owner": b.owner or "", "visibility": b.visibility, "status": b.status,
        "created_at": b.created_at.isoformat() if b.created_at else "",
        "updated_at": b.updated_at.isoformat() if b.updated_at else "",
    }


class KnowledgeBaseService:
    @staticmethod
    async def list_bases(
        session: AsyncSession, limit: int = 100, offset: int = 0,
        status_filter: str | None = None, keyword: str | None = None,
    ) -> dict:
        items = await repo.list_bases(
            session, limit=limit, offset=offset, status=status_filter, keyword=keyword
        )
        total = await repo.count_bases(session, status=status_filter, keyword=keyword)
        return {"total": total, "items": [_base_to_dict(b) for b in items]}

    @staticmethod
    async def get_base(session: AsyncSession, base_id: str) -> dict:
        base = await repo.get_base(session, base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        return _base_to_dict(base)

    @staticmethod
    async def create_base(
        session: AsyncSession, payload: KnowledgeBaseCreate, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        if await repo.get_base_by_name(session, payload.name):
            raise HTTPException(status.HTTP_409_CONFLICT, "知识库名已存在")
        base = KnowledgeBase(
            id=str(uuid.uuid4()), name=payload.name, description=payload.description,
            owner=payload.owner, visibility=payload.visibility, status="active",
        )
        base = await repo.create_base(session, base)
        await record_audit(session, "kb.created", "internal",
                           f"kb={payload.name}", request)
        return _base_to_dict(base)

    @staticmethod
    async def update_base(
        session: AsyncSession, base_id: str, payload: KnowledgeBaseUpdate, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        base = await repo.get_base(session, base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        if base.status == "archived":
            raise HTTPException(status.HTTP_409_CONFLICT, "已归档知识库不可变更")
        if payload.description is not None:
            base.description = payload.description
        if payload.owner is not None:
            base.owner = payload.owner
        if payload.visibility is not None:
            base.visibility = payload.visibility
        base = await repo.update_base(session, base)
        await record_audit(session, "kb.updated", "internal",
                           f"kb_id={base_id}", request)
        return _base_to_dict(base)

    @staticmethod
    async def update_status(
        session: AsyncSession, base_id: str, new_status: str, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        base = await repo.get_base(session, base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        if new_status not in ("active", "archived"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法状态值")
        base.status = new_status
        base = await repo.update_base(session, base)
        await record_audit(session, "kb.status_changed", "internal",
                           f"kb_id={base_id} status={new_status}", request)
        return _base_to_dict(base)

    @staticmethod
    async def delete_base(session: AsyncSession, base_id: str, request: Request) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        base = await repo.get_base(session, base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        doc_count = await doc_repo.count_documents_by_base(session, base_id)
        if doc_count > 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "知识库内仍有文档，禁止删除")
        name = base.name
        await repo.delete_base(session, base)
        await record_audit(session, "kb.deleted", "internal",
                           f"kb_id={base_id} name={name}", request)
        return {"deleted": True, "id": base_id}
