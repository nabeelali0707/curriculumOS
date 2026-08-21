"""OR-Tools CP-SAT scheduling prototype (02_ARCHITECTURE.md §5,
04_PROVIDER_STRATEGY.md §5, 07_TASK_ROADMAP.md P1).

Pure over plain dataclasses — no DB session, no ORM — same pattern as
app/mapping/signals.py and app/ingestion/question_parser.py. A thin
service module wires this to teaching_units/instruction_windows/
scheduled_units when that's needed; this module is the part worth
unit-testing in isolation.

Scope of this prototype: hard constraints only, plus the one
non-functional requirement the handoff docs call out as the most
important thing to get right from day one — minimizing plan churn
against a previous assignment. Medium constraints (coverage priority
beyond "schedule everything if possible") and most soft constraints
(pacing smoothness, fragmentation) are NOT implemented yet.
# ponytail: hard constraints + churn-minimization only; add coverage
# priority weighting and pacing-smoothness soft constraints once a real
# term plan surfaces a need for them, not speculatively.

One unit occupies at most one window and one window holds at most one
unit — a teacher does not teach two teaching units in the same period.
Splitting a unit across multiple sessions (`TeachingUnit.splittable`) is
out of scope for this prototype.
# ponytail: splittable units are scheduled as a single indivisible block
# for now; add multi-session splitting once the single-session model is
# proven against a real calendar.
"""

import logging
from dataclasses import dataclass, field
from datetime import date as date_
from uuid import UUID

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnitInput:
    unit_id: UUID
    duration_minutes: int
    priority: float = 0.0
    prerequisite_unit_ids: tuple[UUID, ...] = ()
    deadline: date_ | None = None  # e.g. must be taught before the exam date


@dataclass(frozen=True)
class WindowInput:
    window_id: UUID
    date: date_
    available_minutes: int
    is_available: bool = True


@dataclass(frozen=True)
class Assignment:
    unit_id: UUID
    window_id: UUID
    date: date_


@dataclass(frozen=True)
class ScheduleResult:
    status: str  # "optimal" | "feasible" | "greedy_fallback"
    assignments: list[Assignment]
    unscheduled_unit_ids: list[UUID]
    unchanged_count: int
    moved_count: int


class InfeasibleScheduleError(Exception):
    """No hard-constraint-satisfying plan exists at all (e.g. not enough
    available windows before a hard deadline). Distinct from "some units
    couldn't be scheduled" (ScheduleResult.unscheduled_unit_ids), which is
    the CP-SAT/greedy result when the *feasible subset* still has to be
    reported to a teacher, not raised as an error.
    """


def validate_schedule(
    assignments: list[Assignment], units: list[UnitInput], windows: list[WindowInput]
) -> list[str]:
    """Hard-constraint invariants, checked independently of whichever path
    (CP-SAT or greedy) produced `assignments`. Per 04_PROVIDER_STRATEGY.md
    §5: "a solver bug or timeout-truncated solution should never silently
    violate a hard constraint" — call this after every solve, not just in
    tests.
    """
    violations = []
    units_by_id = {u.unit_id: u for u in units}
    windows_by_id = {w.window_id: w for w in windows}
    assigned_date: dict[UUID, date_] = {}
    window_usage: dict[UUID, list[UUID]] = {}

    for a in assignments:
        window = windows_by_id.get(a.window_id)
        unit = units_by_id.get(a.unit_id)
        if window is None or unit is None:
            violations.append(f"{a.unit_id}: references unknown unit/window")
            continue
        if not window.is_available:
            violations.append(f"{a.unit_id}: assigned to unavailable window {a.window_id}")
        if unit.duration_minutes > window.available_minutes:
            violations.append(f"{a.unit_id}: does not fit in window {a.window_id}")
        if unit.deadline is not None and window.date > unit.deadline:
            violations.append(f"{a.unit_id}: scheduled after its deadline {unit.deadline}")
        assigned_date[a.unit_id] = window.date
        window_usage.setdefault(a.window_id, []).append(a.unit_id)

    for window_id, unit_ids in window_usage.items():
        if len(unit_ids) > 1:
            violations.append(f"window {window_id}: double-booked by {unit_ids}")

    for unit in units:
        if unit.unit_id not in assigned_date:
            continue
        for prereq_id in unit.prerequisite_unit_ids:
            prereq_date = assigned_date.get(prereq_id)
            if prereq_date is not None and prereq_date >= assigned_date[unit.unit_id]:
                violations.append(
                    f"{unit.unit_id}: scheduled on/before prerequisite {prereq_id}"
                )

    return violations


def _diff_previous(
    assignments: list[Assignment], previous_assignment: dict[UUID, UUID] | None
) -> tuple[int, int]:
    if not previous_assignment:
        return 0, len(assignments)
    unchanged = sum(
        1 for a in assignments if previous_assignment.get(a.unit_id) == a.window_id
    )
    return unchanged, len(assignments) - unchanged


def _candidate_windows(unit: UnitInput, windows: list[WindowInput]) -> list[WindowInput]:
    return [
        w
        for w in windows
        if w.is_available
        and w.available_minutes >= unit.duration_minutes
        and (unit.deadline is None or w.date <= unit.deadline)
    ]


def _greedy_schedule(
    units: list[UnitInput],
    windows: list[WindowInput],
    previous_assignment: dict[UUID, UUID] | None,
) -> ScheduleResult:
    """Time-boxed CP-SAT solve failed or was skipped — fall back to a
    heuristic that guarantees *a* feasible plan rather than no plan at all
    (04_PROVIDER_STRATEGY.md §5). Highest priority first; prefers the
    previous window when it's still a legal candidate, to keep churn down
    even in the fallback path.
    """
    remaining_windows = {w.window_id: w for w in windows}
    scheduled_dates: dict[UUID, date_] = {}
    assignments: list[Assignment] = []
    unscheduled: list[UUID] = []

    ordered = sorted(units, key=lambda u: (-u.priority, u.unit_id.int))
    for unit in ordered:
        prereq_dates = [scheduled_dates[p] for p in unit.prerequisite_unit_ids if p in scheduled_dates]
        earliest_allowed = max(prereq_dates, default=None)

        candidates = [
            w
            for w in remaining_windows.values()
            if w.is_available
            and w.available_minutes >= unit.duration_minutes
            and (unit.deadline is None or w.date <= unit.deadline)
            and (earliest_allowed is None or w.date > earliest_allowed)
        ]
        if not candidates:
            unscheduled.append(unit.unit_id)
            continue

        preferred_id = (previous_assignment or {}).get(unit.unit_id)
        chosen = next((w for w in candidates if w.window_id == preferred_id), None)
        if chosen is None:
            chosen = min(candidates, key=lambda w: (w.date, w.window_id.int))

        assignments.append(Assignment(unit_id=unit.unit_id, window_id=chosen.window_id, date=chosen.date))
        scheduled_dates[unit.unit_id] = chosen.date
        del remaining_windows[chosen.window_id]

    unchanged, moved = _diff_previous(assignments, previous_assignment)
    return ScheduleResult(
        status="greedy_fallback",
        assignments=assignments,
        unscheduled_unit_ids=unscheduled,
        unchanged_count=unchanged,
        moved_count=moved,
    )


def solve_schedule(
    units: list[UnitInput],
    windows: list[WindowInput],
    *,
    previous_assignment: dict[UUID, UUID] | None = None,
    time_limit_seconds: float = 30.0,
    churn_penalty: int = 1_000,
) -> ScheduleResult:
    """Assign every unit that has at least one legal window to exactly one
    window (units with zero legal candidates land in
    `unscheduled_unit_ids` instead), respecting hard constraints (window
    availability/capacity, prerequisite ordering, deadlines, one unit per
    window), minimizing churn against `previous_assignment` first and
    total elapsed time second. Falls back to a greedy heuristic if CP-SAT
    can't find a feasible solution within `time_limit_seconds`.
    """
    if not units:
        return ScheduleResult("optimal", [], [], 0, 0)

    sorted_windows = sorted(windows, key=lambda w: (w.date, w.window_id.int))
    date_index = {w.window_id: i for i, w in enumerate(sorted_windows)}

    model = cp_model.CpModel()
    x: dict[tuple[UUID, UUID], cp_model.IntVar] = {}
    candidates_by_unit: dict[UUID, list[WindowInput]] = {}

    for unit in units:
        candidates = _candidate_windows(unit, sorted_windows)
        candidates_by_unit[unit.unit_id] = candidates
        for w in candidates:
            x[(unit.unit_id, w.window_id)] = model.NewBoolVar(f"x_{unit.unit_id}_{w.window_id}")

    for w in sorted_windows:
        occupants = [x[(u.unit_id, w.window_id)] for u in units if (u.unit_id, w.window_id) in x]
        if occupants:
            model.Add(sum(occupants) <= 1)

    # date_index[u] == the window index it lands on, or 0 if left
    # unscheduled (all its x vars are 0, so the sum collapses to 0 for
    # free — no separate "unscheduled" case to model).
    unit_date_index: dict[UUID, cp_model.IntVar] = {}
    is_scheduled: dict[UUID, cp_model.IntVar] = {}
    for unit in units:
        candidates = candidates_by_unit[unit.unit_id]
        var = model.NewIntVar(0, max(len(sorted_windows), 1), f"date_idx_{unit.unit_id}")
        unit_date_index[unit.unit_id] = var
        model.Add(
            var == sum(date_index[w.window_id] * x[(unit.unit_id, w.window_id)] for w in candidates)
        )

        # Scheduling every unit that has at least one legal candidate
        # window is itself a hard requirement here, not a preference —
        # leaving a teaching unit off the plan while a valid slot exists
        # would make the "term plan" incomplete by construction. A unit
        # only ends up in unscheduled_unit_ids when it has zero candidates
        # (e.g. its deadline already passed).
        scheduled_flag = model.NewBoolVar(f"scheduled_{unit.unit_id}")
        is_scheduled[unit.unit_id] = scheduled_flag
        if candidates:
            model.Add(sum(x[(unit.unit_id, w.window_id)] for w in candidates) == 1)
            model.Add(scheduled_flag == 1)
        else:
            model.Add(scheduled_flag == 0)

    for unit in units:
        for prereq_id in unit.prerequisite_unit_ids:
            if prereq_id not in unit_date_index:
                continue
            # Only enforced when both units are actually scheduled — an
            # unscheduled prerequisite (date_index pinned to 0) must not
            # spuriously block its dependent.
            model.Add(unit_date_index[unit.unit_id] > unit_date_index[prereq_id]).OnlyEnforceIf(
                [is_scheduled[unit.unit_id], is_scheduled[prereq_id]]
            )

    churn_terms = []
    if previous_assignment:
        for unit in units:
            prev_window = previous_assignment.get(unit.unit_id)
            if prev_window is None:
                continue
            var = x.get((unit.unit_id, prev_window))
            if var is not None:
                changed = model.NewBoolVar(f"changed_{unit.unit_id}")
                model.Add(changed == 1 - var)
                churn_terms.append(changed)
            # If the previous window isn't even a legal candidate anymore
            # (e.g. it became unavailable), there's no "stay" option to
            # penalize against — any assignment already counts as moved.

    total_index = sum(unit_date_index.values()) if unit_date_index else 0
    model.Minimize(churn_penalty * sum(churn_terms) + total_index)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("scheduler: CP-SAT found no solution in time, falling back to greedy")
        result = _greedy_schedule(units, sorted_windows, previous_assignment)
    else:
        assignments = []
        scheduled_ids = set()
        for unit in units:
            for w in candidates_by_unit[unit.unit_id]:
                if solver.Value(x[(unit.unit_id, w.window_id)]) == 1:
                    assignments.append(Assignment(unit_id=unit.unit_id, window_id=w.window_id, date=w.date))
                    scheduled_ids.add(unit.unit_id)
                    break
        unscheduled = [u.unit_id for u in units if u.unit_id not in scheduled_ids]
        unchanged, moved = _diff_previous(assignments, previous_assignment)
        result = ScheduleResult(
            status="optimal" if status == cp_model.OPTIMAL else "feasible",
            assignments=assignments,
            unscheduled_unit_ids=unscheduled,
            unchanged_count=unchanged,
            moved_count=moved,
        )

    violations = validate_schedule(result.assignments, units, sorted_windows)
    if violations:
        # Never silently present a plan that violates a hard constraint —
        # surface it loudly instead of returning a plan a teacher would
        # trust. A validated invariant failing means a modeling bug, not
        # bad input data (bad input already gets filtered into
        # unscheduled_unit_ids above).
        raise InfeasibleScheduleError(
            f"scheduler produced {len(violations)} hard-constraint violation(s): {violations}"
        )

    return result
