# 01 — Project Brief

## What this is

CurriculumOS is a curriculum planning engine, not a lesson-generation tool. The distinction matters: lesson generation is a solved, commoditized problem in 2026. What's still open is a system that can (a) **prove** why every scheduled lesson exists, tracing back to a specific source and curriculum objective, and (b) **automatically repair** the plan when reality disrupts the calendar — without needless churn.

## The thesis

Three things, combined, are the product:

1. **Provenance-verified grounding.** Every instructional claim in a generated lesson resolves to a specific, checkable span in a source document (textbook page, syllabus line, mark scheme entry) — not just a citation that looks plausible.
2. **Historical assessment emphasis.** Past exam papers and mark schemes are mapped to curriculum objectives, weighted by recency and current syllabus relevance, to estimate which topics deserve more instructional time.
3. **Constraint-solver-driven replanning.** The term plan is built and repaired by a real constraint solver, not ad-hoc logic — and the solver is tuned to minimize disruption to lessons already taught, not just to find *a* technically valid schedule.

None of the three is individually defensible. Combined, and executed with real engineering rigor (not just prompting), they are.

## Competitive landscape (as of Aug 2026)

Lesson-plan generation itself is crowded: MagicSchool, Kuraplan, TeachQuill, Eduaide, Brisk, and Khanmigo all produce standards-aligned plans today. A known, documented failure mode across this category is that AI lesson planners routinely cite curriculum codes that don't actually exist in the real standards document — which is exactly the trust problem "grounding" is meant to solve. That validates the pain point without validating any one competitor's moat.

We have not identified a mainstream product that combines historical exam-emphasis mapping with constraint-based automatic replanning of a live academic calendar. That is a hypothesis to keep re-testing as the market moves, not a permanent fact.

## What CurriculumOS explicitly is *not*, in v1

- Not a full LMS or gradebook.
- Not a student-facing tutoring product.
- Not a student-level analytics or remediation platform (see `09_RISKS_AND_OPEN_QUESTIONS.md` — this is deliberately deferred, not forgotten).
- Not trying to out-generate MagicSchool/Khanmigo on lesson polish. Lesson generation is P2 in the roadmap, not P0.

## Who it's for (initial pilot)

A single teacher or small department teaching one exam-driven subject (e.g. IGCSE/GCSE Biology), who currently spends hours turning a syllabus + textbook + past papers into a term plan by hand, and who periodically has that plan blown up by a snow day, assembly, or moved exam date.

## The metric that actually matters

Not "lesson quality." It's: **minutes required for a teacher to turn source material into an acceptable term plan**, and **teacher edits required after an automatic replan**. If manual planning takes ~4 hours and this gets it to ~25 minutes, with a replan that a teacher trusts without heavy editing, the product has proven itself.
