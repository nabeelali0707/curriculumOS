"""Academic calendar + instruction window setup, and the "school closed"
disruption endpoint that powers the replan demo
(06_MVP_SCOPE_AND_DEMO.md's "demo moment that matters most"). Nothing in
the app could create AcademicCalendar/CalendarDay/InstructionWindow rows
before this — app/planning/service.py needs them to exist, but had no
producer.
"""

from datetime import date, datetime, time, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.domain.models import AcademicCalendar, CalendarDay, DayType, InstructionWindow

router = APIRouter(prefix="/calendars", tags=["calendar"])


class CreateCalendarRequest(BaseModel):
    school_id: str
    term_start: date
    term_end: date
    non_teaching_dates: list[date] = []
    exam_dates: list[date] = []


class CalendarOut(BaseModel):
    id: UUID
    school_id: str
    term_start: date
    term_end: date
    day_count: int


@router.post("/", response_model=CalendarOut)
async def create_calendar(
    body: CreateCalendarRequest, session: AsyncSession = Depends(get_session)
) -> CalendarOut:
    if body.term_end < body.term_start:
        raise HTTPException(status_code=422, detail="term_end must be on or after term_start")

    calendar = AcademicCalendar(
        school_id=body.school_id, term_start=body.term_start, term_end=body.term_end
    )
    session.add(calendar)
    await session.flush()

    non_teaching = set(body.non_teaching_dates)
    exam = set(body.exam_dates)
    day_count = 0
    d = body.term_start
    while d <= body.term_end:
        # ponytail: Sat/Sun default to non-teaching unless overridden by
        # exam_dates — a real deployment would take this from the school's
        # actual week structure; not modeled yet.
        if d in exam:
            day_type = DayType.EXAM_DAY
        elif d in non_teaching or d.weekday() >= 5:
            day_type = DayType.NON_TEACHING
        else:
            day_type = DayType.SCHOOL_DAY
        session.add(CalendarDay(calendar_id=calendar.id, date=d, day_type=day_type))
        day_count += 1
        d += timedelta(days=1)

    await session.commit()
    return CalendarOut(
        id=calendar.id, school_id=calendar.school_id,
        term_start=calendar.term_start, term_end=calendar.term_end, day_count=day_count,
    )


@router.get("/", response_model=list[CalendarOut])
async def list_calendars(session: AsyncSession = Depends(get_session)) -> list[CalendarOut]:
    calendars = (await session.execute(select(AcademicCalendar))).scalars().all()
    out = []
    for c in calendars:
        day_count = len(
            (await session.execute(select(CalendarDay).where(CalendarDay.calendar_id == c.id)))
            .scalars()
            .all()
        )
        out.append(
            CalendarOut(id=c.id, school_id=c.school_id, term_start=c.term_start, term_end=c.term_end, day_count=day_count)
        )
    return out


class TimetableSlot(BaseModel):
    subject: str
    class_id: str
    weekday: int  # 0=Monday .. 6=Sunday
    start_time: time
    end_time: time


class CreateWindowsRequest(BaseModel):
    slots: list[TimetableSlot]


class CreateWindowsOut(BaseModel):
    windows_created: int


@router.post("/{calendar_id}/instruction-windows", response_model=CreateWindowsOut)
async def create_instruction_windows(
    calendar_id: UUID, body: CreateWindowsRequest, session: AsyncSession = Depends(get_session)
) -> CreateWindowsOut:
    school_days = (
        (
            await session.execute(
                select(CalendarDay).where(
                    CalendarDay.calendar_id == calendar_id, CalendarDay.day_type == DayType.SCHOOL_DAY
                )
            )
        )
        .scalars()
        .all()
    )
    if not school_days:
        raise HTTPException(status_code=404, detail="no school days found for this calendar")

    created = 0
    for slot in body.slots:
        minutes = (
            datetime.combine(date.min, slot.end_time) - datetime.combine(date.min, slot.start_time)
        ).seconds // 60
        if minutes <= 0:
            raise HTTPException(status_code=422, detail=f"end_time must be after start_time for {slot}")
        for day in school_days:
            if day.date.weekday() != slot.weekday:
                continue
            session.add(
                InstructionWindow(
                    calendar_day_id=day.id,
                    subject=slot.subject,
                    class_id=slot.class_id,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    available_minutes=minutes,
                    is_available=True,
                )
            )
            created += 1

    await session.commit()
    return CreateWindowsOut(windows_created=created)


class DisruptRequest(BaseModel):
    date: date
    reason: str = "unavailable"


class DisruptOut(BaseModel):
    date: date
    windows_disrupted: int


@router.post("/{calendar_id}/disrupt", response_model=DisruptOut)
async def disrupt_day(
    calendar_id: UUID, body: DisruptRequest, session: AsyncSession = Depends(get_session)
) -> DisruptOut:
    """Marks one calendar day non-teaching and its windows unavailable —
    the one input the "school closed March 12" replan demo needs. Call
    /planning/plans again afterward with parent_version_id set to the prior
    plan to see the churn-minimized replan.
    """
    day = (
        await session.execute(
            select(CalendarDay).where(CalendarDay.calendar_id == calendar_id, CalendarDay.date == body.date)
        )
    ).scalar_one_or_none()
    if day is None:
        raise HTTPException(status_code=404, detail="no calendar_day for that date")

    day.day_type = DayType.NON_TEACHING
    windows = (
        (await session.execute(select(InstructionWindow).where(InstructionWindow.calendar_day_id == day.id)))
        .scalars()
        .all()
    )
    for w in windows:
        w.is_available = False

    await session.commit()
    return DisruptOut(date=body.date, windows_disrupted=len(windows))
