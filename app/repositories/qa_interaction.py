"""问答交互记录仓储层。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.qa_interaction import QAInteraction


async def get_interaction(session: AsyncSession, interaction_id: str) -> QAInteraction | None:
    result = await session.execute(select(QAInteraction).where(QAInteraction.id == interaction_id))
    return result.scalar_one_or_none()


async def list_interactions(
    session: AsyncSession, limit: int = 100, offset: int = 0,
    base_id: str | None = None, status: str | None = None, keyword: str | None = None,
) -> list[QAInteraction]:
    stmt = select(QAInteraction).order_by(QAInteraction.created_at.desc()).limit(limit).offset(offset)
    if base_id:
        stmt = stmt.where(QAInteraction.base_id == base_id)
    if status:
        stmt = stmt.where(QAInteraction.status == status)
    if keyword:
        stmt = stmt.where(QAInteraction.question.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_interactions(
    session: AsyncSession, base_id: str | None = None,
    status: str | None = None, keyword: str | None = None,
) -> int:
    stmt = select(func.count(QAInteraction.id))
    if base_id:
        stmt = stmt.where(QAInteraction.base_id == base_id)
    if status:
        stmt = stmt.where(QAInteraction.status == status)
    if keyword:
        stmt = stmt.where(QAInteraction.question.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_interaction(session: AsyncSession, item: QAInteraction) -> QAInteraction:
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def update_interaction(session: AsyncSession, item: QAInteraction) -> QAInteraction:
    await session.commit()
    await session.refresh(item)
    return item
