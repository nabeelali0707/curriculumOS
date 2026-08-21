"""Teacher correction logging (02_ARCHITECTURE.md §6, 04_PROVIDER_STRATEGY.md
§4: "Every teacher correction should be logged ... and weighted as ground
truth going forward").

A correction is always logged to `teacher_corrections` verbatim, regardless
of entity type — that history is the compounding asset the roadmap calls
out. For `question_node_mapping` specifically, the correction also
overwrites the live mapping row: a human correction is the one signal the
ensemble (app/mapping/mapper.py) treats as always-wins, so it's applied
here rather than left to be re-derived by a future mapping run.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import MappingMethod, QuestionNodeMapping, TeacherCorrection

router = APIRouter(prefix="/corrections", tags=["corrections"])


class CorrectionIn(BaseModel):
    entity_type: str
    entity_id: UUID
    before_value: dict
    after_value: dict
    teacher_id: str


class CorrectionOut(BaseModel):
    id: UUID


@router.post("/", response_model=CorrectionOut)
async def create_correction(
    body: CorrectionIn, session: AsyncSession = Depends(get_session)
) -> CorrectionOut:
    correction = TeacherCorrection(
        entity_type=body.entity_type,
        entity_id=body.entity_id,
        before_value=body.before_value,
        after_value=body.after_value,
        teacher_id=body.teacher_id,
    )
    session.add(correction)

    if body.entity_type == "question_node_mapping":
        mapping = await session.get(QuestionNodeMapping, body.entity_id)
        if mapping is None:
            raise HTTPException(status_code=404, detail="question_node_mapping not found")
        mapping.weight = float(body.after_value.get("weight", mapping.weight))
        # Confidence is pinned to 1.0, not taken from after_value — a
        # teacher correction is definitionally certain, per §4's "always
        # wins when present".
        mapping.confidence = 1.0
        mapping.mapping_method = MappingMethod.HUMAN_CORRECTED
        mapping.corrected_by = body.teacher_id

    await session.commit()
    await session.refresh(correction)
    return CorrectionOut(id=correction.id)
