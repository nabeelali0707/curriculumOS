"""Verify-then-render pipeline (02_ARCHITECTURE.md §4):

    retrieve evidence -> generate structured claims -> claim<->evidence
    verification (separate chain/provider) -> reject unsupported claims
    -> render

Lesson generation and assessment generation (07_TASK_ROADMAP.md P2) share
this loop — they differ only in which prompt template drives the
generation step, so the retrieve/generate/verify/persist orchestration is
written once, in `_generate_and_verify`, and both services call it.

Trust rule, non-negotiable: a claim is never persisted as VERIFIED unless
the verification chain actually said so. A provider outage or a malformed
response becomes NOT_CHECKED (or the claim is dropped pre-persist, for a
generation-side failure with nothing yet to record) — never a silent
upgrade to VERIFIED, and an UNSUPPORTED claim is never dropped from the
record, only excluded from rendering by its status.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    Claim,
    ClaimEvidence,
    CurriculumNode,
    ScheduledUnit,
    SourceSpan,
    TeachingUnit,
    VerificationStatus,
)
from app.generation.claims import (
    ClaimParseError,
    GeneratedClaim,
    Verdict,
    VerificationResult,
    parse_generated_claims,
    parse_verification_result,
)
from app.generation.retrieval import retrieve_evidence
from app.providers.base import LLMMessage, ProviderError

logger = logging.getLogger(__name__)

_VERDICT_TO_STATUS = {
    Verdict.YES: VerificationStatus.VERIFIED,
    Verdict.PARTIAL: VerificationStatus.PARTIALLY_SUPPORTED,
    Verdict.NO: VerificationStatus.UNSUPPORTED,
}

GENERATION_PROMPT_LESSON = (
    "You are drafting factual lesson content for the topic below, using ONLY "
    "the evidence snippets provided. Do not use outside knowledge or invent "
    "facts not present in the evidence. Every claim must cite the evidence "
    "span id(s) (the bracketed ids below) that support it.\n\n"
    "Topic: {label}\n{description}\n\n"
    "Evidence:\n{evidence}\n\n"
    'Respond with JSON only: {{"claims": [{{"text": "...", "evidence": ["<span-id>", ...]}}]}}'
)

GENERATION_PROMPT_ASSESSMENT = (
    "Write {count} practice exam-style questions testing the objective below, "
    "using ONLY the evidence snippets provided as grounding for what's "
    "testable. Do not use outside knowledge. Each question must cite the "
    "evidence span id(s) (the bracketed ids below) it is grounded in.\n\n"
    "Objective: {label}\n{description}\n\n"
    "Evidence:\n{evidence}\n\n"
    'Respond with JSON only: {{"claims": [{{"text": "<question text>", "evidence": ["<span-id>", ...]}}]}}'
)

VERIFICATION_PROMPT = (
    "Claim: {claim}\n\nEvidence:\n{evidence}\n\n"
    "Is the claim fully, partially, or not supported by the evidence above? "
    "Judge only against the evidence text, not outside knowledge.\n"
    'Respond with JSON only: {{"verdict": "yes"|"partial"|"no", "confidence": 0.0-1.0, "reasoning": "..."}}'
)


def _evidence_block(spans: list[SourceSpan]) -> str:
    """Renders retrieved spans as a numbered, citable block for the prompt —
    the LLM is asked to reference spans by these ids, not to restate them,
    so evidence links stay resolvable against real SourceSpan rows.
    """
    return "\n".join(f"[{s.id}] (p.{s.page}) {s.text}" for s in spans)


async def _load_node_for_scheduled_unit(
    session: AsyncSession, scheduled_unit_id: UUID
) -> tuple[ScheduledUnit, CurriculumNode]:
    scheduled_unit = await session.get(ScheduledUnit, scheduled_unit_id)
    if scheduled_unit is None:
        raise ValueError(f"no scheduled_unit {scheduled_unit_id}")
    teaching_unit = await session.get(TeachingUnit, scheduled_unit.unit_id)
    if teaching_unit is None:
        raise ValueError(f"scheduled_unit {scheduled_unit_id} references a missing teaching_unit")
    node = await session.get(CurriculumNode, teaching_unit.node_id)
    if node is None:
        raise ValueError(f"teaching_unit {teaching_unit.id} references a missing curriculum_node")
    return scheduled_unit, node


def _resolve_chains(generation_chain, verification_chain):
    """Lazy default, same reasoning as IngestionService's parser router:
    importing app.providers.llm pulls in every provider SDK, which tests
    that inject their own chains shouldn't have to pay for.
    """
    if generation_chain is not None and verification_chain is not None:
        return generation_chain, verification_chain
    from app.providers.llm import get_generation_chain, get_verification_chain

    return (
        generation_chain or get_generation_chain(),
        verification_chain or get_verification_chain(),
    )


async def _verify_claim(
    claim: GeneratedClaim,
    evidence: list[SourceSpan],
    verification_chain,
    *,
    generation_provider: str,
) -> tuple[VerificationStatus, float, str]:
    """Runs the separate verification chain and maps its verdict onto the
    domain VerificationStatus. Never returns VERIFIED except on an actual
    "yes" verdict from a chain call that succeeded and parsed.
    """
    if not evidence:
        # Claim cited no span we could resolve — nothing to verify against,
        # unsupported by construction. Not worth a round trip.
        return VerificationStatus.UNSUPPORTED, 0.0, "none"

    prompt = VERIFICATION_PROMPT.format(claim=claim.text, evidence=_evidence_block(evidence))
    try:
        # Budgeted like generation, not smaller: the verdict JSON is tiny,
        # but a reasoning model thinks before emitting it and a tight cap
        # truncates it mid-thought into an empty completion.
        response = await verification_chain.call(
            lambda p: p.complete([LLMMessage(role="user", content=prompt)], max_tokens=2048),
            exclude={generation_provider},
        )
    except ProviderError as exc:
        logger.error("verification chain unavailable for claim %r: %s", claim.text[:60], exc)
        return VerificationStatus.NOT_CHECKED, 0.0, "unavailable"

    try:
        result: VerificationResult = parse_verification_result(response.text)
    except ClaimParseError as exc:
        logger.error("verification response failed to parse: %s", exc)
        return VerificationStatus.NOT_CHECKED, 0.0, response.model

    return _VERDICT_TO_STATUS[result.verdict], result.confidence, response.model


async def _generate_and_verify(
    session: AsyncSession,
    *,
    node: CurriculumNode,
    scheduled_unit_id: UUID | None,
    generation_chain,
    verification_chain,
    prompt_template: str,
    prompt_kwargs: dict,
    evidence_k: int,
) -> list[Claim]:
    """The shared retrieve -> generate -> verify -> persist loop."""
    evidence_spans = await retrieve_evidence(session, node, k=evidence_k)
    if not evidence_spans:
        logger.warning("generation: no evidence spans found for node %s, skipping", node.id)
        return []
    spans_by_id = {str(s.id): s for s in evidence_spans}

    prompt = prompt_template.format(
        label=node.label,
        description=node.description or "",
        evidence=_evidence_block(evidence_spans),
        **prompt_kwargs,
    )

    try:
        response = await generation_chain.call(
            lambda p: p.complete([LLMMessage(role="user", content=prompt)], max_tokens=2048)
        )
    except ProviderError as exc:
        # No draft to verify — nothing to persist. Contrast with a
        # verification-chain failure below, where the claim text already
        # exists and gets persisted as NOT_CHECKED instead of being hidden.
        logger.error("generation chain unavailable for node %s: %s", node.id, exc)
        return []

    try:
        generated = parse_generated_claims(response.text)
    except ClaimParseError as exc:
        logger.error("generation response for node %s failed to parse: %s", node.id, exc)
        return []

    persisted: list[Claim] = []
    for gc in generated:
        used_spans = [spans_by_id[eid] for eid in gc.evidence_span_ids if eid in spans_by_id]
        status, confidence, verification_model = await _verify_claim(
            gc, used_spans, verification_chain, generation_provider=response.provider
        )

        claim = Claim(
            scheduled_unit_id=scheduled_unit_id,
            text=gc.text,
            generation_model=response.model,
            verification_model=verification_model,
            verification_status=status,
            confidence=confidence,
        )
        session.add(claim)
        await session.flush()  # need claim.id for the ClaimEvidence rows below
        for span in used_spans:
            session.add(ClaimEvidence(claim_id=claim.id, source_span_id=span.id))
        persisted.append(claim)

    await session.commit()
    return persisted


class LessonGenerationService:
    def __init__(self, session: AsyncSession, generation_chain=None, verification_chain=None):
        self._session = session
        self._generation_chain = generation_chain
        self._verification_chain = verification_chain

    async def generate_lesson(self, scheduled_unit_id: UUID, *, evidence_k: int = 5) -> list[Claim]:
        scheduled_unit, node = await _load_node_for_scheduled_unit(self._session, scheduled_unit_id)
        generation_chain, verification_chain = _resolve_chains(
            self._generation_chain, self._verification_chain
        )
        return await _generate_and_verify(
            self._session,
            node=node,
            scheduled_unit_id=scheduled_unit.id,
            generation_chain=generation_chain,
            verification_chain=verification_chain,
            prompt_template=GENERATION_PROMPT_LESSON,
            prompt_kwargs={},
            evidence_k=evidence_k,
        )


class AssessmentGenerationService:
    """Practice-question generation. A generated question is stored as a
    plain Claim whose `text` is the question — not a new table — because
    the same verify-then-render trust rules apply unchanged
    (07_TASK_ROADMAP.md P2 explicitly calls for reusing the approach), and
    a dedicated table would need a migration outside this pass's scope.
    """

    def __init__(self, session: AsyncSession, generation_chain=None, verification_chain=None):
        self._session = session
        self._generation_chain = generation_chain
        self._verification_chain = verification_chain

    async def generate_questions(
        self, node_id: UUID, *, count: int = 3, evidence_k: int = 5
    ) -> list[Claim]:
        node = await self._session.get(CurriculumNode, node_id)
        if node is None:
            raise ValueError(f"no curriculum_node {node_id}")
        generation_chain, verification_chain = _resolve_chains(
            self._generation_chain, self._verification_chain
        )
        return await _generate_and_verify(
            self._session,
            node=node,
            scheduled_unit_id=None,
            generation_chain=generation_chain,
            verification_chain=verification_chain,
            prompt_template=GENERATION_PROMPT_ASSESSMENT,
            prompt_kwargs={"count": count},
            evidence_k=evidence_k,
        )
