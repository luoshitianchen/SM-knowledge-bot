"""知识文档服务层：文档接入与解析状态机。"""
from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import internal_write_allowed
from app.models.knowledge_document import KnowledgeDocument
from app.repositories import knowledge_base as base_repo
from app.repositories import knowledge_document as repo
from app.schemas.knowledge_document import KnowledgeDocumentCreate, KnowledgeDocumentUpdate
from app.services.audit import record_audit

# 文档解析状态机：允许的合法迁移
_DOC_TRANSITIONS: dict[str, set[str]] = {
    "parsing": {"ready", "failed"},
    "ready": {"parsing"},
    "failed": {"parsing"},
}


def _doc_to_dict(d: KnowledgeDocument) -> dict:
    return {
        "id": d.id, "base_id": d.base_id, "title": d.title,
        "content": d.content or "", "doc_type": d.doc_type, "status": d.status,
        "chunk_count": d.chunk_count,
        "created_at": d.created_at.isoformat() if d.created_at else "",
        "updated_at": d.updated_at.isoformat() if d.updated_at else "",
    }


class KnowledgeDocumentService:
    @staticmethod
    async def list_documents(
        session: AsyncSession, limit: int = 100, offset: int = 0,
        base_id: str | None = None, status_filter: str | None = None,
        keyword: str | None = None,
    ) -> dict:
        items = await repo.list_documents(
            session, limit=limit, offset=offset, base_id=base_id,
            status=status_filter, keyword=keyword,
        )
        total = await repo.count_documents(
            session, base_id=base_id, status=status_filter, keyword=keyword
        )
        return {"total": total, "items": [_doc_to_dict(d) for d in items]}

    @staticmethod
    async def get_document(session: AsyncSession, doc_id: str) -> dict:
        doc = await repo.get_document(session, doc_id)
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
        return _doc_to_dict(doc)

    @staticmethod
    async def create_document(
        session: AsyncSession, payload: KnowledgeDocumentCreate, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        base = await base_repo.get_base(session, payload.base_id)
        if not base:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "知识库不存在")
        if base.status != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "仅 active 知识库可写入文档")
        if await repo.get_document_by_title(session, payload.base_id, payload.title):
            raise HTTPException(status.HTTP_409_CONFLICT, "同知识库下文档标题已存在")
        doc = KnowledgeDocument(
            id=str(uuid.uuid4()), base_id=payload.base_id, title=payload.title,
            content=payload.content, doc_type=payload.doc_type,
            status="parsing", chunk_count=0,
        )
        doc = await repo.create_document(session, doc)
        await record_audit(session, "doc.created", "internal",
                           f"doc={payload.title}", request)
        return _doc_to_dict(doc)

    @staticmethod
    async def update_document(
        session: AsyncSession, doc_id: str, payload: KnowledgeDocumentUpdate, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        doc = await repo.get_document(session, doc_id)
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
        if doc.status == "parsing":
            raise HTTPException(status.HTTP_409_CONFLICT, "文档解析中，暂不可编辑")
        if payload.title is not None:
            doc.title = payload.title
        if payload.content is not None:
            doc.content = payload.content
        if payload.chunk_count is not None:
            doc.chunk_count = payload.chunk_count
        doc = await repo.update_document(session, doc)
        await record_audit(session, "doc.updated", "internal",
                           f"doc_id={doc_id}", request)
        return _doc_to_dict(doc)

    @staticmethod
    async def update_status(
        session: AsyncSession, doc_id: str, new_status: str, request: Request
    ) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        doc = await repo.get_document(session, doc_id)
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
        allowed = _DOC_TRANSITIONS.get(doc.status, set())
        if new_status not in allowed:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"非法状态迁移：{doc.status} -> {new_status}",
            )
        doc.status = new_status
        # 解析成功后给一个默认分块数，失败则清零
        doc.chunk_count = doc.chunk_count if new_status == "parsing" else (
            doc.chunk_count or 1
        ) if new_status == "ready" else 0
        doc = await repo.update_document(session, doc)
        await record_audit(session, "doc.status_changed", "internal",
                           f"doc_id={doc_id} status={new_status}", request)
        return _doc_to_dict(doc)

    @staticmethod
    async def delete_document(session: AsyncSession, doc_id: str, request: Request) -> dict:
        if not internal_write_allowed(request):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "内部写入令牌无效")
        doc = await repo.get_document(session, doc_id)
        if not doc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
        title = doc.title
        await repo.delete_document(session, doc)
        await record_audit(session, "doc.deleted", "internal",
                           f"doc_id={doc_id} title={title}", request)
        return {"deleted": True, "id": doc_id}
