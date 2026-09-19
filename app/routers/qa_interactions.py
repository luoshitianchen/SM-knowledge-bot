"""问答交互记录路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.qa_interaction import QAFeedbackUpdate, QAInteractionCreate
from app.services.qa_interaction import QAInteractionService

router = APIRouter(prefix="/api/kb/qa", tags=["qa-interactions"])


@router.get("")
async def list_interactions(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    base_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    keyword: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await QAInteractionService.list_interactions(
        session, limit=limit, offset=offset, base_id=base_id,
        status_filter=status_filter, keyword=keyword,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def record_interaction(
    payload: QAInteractionCreate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await QAInteractionService.record_interaction(session, payload, request)


@router.get("/{interaction_id}")
async def get_interaction(
    interaction_id: str, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await QAInteractionService.get_interaction(session, interaction_id)


@router.post("/{interaction_id}/feedback")
async def submit_feedback(
    interaction_id: str, payload: QAFeedbackUpdate, request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await QAInteractionService.submit_feedback(
        session, interaction_id, payload.feedback, request
    )
