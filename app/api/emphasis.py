"""Historical assessment emphasis score endpoint. Thin wrapper over
app/emphasis/service.py — see that module for the scoring logic.
"""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.emphasis.service import HistoricalAssessmentEmphasisService

router = APIRouter(prefix="/emphasis", tags=["emphasis"])


class EmphasisOut(BaseModel):
    node_id: UUID
    score: float
    frequency: float
    recency: float
    marks: float
    syllabus: float
    structural: float


@router.get("/", response_model=list[EmphasisOut])
async def get_emphasis_scores(
    current_year: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[EmphasisOut]:
    results = await HistoricalAssessmentEmphasisService(session).calculate(current_year=current_year)
    return [
        EmphasisOut(
            node_id=r.node_id,
            score=r.score,
            frequency=r.components.frequency,
            recency=r.components.recency,
            marks=r.components.marks,
            syllabus=r.components.syllabus,
            structural=r.components.structural,
        )
        for r in results
    ]
