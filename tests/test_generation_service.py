"""Service-level tests for app/generation/service.py using fake LLM chains
and a fake AsyncSession (same style as tests/test_ingestion.py's
FakeSession) — no real DB, no real provider SDK.

retrieve_evidence() itself (app/generation/retrieval.py) issues real
SQLAlchemy `select()` queries and needs a live async session with pgvector
tables to exercise properly — that part is monkeypatched out here rather
than faked, same gap tests/test_ingestion.py leaves for docling. It has its
own pure-function coverage (lexical_overlap/rank_spans) in
tests/test_generation_claims.py.
"""

import uuid

import pytest

from app.domain.models import (
    Claim,
    ClaimEvidence,
    CurriculumNode,
    NodeType,
    Origin,
    ScheduledUnit,
    ScheduledUnitStatus,
    SourceSpan,
    TeachingUnit,
    VerificationStatus,
)
from app.generation import service as service_module
from app.generation.service import (
    AssessmentGenerationService,
    LessonGenerationService,
    _verify_claim,
)
from app.generation.claims import GeneratedClaim
from app.providers.base import LLMResponse, ProviderError


class FakeSession:
    """Tracks add()/flush()/commit() the way the real AsyncSession does for
    the columns service.py touches; session.get() looks up canned rows by
    (model, id) instead of hitting a database.
    """

    def __init__(self, rows: dict[tuple[type, uuid.UUID], object] | None = None):
        self._rows = rows or {}
        self.added: list[object] = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, id_):
        return self._rows.get((model, id_))

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()

    async def commit(self):
        self.committed = True


class FakeChain:
    """Stands in for a FallbackChain: call() ignores the fn (nothing here
    calls a real provider) and either returns a canned LLMResponse or
    raises, mirroring what a real chain raises when every provider fails.
    """

    def __init__(self, response: LLMResponse | None = None, error: Exception | None = None):
        self._response = response
        self._error = error
        self.last_exclude = None

    async def call(self, fn, *, exclude=None):
        self.last_exclude = exclude
        if self._error is not None:
            raise self._error
        return self._response


def _span(text: str = "Mitosis produces two daughter cells.") -> SourceSpan:
    return SourceSpan(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page=47,
        block_id="blk-0",
        bbox=[0, 0, 1, 1],
        text=text,
        content_hash="sha256:x",
    )


def _node() -> CurriculumNode:
    return CurriculumNode(
        id=uuid.uuid4(),
        node_type=NodeType.OBJECTIVE,
        label="Mitosis",
        description="Cell division producing identical daughter cells.",
        origin=Origin.OFFICIAL,
        confidence=1.0,
    )


# ---- _verify_claim: no session or retrieval involved, pure chain logic ----


async def test_verify_claim_yes_verdict_maps_to_verified():
    span = _span()
    response = LLMResponse(
        text='{"verdict": "yes", "confidence": 0.9, "reasoning": "matches"}',
        model="claude-sonnet-5",
        provider="anthropic",
        input_tokens=10,
        output_tokens=10,
    )
    chain = FakeChain(response=response)
    claim = GeneratedClaim(text="Mitosis produces two daughter cells.", evidence_span_ids=[str(span.id)])

    status, confidence, model = await _verify_claim(
        claim, [span], chain, generation_provider="anthropic"
    )

    assert status == VerificationStatus.VERIFIED
    assert confidence == 0.9
    assert model == "claude-sonnet-5"
    # The generation provider must be excluded from the verification chain
    # — a model must not grade its own output.
    assert chain.last_exclude == {"anthropic"}


async def test_verify_claim_no_evidence_is_unsupported_without_calling_chain():
    chain = FakeChain(response=None)
    claim = GeneratedClaim(text="Unfounded claim.", evidence_span_ids=[])

    status, confidence, _ = await _verify_claim(claim, [], chain, generation_provider="anthropic")

    assert status == VerificationStatus.UNSUPPORTED
    assert confidence == 0.0
    assert chain.last_exclude is None  # never called


async def test_verify_claim_provider_error_is_not_checked_never_verified():
    span = _span()
    chain = FakeChain(error=ProviderError("all providers exhausted"))
    claim = GeneratedClaim(text="Some claim.", evidence_span_ids=[str(span.id)])

    status, confidence, _ = await _verify_claim(
        claim, [span], chain, generation_provider="anthropic"
    )

    # The core trust rule: an outage must never silently become VERIFIED.
    assert status == VerificationStatus.NOT_CHECKED
    assert confidence == 0.0


async def test_verify_claim_malformed_response_is_not_checked():
    span = _span()
    chain = FakeChain(
        response=LLMResponse(
            text="not json", model="claude-sonnet-5", provider="anthropic", input_tokens=1, output_tokens=1
        )
    )
    claim = GeneratedClaim(text="Some claim.", evidence_span_ids=[str(span.id)])

    status, _, _ = await _verify_claim(claim, [span], chain, generation_provider="anthropic")

    assert status == VerificationStatus.NOT_CHECKED


# ---- LessonGenerationService / AssessmentGenerationService: full loop ----


def _generation_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text, model="claude-sonnet-5", provider="anthropic", input_tokens=50, output_tokens=50
    )


def _verification_response(verdict: str) -> LLMResponse:
    return LLMResponse(
        text=f'{{"verdict": "{verdict}", "confidence": 0.8, "reasoning": "ok"}}',
        model="gpt-4o",
        provider="openai",
        input_tokens=20,
        output_tokens=20,
    )


async def test_generate_lesson_persists_verified_claim_with_evidence_link(monkeypatch):
    node = _node()
    span = _span()

    async def fake_retrieve_evidence(session, n, *, k):
        assert n is node
        return [span]

    monkeypatch.setattr(service_module, "retrieve_evidence", fake_retrieve_evidence)

    scheduled_unit = ScheduledUnit(
        id=uuid.uuid4(),
        unit_id=uuid.uuid4(),
        instruction_window_id=uuid.uuid4(),
        scheduled_minutes=45,
        status=ScheduledUnitStatus.PLANNED,
        plan_version=uuid.uuid4(),
    )
    teaching_unit = TeachingUnit(
        id=scheduled_unit.unit_id, node_id=node.id, duration_minutes=90, splittable=False, priority=0.5
    )

    session = FakeSession(
        {
            (ScheduledUnit, scheduled_unit.id): scheduled_unit,
            (TeachingUnit, teaching_unit.id): teaching_unit,
            (CurriculumNode, node.id): node,
        }
    )

    generation_chain = FakeChain(
        response=_generation_response(
            f'{{"claims": [{{"text": "Mitosis produces two daughter cells.", "evidence": ["{span.id}"]}}]}}'
        )
    )
    verification_chain = FakeChain(response=_verification_response("yes"))

    service = LessonGenerationService(session, generation_chain, verification_chain)
    claims = await service.generate_lesson(scheduled_unit.id)

    assert len(claims) == 1
    claim = claims[0]
    assert isinstance(claim, Claim)
    assert claim.verification_status == VerificationStatus.VERIFIED
    assert claim.scheduled_unit_id == scheduled_unit.id
    assert claim.generation_model == "claude-sonnet-5"
    assert claim.verification_model == "gpt-4o"
    assert session.committed

    links = [obj for obj in session.added if isinstance(obj, ClaimEvidence)]
    assert len(links) == 1
    assert links[0].claim_id == claim.id
    assert links[0].source_span_id == span.id


async def test_generate_lesson_unsupported_claim_is_persisted_not_dropped(monkeypatch):
    """An UNSUPPORTED verdict must still leave a Claim row — the trust
    record is never silently erased, only excluded from rendering by
    verification_status (that exclusion is a rendering-layer concern, out
    of scope here)."""
    node = _node()
    span = _span()

    async def fake_retrieve_evidence(session, n, *, k):
        return [span]

    monkeypatch.setattr(service_module, "retrieve_evidence", fake_retrieve_evidence)

    session = FakeSession(
        {
            (CurriculumNode, node.id): node,
        }
    )
    generation_chain = FakeChain(
        response=_generation_response(
            f'{{"claims": [{{"text": "A dubious claim.", "evidence": ["{span.id}"]}}]}}'
        )
    )
    verification_chain = FakeChain(response=_verification_response("no"))

    service = AssessmentGenerationService(session, generation_chain, verification_chain)
    claims = await service.generate_questions(node.id, count=1)

    assert len(claims) == 1
    assert claims[0].verification_status == VerificationStatus.UNSUPPORTED
    assert claims[0].scheduled_unit_id is None


async def test_generate_lesson_generation_provider_error_persists_nothing(monkeypatch):
    node = _node()
    span = _span()

    async def fake_retrieve_evidence(session, n, *, k):
        return [span]

    monkeypatch.setattr(service_module, "retrieve_evidence", fake_retrieve_evidence)

    session = FakeSession({(CurriculumNode, node.id): node})
    generation_chain = FakeChain(error=ProviderError("all providers exhausted"))
    verification_chain = FakeChain(response=_verification_response("yes"))

    service = AssessmentGenerationService(session, generation_chain, verification_chain)
    claims = await service.generate_questions(node.id)

    assert claims == []
    assert session.added == []
    assert not session.committed


async def test_generate_lesson_missing_node_raises():
    session = FakeSession({})
    service = LessonGenerationService(session, FakeChain(), FakeChain())
    with pytest.raises(ValueError):
        await service.generate_lesson(uuid.uuid4())


async def test_empty_completion_is_a_provider_error_not_an_empty_answer():
    """A reasoning model can spend its whole token budget thinking and
    return finish_reason="length" with no content. Passing "" up the stack
    makes a provider truncation look like an unparseable answer, and the
    claim silently lands as NOT_CHECKED. It must raise so the router can
    retry and the chain can fall through.
    """
    from unittest.mock import AsyncMock, patch

    from app.providers.base import LLMMessage, ProviderError
    from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider

    provider = OpenAICompatibleLLMProvider(
        name="fake", model="m", base_url="http://x", api_key=None, requires_api_key=False
    )

    class Msg:
        content = ""

    class Choice:
        message = Msg()
        finish_reason = "length"

    class Response:
        choices = [Choice()]
        usage = None
        model = "m"

    with patch.object(
        provider._client.chat.completions, "create", AsyncMock(return_value=Response())
    ):
        with pytest.raises(ProviderError, match="empty completion"):
            await provider.complete([LLMMessage(role="user", content="hi")])
