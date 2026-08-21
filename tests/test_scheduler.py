import uuid
from datetime import date, timedelta

import pytest

from app.planning.scheduler import (
    Assignment,
    UnitInput,
    WindowInput,
    solve_schedule,
    validate_schedule,
)

START = date(2026, 1, 5)


def _uid() -> uuid.UUID:
    return uuid.uuid4()


def _windows(n: int, minutes: int = 60, unavailable: set[int] = frozenset()) -> list[WindowInput]:
    return [
        WindowInput(
            window_id=_uid(),
            date=START + timedelta(days=i),
            available_minutes=minutes,
            is_available=i not in unavailable,
        )
        for i in range(n)
    ]


def test_each_unit_gets_a_distinct_window():
    units = [UnitInput(unit_id=_uid(), duration_minutes=60) for _ in range(3)]
    windows = _windows(5)

    result = solve_schedule(units, windows)

    assert result.status in ("optimal", "feasible")
    assert not result.unscheduled_unit_ids
    assigned_windows = [a.window_id for a in result.assignments]
    assert len(assigned_windows) == len(set(assigned_windows))
    assert validate_schedule(result.assignments, units, windows) == []


def test_prerequisite_scheduled_strictly_before_dependent():
    prereq = UnitInput(unit_id=_uid(), duration_minutes=60)
    dependent = UnitInput(
        unit_id=_uid(), duration_minutes=60, prerequisite_unit_ids=(prereq.unit_id,)
    )
    windows = _windows(5)

    result = solve_schedule([dependent, prereq], windows)

    by_unit = {a.unit_id: a.date for a in result.assignments}
    assert by_unit[prereq.unit_id] < by_unit[dependent.unit_id]
    assert validate_schedule(result.assignments, [dependent, prereq], windows) == []


def test_unavailable_windows_are_never_used():
    units = [UnitInput(unit_id=_uid(), duration_minutes=60) for _ in range(2)]
    windows = _windows(4, unavailable={0, 1})

    result = solve_schedule(units, windows)

    used = {a.window_id for a in result.assignments}
    unavailable_ids = {w.window_id for w in windows if not w.is_available}
    assert used.isdisjoint(unavailable_ids)


def test_deadline_is_respected():
    deadline = START + timedelta(days=1)
    unit = UnitInput(unit_id=_uid(), duration_minutes=60, deadline=deadline)
    # Only windows after the deadline are available -> infeasible to place.
    windows = _windows(5)[2:]

    result = solve_schedule([unit], windows)

    assert unit.unit_id in result.unscheduled_unit_ids


def test_churn_minimization_prefers_previous_assignment():
    a = UnitInput(unit_id=_uid(), duration_minutes=60)
    b = UnitInput(unit_id=_uid(), duration_minutes=60)
    windows = _windows(4)
    previous = {a.unit_id: windows[0].window_id, b.unit_id: windows[1].window_id}

    result = solve_schedule([a, b], windows, previous_assignment=previous)

    assert result.unchanged_count == 2
    assert result.moved_count == 0


def test_disruption_moves_only_the_affected_unit():
    a = UnitInput(unit_id=_uid(), duration_minutes=60)
    b = UnitInput(unit_id=_uid(), duration_minutes=60)
    windows = _windows(4)
    previous = {a.unit_id: windows[0].window_id, b.unit_id: windows[1].window_id}

    # Day 0 becomes unavailable, mimicking a calendar disruption.
    disrupted = [w for w in windows if w.date != windows[0].date] + [
        WindowInput(windows[0].window_id, windows[0].date, windows[0].available_minutes, is_available=False)
    ]

    result = solve_schedule([a, b], disrupted, previous_assignment=previous)

    assert result.unchanged_count == 1
    assert result.moved_count == 1


def test_validate_schedule_flags_double_booking():
    unit_a = UnitInput(unit_id=_uid(), duration_minutes=60)
    unit_b = UnitInput(unit_id=_uid(), duration_minutes=60)
    window = WindowInput(window_id=_uid(), date=START, available_minutes=60)

    assignments = [
        Assignment(unit_id=unit_a.unit_id, window_id=window.window_id, date=START),
        Assignment(unit_id=unit_b.unit_id, window_id=window.window_id, date=START),
    ]

    violations = validate_schedule(assignments, [unit_a, unit_b], [window])
    assert any("double-booked" in v for v in violations)


def test_validate_schedule_flags_prerequisite_violation():
    prereq = UnitInput(unit_id=_uid(), duration_minutes=60)
    dependent = UnitInput(
        unit_id=_uid(), duration_minutes=60, prerequisite_unit_ids=(prereq.unit_id,)
    )
    w1 = WindowInput(window_id=_uid(), date=START, available_minutes=60)
    w2 = WindowInput(window_id=_uid(), date=START + timedelta(days=1), available_minutes=60)

    # Dependent scheduled before its prerequisite -> should be flagged.
    assignments = [
        Assignment(unit_id=dependent.unit_id, window_id=w1.window_id, date=w1.date),
        Assignment(unit_id=prereq.unit_id, window_id=w2.window_id, date=w2.date),
    ]

    violations = validate_schedule(assignments, [dependent, prereq], [w1, w2])
    assert any("prerequisite" in v for v in violations)


def test_empty_units_returns_empty_optimal_schedule():
    result = solve_schedule([], _windows(3))
    assert result.status == "optimal"
    assert result.assignments == []
