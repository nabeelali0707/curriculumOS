"""Evidence retrieval for grounded generation (02_ARCHITECTURE.md §4,
"retrieve evidence" — the first stage of verify-then-render).

Given a curriculum node, shortlist the SourceSpan rows most likely to
support claims about it.

# ponytail: lexical (token-overlap) scoring only. SourceSpan has no
# embedding column — adding one is a schema change (new migration) outside
# this pass's scope. Upgrade path: add an embedding column + pgvector index
# on source_spans, mirror app/mapping/retrieval.py's top_k_similar_nodes
# shape, and blend it with this lexical score (hybrid retrieval per
# 02_ARCHITECTURE.md §4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CurriculumEdge, CurriculumNode, SourceSpan

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(text.lower()))


def lexical_overlap(query: str, candidate: str) -> float:
    """Jaccard overlap between query and candidate token sets. Simple,
    dependency-free, good enough as a first-pass evidence filter — see
    module ponytail note for the upgrade path.
    """
    q = _tokenize(query)
    c = _tokenize(candidate)
    if not q or not c:
        return 0.0
    return len(q & c) / len(q | c)


@dataclass
class ScoredSpan:
    span: SourceSpan
    score: float


def rank_spans(query: str, spans: list[SourceSpan], k: int) -> list[ScoredSpan]:
    """Pure ranking step — no DB/session here, so it's directly testable
    without a live database.
    """
    scored = [ScoredSpan(span=s, score=lexical_overlap(query, s.text)) for s in spans]
    scored = [s for s in scored if s.score > 0.0]
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:k]


async def _candidate_spans(session: AsyncSession, node: CurriculumNode) -> list[SourceSpan]:
    """Spans reachable from `node`.

    Highest-precision source: edges touching this node that carry
    provenance (CurriculumEdge.provenance_id -> source_spans — see that
    column's docstring in app/domain/models.py). If that yields nothing
    (most edges are provenance-free today; only machine_* edges are
    required to set it), fall back to scanning every span in the store and
    let lexical scoring in rank_spans() do the filtering. Acceptable at
    pilot scale; not something to optimize before there's a real span
    volume to measure against.
    """
    edge_rows = await session.execute(
        select(CurriculumEdge.provenance_id).where(
            (CurriculumEdge.source_node_id == node.id) | (CurriculumEdge.target_node_id == node.id),
            CurriculumEdge.provenance_id.is_not(None),
        )
    )
    span_ids = [row[0] for row in edge_rows.all()]
    if span_ids:
        result = await session.execute(select(SourceSpan).where(SourceSpan.id.in_(span_ids)))
        spans = list(result.scalars().all())
        if spans:
            return spans

    result = await session.execute(select(SourceSpan))
    return list(result.scalars().all())


async def retrieve_evidence(
    session: AsyncSession, node: CurriculumNode, *, k: int = 5
) -> list[SourceSpan]:
    """Evidence shortlist for `node`, ranked by lexical overlap with its
    label/description/syllabus_ref.
    """
    query = " ".join(filter(None, [node.label, node.description, node.syllabus_ref]))
    candidates = await _candidate_spans(session, node)
    return [scored.span for scored in rank_spans(query, candidates, k)]
