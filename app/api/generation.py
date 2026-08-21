"""Grounded lesson/assessment generation endpoints. Thin wrappers over
app/generation/service.py — see that module for the verify-then-render
pipeline itself.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import Claim
from app.generation.service import AssessmentGenerationService, LessonGenerationService

router = APIRouter(prefix="/generation", tags=["generation"])


class ClaimOut(BaseModel):
    id: UUID
    text: str
    verification_status: str
    confidence: float


def _to_out(claim: Claim) -> ClaimOut:
    return ClaimOut(
        id=claim.id,
        text=claim.text,
        verification_status=claim.verification_status.value,
        confidence=claim.confidence,
    )


@router.post("/lessons/{scheduled_unit_id}", response_model=list[ClaimOut])
async def generate_lesson(
    scheduled_unit_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ClaimOut]:
    try:
        claims = await LessonGenerationService(session).generate_lesson(scheduled_unit_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_to_out(c) for c in claims]


class GenerateQuestionsRequest(BaseModel):
    count: int = 3


@router.post("/assessments/{node_id}", response_model=list[ClaimOut])
async def generate_questions(
    node_id: UUID,
    body: GenerateQuestionsRequest = GenerateQuestionsRequest(),
    session: AsyncSession = Depends(get_session),
) -> list[ClaimOut]:
    try:
        claims = await AssessmentGenerationService(session).generate_questions(
            node_id, count=body.count
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [_to_out(c) for c in claims]
