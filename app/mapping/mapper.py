"""Question -> curriculum-objective ensemble mapper (04_PROVIDER_STRATEGY.md
§4): embedding similarity + lexical overlap + syllabus terminology match +
LLM classification, combined into a multi-label weighted mapping — never a
single-label classification (03_DATA_MODELS.md §3).

Candidate objectives are supplied by the caller rather than looked up here.
Narrowing "all curriculum nodes" down to a shortlist worth scoring is a
retrieval concern (top-k by embedding search over `curriculum_nodes`, once
that index exists) that belongs to whoever calls this service, not to the
ensemble itself.
"""

import json
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CurriculumNode, ExamQuestion, MappingMethod, QuestionNodeMapping
from app.mapping.signals import SignalScores, combine, cosine_similarity, lexical_overlap, terminology_match
from app.providers.base import LLMMessage, ProviderError

logger = logging.getLogger(__name__)


@dataclass
class MappingCandidate:
    node: CurriculumNode
    scores: SignalScores
    weight: float
    confidence: float


def _node_text(node: CurriculumNode) -> str:
    return f"{node.label} {node.description or ''}"


async def _embedding_scores(
    embedding_router, question_text: str, candidates: list[CurriculumNode]
) -> dict[UUID, float] | None:
    """One batched embed call for the question + every candidate. Returns
    None (not an all-zero dict) on provider failure so the caller can tell
    "signal unavailable" apart from "signal ran and found nothing similar".
    """
    if embedding_router is None or not candidates:
        return None
    texts = [question_text] + [_node_text(c) for c in candidates]
    try:
        response = await embedding_router.call(lambda p: p.embed(texts))
    except ProviderError as exc:
        logger.warning("mapping: embedding signal unavailable: %s", exc)
        return None
    question_vec, *node_vecs = response.vectors
    return {c.id: cosine_similarity(question_vec, v) for c, v in zip(candidates, node_vecs)}


_LLM_PROMPT = """You are scoring how well an exam question matches each candidate \
curriculum objective, for a question -> objective mapping tool. For every \
candidate, output a relevance score from 0.0 (unrelated) to 1.0 (directly assessed). \
A question may relate to more than one objective.

Question:
{question_text}

Candidates:
{candidates_block}

Respond with ONLY a JSON object mapping each candidate's id to its score, e.g.:
{{"<id>": 0.8, "<id>": 0.1}}
"""


async def _llm_scores(
    llm_chain, question_text: str, candidates: list[CurriculumNode]
) -> dict[UUID, float] | None:
    if llm_chain is None or not candidates:
        return None
    candidates_block = "\n".join(f"- {c.id}: {_node_text(c)}" for c in candidates)
    prompt = _LLM_PROMPT.format(question_text=question_text, candidates_block=candidates_block)
    try:
        response = await llm_chain.call(
            lambda p: p.complete([LLMMessage(role="user", content=prompt)], max_tokens=1024)
        )
        raw = json.loads(response.text.strip())
        return {UUID(k): max(0.0, min(1.0, float(v))) for k, v in raw.items()}
    except (ProviderError, ValueError, KeyError, json.JSONDecodeError) as exc:
        logger.warning("mapping: LLM classification signal unavailable: %s", exc)
        return None


class EnsembleMapper:
    """Scores and persists question -> objective mappings. Embedding router
    and LLM chain are both optional so callers (and tests) can exercise the
    lexical/terminology-only path without live providers — mirrors §4's
    "don't block the pipeline entirely on LLM availability."
    """

    def __init__(self, session: AsyncSession, *, embedding_router=None, llm_chain=None):
        self._session = session
        self._embedding_router = embedding_router
        self._llm_chain = llm_chain

    async def score_candidates(
        self,
        question: ExamQuestion,
        candidates: list[CurriculumNode],
        *,
        acceptable_terms: list[str] | None = None,
    ) -> list[MappingCandidate]:
        if not candidates:
            return []

        embedding_scores = await _embedding_scores(
            self._embedding_router, question.text, candidates
        )
        llm_scores = await _llm_scores(self._llm_chain, question.text, candidates)

        results = []
        for node in candidates:
            scores = SignalScores(
                embedding=None if embedding_scores is None else embedding_scores[node.id],
                lexical=lexical_overlap(question.text, _node_text(node)),
                terminology=terminology_match(acceptable_terms or [], _node_text(node)),
                llm=None if llm_scores is None else llm_scores.get(node.id, 0.0),
            )
            weight, confidence = combine(scores)
            results.append(
                MappingCandidate(node=node, scores=scores, weight=weight, confidence=confidence)
            )
        return results

    async def map_question(
        self,
        question: ExamQuestion,
        candidates: list[CurriculumNode],
        *,
        acceptable_terms: list[str] | None = None,
        min_confidence: float = 0.2,
    ) -> list[QuestionNodeMapping]:
        """Score candidates and persist a QuestionNodeMapping row for each
        one clearing `min_confidence`. Multi-label: a question can and
        routinely will produce several rows, with independent weights that
        are not required to sum to 1.0 (03_DATA_MODELS.md §3).
        """
        scored = await self.score_candidates(
            question, candidates, acceptable_terms=acceptable_terms
        )
        mappings = []
        for candidate in scored:
            if candidate.confidence < min_confidence:
                continue
            mapping = QuestionNodeMapping(
                question_id=question.id,
                node_id=candidate.node.id,
                weight=candidate.weight,
                confidence=candidate.confidence,
                mapping_method=MappingMethod.HYBRID,
            )
            self._session.add(mapping)
            mappings.append(mapping)
        await self._session.commit()
        return mappings
