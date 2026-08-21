"""Pure data shapes for the generate -> verify pipeline
(02_ARCHITECTURE.md §4), plus basic parsing of the two LLM chains' JSON
responses. No DB session, no provider SDK import here — importable and
testable standalone, same split as app/ingestion/question_parser.py vs
app/ingestion/question_service.py.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from app.llm_json import loads_llm_json


class Verdict(str, Enum):
    """The verification chain's raw answer. Kept separate from the domain
    VerificationStatus enum (app/domain/models.py) so this module stays
    free of SQLAlchemy imports — service.py maps Verdict -> VerificationStatus.
    """

    YES = "yes"
    NO = "no"
    PARTIAL = "partial"


@dataclass
class GeneratedClaim:
    """One claim out of the generation chain's response, before verification."""

    text: str
    evidence_span_ids: list[str] = field(default_factory=list)


@dataclass
class VerificationResult:
    verdict: Verdict
    confidence: float
    reasoning: str = ""


class ClaimParseError(ValueError):
    """Raised when an LLM chain's response isn't the expected JSON shape.
    Callers treat this the same as a provider outage: don't fabricate a
    result, mark the claim NOT_CHECKED (or drop the whole batch pre-persist
    for a generation-side failure) rather than guessing.
    """


def parse_generated_claims(raw_text: str) -> list[GeneratedClaim]:
    """Parse the generation chain's response into GeneratedClaim objects.

    Expected shape: {"claims": [{"text": "...", "evidence": ["<span-id>", ...]}, ...]}
    A bare top-level list is also accepted.

    # ponytail: basic structural checks, no JSON-schema validation library
    # (not a dependency here). Anything malformed raises ClaimParseError and
    # the caller drops the batch rather than half-trusting a partial parse.
    """
    try:
        data = loads_llm_json(raw_text)
    except json.JSONDecodeError as exc:
        raise ClaimParseError(f"generation response was not valid JSON: {exc}") from exc

    claims_raw = data.get("claims") if isinstance(data, dict) else data
    if not isinstance(claims_raw, list):
        raise ClaimParseError("expected a top-level 'claims' list")

    claims: list[GeneratedClaim] = []
    for item in claims_raw:
        if not isinstance(item, dict) or "text" not in item:
            raise ClaimParseError(f"malformed claim entry: {item!r}")
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            raise ClaimParseError(f"claim evidence must be a list: {item!r}")
        claims.append(
            GeneratedClaim(text=str(item["text"]), evidence_span_ids=[str(e) for e in evidence])
        )
    return claims


def parse_verification_result(raw_text: str) -> VerificationResult:
    """Parse the verification chain's response.

    Expected shape: {"verdict": "yes"|"partial"|"no", "confidence": 0.0-1.0, "reasoning": "..."}
    """
    try:
        data = loads_llm_json(raw_text)
    except json.JSONDecodeError as exc:
        raise ClaimParseError(f"verification response was not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "verdict" not in data:
        raise ClaimParseError(f"expected an object with a 'verdict' field, got {data!r}")

    try:
        verdict = Verdict(str(data["verdict"]).lower())
    except ValueError as exc:
        raise ClaimParseError(f"unknown verdict {data.get('verdict')!r}") from exc

    confidence = data.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ClaimParseError(f"confidence must be numeric, got {confidence!r}")
    confidence = max(0.0, min(1.0, float(confidence)))

    return VerificationResult(
        verdict=verdict, confidence=confidence, reasoning=str(data.get("reasoning", ""))
    )
