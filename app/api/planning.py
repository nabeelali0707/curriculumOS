"""Term-plan build/replan endpoint. Thin wrapper over
app/planning/service.py — see that module and app/planning/scheduler.py
for the actual solve logic.
"""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import (
    CalendarDay,
    CurriculumNode,
    InstructionWindow,
    PlanVersion,
    ScheduledUnit,
    TeachingUnit,
)
from app.planning.service import PlanningService

router = APIRouter(prefix="/planning", tags=["planning"])


class BuildPlanRequest(BaseModel):
    calendar_id: UUID
    subject: str
    class_id: str
    node_ids: list[UUID]
    trigger_reason: str = "initial_plan"
    parent_version_id: UUID | None = None


class AssignmentOut(BaseModel):
    unit_id: UUID
    window_id: UUID
    date: date


class PlanOut(BaseModel):
    plan_version_id: UUID
    status: str
    assignments: list[AssignmentOut]
    unscheduled_unit_ids: list[UUID]
    unchanged_count: int
    moved_count: int


@router.post("/plans", response_model=PlanOut)
async def build_plan(
    body: BuildPlanRequest, session: AsyncSession = Depends(get_session)
) -> PlanOut:
    plan_version, result = await PlanningService(session).build_plan(
        calendar_id=body.calendar_id,
        subject=body.subject,
        class_id=body.class_id,
        node_ids=body.node_ids,
        trigger_reason=body.trigger_reason,
        parent_version_id=body.parent_version_id,
    )
    return PlanOut(
        plan_version_id=plan_version.id,
        status=result.status,
        assignments=[
            AssignmentOut(unit_id=a.unit_id, window_id=a.window_id, date=a.date)
            for a in result.assignments
        ],
        unscheduled_unit_ids=result.unscheduled_unit_ids,
        unchanged_count=result.unchanged_count,
        moved_count=result.moved_count,
    )


class PlanVersionOut(BaseModel):
    id: UUID
    calendar_id: UUID
    parent_version_id: UUID | None
    trigger_reason: str
    scheduled_count: int


@router.get("/plans", response_model=list[PlanVersionOut])
async def list_plans(session: AsyncSession = Depends(get_session)) -> list[PlanVersionOut]:
    """Newest first. The workspace remembers the plan it built in browser
    storage, but a fresh browser has none — this is how it finds the plans
    that already exist rather than making the user rebuild one.
    """
    counts = dict(
        (
            await session.execute(
                select(ScheduledUnit.plan_version, func.count()).group_by(ScheduledUnit.plan_version)
            )
        ).all()
    )
    versions = (
        (await session.execute(select(PlanVersion).order_by(PlanVersion.created_at.desc())))
        .scalars()
        .all()
    )
    return [
        PlanVersionOut(
            id=v.id, calendar_id=v.calendar_id, parent_version_id=v.parent_version_id,
            trigger_reason=v.trigger_reason, scheduled_count=counts.get(v.id, 0),
        )
        for v in versions
    ]


class ScheduledUnitOut(BaseModel):
    id: UUID
    node_label: str
    date: date
    scheduled_minutes: int
    status: str


@router.get("/plans/{plan_version_id}", response_model=list[ScheduledUnitOut])
async def get_plan(
    plan_version_id: UUID, session: AsyncSession = Depends(get_session)
) -> list[ScheduledUnitOut]:
    """The scheduled units for one plan version, for the "click a lesson,
    see why it's there" workspace view (06_MVP_SCOPE_AND_DEMO.md) — this
    endpoint gives the date/status; app/generation/ supplies the
    citations/justification once a lesson is generated for a unit.
    """
    rows = (
        await session.execute(
            select(ScheduledUnit, TeachingUnit, CurriculumNode, InstructionWindow, CalendarDay)
            .join(TeachingUnit, TeachingUnit.id == ScheduledUnit.unit_id)
            .join(CurriculumNode, CurriculumNode.id == TeachingUnit.node_id)
            .join(InstructionWindow, InstructionWindow.id == ScheduledUnit.instruction_window_id)
            .join(CalendarDay, CalendarDay.id == InstructionWindow.calendar_day_id)
            .where(ScheduledUnit.plan_version == plan_version_id)
            .order_by(CalendarDay.date)
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="no scheduled units for that plan_version_id")
    return [
        ScheduledUnitOut(id=su.id, node_label=node.label, date=day.date, scheduled_minutes=su.scheduled_minutes, status=su.status.value)
        for su, tu, node, win, day in rows
    ]
