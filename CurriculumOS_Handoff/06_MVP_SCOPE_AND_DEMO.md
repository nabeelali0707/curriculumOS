# 06 — MVP Scope & Demo

## Subject choice
One exam-driven subject with explicit topic relationships and clear textbook sourcing. Good candidates: IGCSE/GCSE Biology, IGCSE Mathematics. Biology is a reasonable first choice — topic relationships and textbook sourcing tend to be explicit and well-structured.

## Required inputs for the pilot
- 1 syllabus
- 1 textbook
- 5 years of past papers
- 5 years of mark schemes
- Academic calendar (term dates, non-teaching days, exam dates)
- Weekly lesson timetable (which periods this subject/class has, and for how long)

## Product flow
```
Upload sources
      ↓
CurriculumOS extracts curriculum structure (objectives, subtopics, prerequisites)
      ↓
Teacher reviews and corrects the extracted structure
      ↓
Past-paper questions are mapped to objectives (multi-label, with confidence)
      ↓
System computes historical assessment emphasis score per objective
      ↓
Teacher confirms/adjusts teaching availability
      ↓
Solver builds the term plan (teaching units → calendar slots)
      ↓
Teacher can click any scheduled lesson and ask:
  "Why is this scheduled here?"
      ↓
System explains:
  - prerequisite dependency
  - syllabus objective it covers
  - textbook pages it draws from
  - historical assessment weight
  - time remaining before the exam
```

## The demo moment that matters most

This is more compelling — and more trust-building — than another nicely formatted lesson plan:

> **Teacher:** "School closed March 12."
>
> **System:** *Replanning...*
> - Cell division moved Mar 12 → Mar 15
> - Enzymes compressed from 3 sessions → 2
> - Low-priority enrichment task removed
> - Revision block preserved
> - Exam date unchanged
> - **7 lessons unchanged. 3 lessons moved. 1 lesson shortened.**

The last line is the point: a good replan is measured by how little it disturbs, not by how clever the rearrangement is.

## Acceptance criteria for the MVP

- [ ] A teacher can upload a syllabus, textbook, and 5 years of past papers/mark schemes and get back an extracted curriculum structure within a reasonable time (define a target, e.g. under 10 minutes for a full subject).
- [ ] Every extracted objective and every question→objective mapping displays a confidence score and origin tag in the teacher workspace.
- [ ] A teacher can correct a mapping, and that correction is persisted and logged.
- [ ] The solver produces a full-term plan that satisfies all hard constraints (zero violations) given a real calendar and timetable.
- [ ] Clicking any scheduled lesson shows its justification (prerequisite, objective, source pages, emphasis weight, time-to-exam).
- [ ] Simulating a calendar disruption (e.g. marking a day unavailable) triggers a replan that satisfies hard constraints, minimizes changes to already-scheduled/already-taught units, and clearly reports what changed vs. what stayed the same.
- [ ] No student-level data is collected or stored anywhere in the MVP (see `09_RISKS_AND_OPEN_QUESTIONS.md`).
- [ ] Every generated lesson claim carries a verification status, and unverified claims are visibly flagged rather than silently rendered as fact.

## Explicitly out of scope for the MVP
- Student-level performance tracking or remediation (class-level teacher-marked signals only: mastered / needs reinforcement / reteach)
- Multi-subject or multi-teacher scheduling in one solve (single subject, single class scope for v1)
- A polished lesson-content authoring UI (a functional, not beautiful, teacher workspace is sufficient for the pilot)
- Multi-provider automatic failover fully load-tested (config-driven fallback chains should exist per `04_PROVIDER_STRATEGY.md`, but exhaustive failover testing across all providers is not a pilot blocker)
