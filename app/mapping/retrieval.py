"""Retrieve curriculum nodes by embedding similarity when the caller has a query vector."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CurriculumNode


async def top_k_similar_nodes(
    session: AsyncSession, query_vector: list[float], k: int = 10
) -> list[CurriculumNode]:
    """Return the closest embedded nodes while ignoring rows that have not been vectorized yet.

    `session` is an AsyncSession (every other DB-touching module in this repo
    uses one — app/mapping/mapper.py, app/emphasis/service.py,
    app/planning/service.py) so this must be awaited, not called sync.
    """
    if k <= 0:
        return []
    result = await session.execute(
        select(CurriculumNode)
        .where(CurriculumNode.embedding.is_not(None))
        .order_by(CurriculumNode.embedding.cosine_distance(query_vector).asc())
        .limit(k)
    )
    return list(result.scalars().all())
