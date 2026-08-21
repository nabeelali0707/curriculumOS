"""Question -> objective ensemble mapping endpoint. Thin wrapper over
app/mapping/mapper.py — see that module for the actual scoring logic.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import CurriculumNode, ExamQuestion, MarkSchemeEntry
from app.mapping.mapper import EnsembleMapper
from app.mapping.retrieval import top_k_similar_nodes

router = APIRouter(prefix="/mappings", tags=["mapping"])

DEFAULT_SHORTLIST_K = 20


class MapQuestionRequest(BaseModel):
    # Explicit candidates take priority. Omit to auto-shortlist via
    # pgvector similarity search (app/mapping/retrieval.py) instead of
    # requiring the caller to already know which objectives are relevant
    # — that's the whole point of the ensemble.
    node_ids: list[UUID] | None = None
    min_confidence: float = 0.2


class MappingOut(BaseModel):
    node_id: UUID
    weight: float
    confidence: float
    mapping_method: str


async def _get_embedding_router():
    from app.providers.embeddings import get_embedding_router

    try:
        return get_embedding_router()
    except Exception:
        # Embedding provider not configured/reachable — the ensemble
        # degrades to lexical + terminology (+ LLM if that's up), per
        # 04_PROVIDER_STRATEGY.md §4. Not a request failure.
        return None


async def _get_llm_chain():
    from app.providers.llm import get_generation_chain

    try:
        return get_generation_chain()
    except ValueError:
        return None


@router.post("/questions/{question_id}", response_model=list[MappingOut])
async def map_question(
    question_id: UUID,
    body: MapQuestionRequest,
    session: AsyncSession = Depends(get_session),
) -> list[MappingOut]:
    question = await session.get(ExamQuestion, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="question not found")

    embedding_router = await _get_embedding_router()

    if body.node_ids is not None:
        candidates = list(
            (
                await session.execute(
                    select(CurriculumNode).where(CurriculumNode.id.in_(body.node_ids))
                )
            )
            .scalars()
            .all()
        )
    elif embedding_router is not None:
        query_vector = (await embedding_router.call(lambda p: p.embed([question.text]))).vectors[0]
        candidates = await top_k_similar_nodes(session, query_vector, k=DEFAULT_SHORTLIST_K)
    else:
        # No explicit candidates and no embedding provider to shortlist
        # with — nothing sensible to score against.
        raise HTTPException(
            status_code=400,
            detail="node_ids required: no embedding provider available to auto-shortlist candidates",
        )

    acceptable_terms: list[str] = []
    for entry in (
        (await session.execute(select(MarkSchemeEntry).where(MarkSchemeEntry.question_id == question_id)))
        .scalars()
        .all()
    ):
        acceptable_terms.extend(entry.acceptable_terms or [])

    mapper = EnsembleMapper(
        session, embedding_router=embedding_router, llm_chain=await _get_llm_chain()
    )
    mappings = await mapper.map_question(
        question, candidates, acceptable_terms=acceptable_terms, min_confidence=body.min_confidence
    )
    return [
        MappingOut(
            node_id=m.node_id,
            weight=m.weight,
            confidence=m.confidence,
            mapping_method=m.mapping_method.value,
        )
        for m in mappings
    ]
