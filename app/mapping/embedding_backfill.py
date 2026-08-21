"""Populate CurriculumNode.embedding for nodes that don't have one yet.

The ensemble mapper's shortlist step (app/mapping/retrieval.py) can only
see nodes whose embedding column is populated, so freshly-extracted nodes
are invisible to it until this runs. Kept separate from extraction rather
than inlined there because it's re-runnable: a node added by hand, or one
whose label a teacher corrected, needs re-embedding without re-extracting
the whole syllabus.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CurriculumNode

logger = logging.getLogger(__name__)

# ponytail: one batch, no chunking. A syllabus is tens-to-low-hundreds of
# nodes, well inside a single embedding call. Chunk this if a multi-subject
# curriculum ever makes it a problem.
BATCH_LIMIT = 512


def _embedding_text(node: CurriculumNode) -> str:
    """Label plus description — the description carries the wording a
    question is actually likely to echo, so dropping it measurably weakens
    the shortlist.
    """
    return f"{node.label}\n{node.description}" if node.description else node.label


async def backfill_node_embeddings(session: AsyncSession, embedding_router=None) -> int:
    """Embed every node missing an embedding. Returns how many were updated."""
    if embedding_router is None:
        from app.providers.embeddings import get_embedding_router

        embedding_router = get_embedding_router()

    nodes = list(
        (
            await session.execute(
                select(CurriculumNode)
                .where(CurriculumNode.embedding.is_(None))
                .limit(BATCH_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    if not nodes:
        return 0

    response = await embedding_router.call(
        lambda p: p.embed([_embedding_text(n) for n in nodes])
    )
    for node, vector in zip(nodes, response.vectors):
        node.embedding = vector

    await session.commit()
    logger.info("embedded %d curriculum nodes with %s", len(nodes), response.model)
    return len(nodes)
