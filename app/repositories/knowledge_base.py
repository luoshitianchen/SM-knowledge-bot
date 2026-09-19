"""知识库仓储层。"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_base import KnowledgeBase


async def get_base(session: AsyncSession, base_id: str) -> KnowledgeBase | None:
    result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.id == base_id))
    return result.scalar_one_or_none()


async def get_base_by_name(session: AsyncSession, name: str) -> KnowledgeBase | None:
    result = await session.execute(select(KnowledgeBase).where(KnowledgeBase.name == name))
    return result.scalar_one_or_none()


async def list_bases(
    session: AsyncSession, limit: int = 100, offset: int = 0,
    status: str | None = None, keyword: str | None = None,
) -> list[KnowledgeBase]:
    stmt = select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()).limit(limit).offset(offset)
    if status:
        stmt = stmt.where(KnowledgeBase.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(KnowledgeBase.name.like(pattern), KnowledgeBase.description.like(pattern))
        )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_bases(
    session: AsyncSession, status: str | None = None, keyword: str | None = None,
) -> int:
    stmt = select(func.count(KnowledgeBase.id))
    if status:
        stmt = stmt.where(KnowledgeBase.status == status)
    if keyword:
        pattern = f"%{keyword}%"
        stmt = stmt.where(
            or_(KnowledgeBase.name.like(pattern), KnowledgeBase.description.like(pattern))
        )
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_base(session: AsyncSession, base: KnowledgeBase) -> KnowledgeBase:
    session.add(base)
    await session.commit()
    await session.refresh(base)
    return base


async def update_base(session: AsyncSession, base: KnowledgeBase) -> KnowledgeBase:
    await session.commit()
    await session.refresh(base)
    return base


async def delete_base(session: AsyncSession, base: KnowledgeBase) -> None:
    await session.delete(base)
    await session.commit()
