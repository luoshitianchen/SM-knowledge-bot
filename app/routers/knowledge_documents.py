"""知识文档管理路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.knowledge_document import (
    KnowledgeDocumentCreate,
    KnowledgeDocumentStatusUpdate,
    KnowledgeDocumentUpdate,
)
from app.services.knowledge_document import KnowledgeDocumentService

router = APIRouter(prefix="/api/kb/documents", tags=["knowledge-documents"])


@router.get("")
async def list_documents(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    base_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.list_documents(
        session, limit=limit, offset=offset, base_id=base_id,
        status_filter=status_filter, keyword=keyword,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_document(
    payload: KnowledgeDocumentCreate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.create_document(session, payload, request)


@router.get("/{doc_id}")
async def get_document(
    doc_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.get_document(session, doc_id)


@router.patch("/{doc_id}")
async def update_document(
    doc_id: str, payload: KnowledgeDocumentUpdate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.update_document(session, doc_id, payload, request)


@router.patch("/{doc_id}/status")
async def update_document_status(
    doc_id: str, payload: KnowledgeDocumentStatusUpdate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.update_status(session, doc_id, payload.status, request)


@router.delete("/{doc_id}", status_code=status.HTTP_200_OK)
async def delete_document(
    doc_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeDocumentService.delete_document(session, doc_id, request)
