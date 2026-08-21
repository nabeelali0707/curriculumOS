"""Pure logic tests — no DB, no provider SDK. Covers app/generation/claims.py
(JSON parsing of the two LLM chains' responses) and the pure ranking helpers
in app/generation/retrieval.py (lexical_overlap/rank_spans take plain
objects, no session).
"""

import uuid

import pytest

from app.generation.claims import (
    ClaimParseError,
    Verdict,
    parse_generated_claims,
    parse_verification_result,
)
from app.generation.retrieval import ScoredSpan, lexical_overlap, rank_spans
from app.domain.models import SourceSpan


def test_parse_generated_claims_happy_path():
    raw = '{"claims": [{"text": "Mitosis produces two daughter cells.", "evidence": ["abc", "def"]}]}'
    claims = parse_generated_claims(raw)
    assert len(claims) == 1
    assert claims[0].text == "Mitosis produces two daughter cells."
    assert claims[0].evidence_span_ids == ["abc", "def"]


def test_parse_generated_claims_accepts_bare_list():
    raw = '[{"text": "Enzymes are proteins.", "evidence": []}]'
    claims = parse_generated_claims(raw)
    assert claims[0].evidence_span_ids == []


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "{}",  # no 'claims' key
        '{"claims": "not a list"}',
        '{"claims": [{"no_text": "here"}]}',
        '{"claims": [{"text": "ok", "evidence": "not a list"}]}',
    ],
)
def test_parse_generated_claims_rejects_malformed_input(raw):
    with pytest.raises(ClaimParseError):
        parse_generated_claims(raw)


def test_parse_verification_result_happy_path():
    raw = '{"verdict": "partial", "confidence": 0.6, "reasoning": "only half matches"}'
    result = parse_verification_result(raw)
    assert result.verdict == Verdict.PARTIAL
    assert result.confidence == 0.6
    assert result.reasoning == "only half matches"


def test_parse_verification_result_clamps_confidence():
    raw = '{"verdict": "yes", "confidence": 5.0}'
    result = parse_verification_result(raw)
    assert result.confidence == 1.0


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"no_verdict": "yes"}',
        '{"verdict": "maybe"}',
        '{"verdict": "yes", "confidence": "high"}',
    ],
)
def test_parse_verification_result_rejects_malformed_input(raw):
    with pytest.raises(ClaimParseError):
        parse_verification_result(raw)


def test_lexical_overlap_ranks_more_similar_text_higher():
    query = "mitosis daughter cells division"
    high = lexical_overlap(query, "Mitosis produces two daughter cells.")
    low = lexical_overlap(query, "Photosynthesis occurs in chloroplasts.")
    assert high > low
    assert 0.0 <= high <= 1.0


def test_lexical_overlap_empty_inputs_score_zero():
    assert lexical_overlap("", "anything") == 0.0
    assert lexical_overlap("anything", "") == 0.0


def _span(text: str) -> SourceSpan:
    return SourceSpan(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        page=1,
        block_id="blk-0",
        bbox=[0, 0, 1, 1],
        text=text,
        content_hash="sha256:x",
    )


def test_rank_spans_orders_by_score_and_drops_zero_matches():
    on_topic = _span("Mitosis produces two genetically identical daughter cells.")
    off_topic = _span("The stock market closed higher today.")

    ranked = rank_spans("mitosis daughter cells identical", [off_topic, on_topic], k=5)

    assert [r.span for r in ranked] == [on_topic]
    assert isinstance(ranked[0], ScoredSpan)


def test_rank_spans_respects_k():
    spans = [_span(f"mitosis cell division example {i}") for i in range(10)]
    ranked = rank_spans("mitosis cell division", spans, k=3)
    assert len(ranked) == 3
