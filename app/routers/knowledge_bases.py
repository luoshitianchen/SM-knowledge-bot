"""知识库管理路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseStatusUpdate,
    KnowledgeBaseUpdate,
)
from app.services.knowledge_base import KnowledgeBaseService

router = APIRouter(prefix="/api/kb/bases", tags=["knowledge-bases"])


@router.get("")
async def list_bases(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.list_bases(
        session, limit=limit, offset=offset,
        status_filter=status_filter, keyword=keyword,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_base(
    payload: KnowledgeBaseCreate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.create_base(session, payload, request)


@router.get("/{base_id}")
async def get_base(
    base_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.get_base(session, base_id)


@router.patch("/{base_id}")
async def update_base(
    base_id: str, payload: KnowledgeBaseUpdate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.update_base(session, base_id, payload, request)


@router.patch("/{base_id}/status")
async def update_base_status(
    base_id: str, payload: KnowledgeBaseStatusUpdate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.update_status(session, base_id, payload.status, request)


@router.delete("/{base_id}", status_code=status.HTTP_200_OK)
async def delete_base(
    base_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await KnowledgeBaseService.delete_base(session, base_id, request)
