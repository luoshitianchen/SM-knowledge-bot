"""知识文档仓储层。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge_document import KnowledgeDocument


async def get_document(session: AsyncSession, doc_id: str) -> KnowledgeDocument | None:
    result = await session.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
    return result.scalar_one_or_none()


async def get_document_by_title(
    session: AsyncSession, base_id: str, title: str
) -> KnowledgeDocument | None:
    stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.base_id == base_id, KnowledgeDocument.title == title
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_documents(
    session: AsyncSession, limit: int = 100, offset: int = 0,
    base_id: str | None = None, status: str | None = None, keyword: str | None = None,
) -> list[KnowledgeDocument]:
    stmt = select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc()).limit(limit).offset(offset)
    if base_id:
        stmt = stmt.where(KnowledgeDocument.base_id == base_id)
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    if keyword:
        stmt = stmt.where(KnowledgeDocument.title.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_documents(
    session: AsyncSession, base_id: str | None = None,
    status: str | None = None, keyword: str | None = None,
) -> int:
    stmt = select(func.count(KnowledgeDocument.id))
    if base_id:
        stmt = stmt.where(KnowledgeDocument.base_id == base_id)
    if status:
        stmt = stmt.where(KnowledgeDocument.status == status)
    if keyword:
        stmt = stmt.where(KnowledgeDocument.title.like(f"%{keyword}%"))
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def count_documents_by_base(session: AsyncSession, base_id: str) -> int:
    stmt = select(func.count(KnowledgeDocument.id)).where(KnowledgeDocument.base_id == base_id)
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def create_document(session: AsyncSession, doc: KnowledgeDocument) -> KnowledgeDocument:
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return doc


async def update_document(session: AsyncSession, doc: KnowledgeDocument) -> KnowledgeDocument:
    await session.commit()
    await session.refresh(doc)
    return doc


async def delete_document(session: AsyncSession, doc: KnowledgeDocument) -> None:
    await session.delete(doc)
    await session.commit()
