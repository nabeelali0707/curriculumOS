# 07 — Task Roadmap

Priorities are P0 (build first) through P3 (defer). The key reversal to internalize: **don't spend disproportionate effort on lesson generation early.** LLMs already make that relatively easy. Spend the effort on the structured system around the LLM — provenance, mapping, scheduling, and the correction feedback loop. That is the part that's actually hard to copy.

## P0 — Foundation (nothing else works without these)

- [ ] **Provider abstraction layer** (`04_PROVIDER_STRATEGY.md`). Build the interface first, wire exactly one provider through it per capability (LLM, embeddings, parsing), confirm it works end-to-end, then add fallback chains.
- [ ] **Provenance-preserving ingestion pipeline.** Docling as primary parser → structured blocks with page/bbox/hash → `source_documents` + `source_spans` tables populated. Acceptance: given a sample textbook PDF, every extracted paragraph is traceable to an exact page and bounding box.
- [ ] **Curriculum/objective domain model in Postgres.** Implement the schema from `03_DATA_MODELS.md` §1. Acceptance: can represent a real syllabus's topic → subtopic → objective → prerequisite structure with confidence/origin on every edge.
- [ ] **Question + mark-scheme parser.** Extract exam questions and their linked mark scheme entries as one entity (`question ↔ mark_scheme_entry`), with marks and page attribution. This is a differentiating dataset — don't shortcut it.
- [ ] **Question → objective mapper (ensemble).** Implement the multi-signal approach from `04_PROVIDER_STRATEGY.md` §4 (embedding similarity + lexical retrieval + syllabus terminology + LLM classification), producing multi-label weighted mappings with confidence, not single-label classification.

## P1 — Core product wedge

- [ ] **Historical assessment emphasis calculation.** Implement the weighted formula from `03_DATA_MODELS.md` §4 (frequency, recency decay, marks, syllabus weighting, structural similarity) — not raw frequency counting.
- [ ] **Scheduling/replanning prototype (OR-Tools CP-SAT).** Model teaching units and calendar-as-capacity (`02_ARCHITECTURE.md`). Implement hard constraints first (prerequisite order, non-teaching days, fixed exam dates, teacher unavailability), then medium (coverage of high-priority objectives, protect already-taught lessons), then soft (pacing smoothness, minimize fragmentation, **minimize plan instability** — weight this heavily).
- [ ] **Teacher correction UI.** Every correction a teacher makes to an extracted objective, a question mapping, or a scheduled unit should be logged to `teacher_corrections` and fed back as a high-trust signal into the mapping ensemble.

## P2 — Useful, but not the moat

- [ ] **Grounded lesson generation.** Implement the verify-then-render pipeline (`02_ARCHITECTURE.md` §4): retrieve evidence → generate structured claims → claim↔evidence verification (different provider/model than generation) → reject unsupported claims → render. This is P2, not P0, deliberately — lesson generation is the commoditized part of the product.
- [ ] **Assessment generation.** Generate practice questions/quizzes grounded in retrieved source spans and tagged to objectives, reusing the same verify-then-render approach.

## P3 — Defer until planning/replanning is proven

- [ ] **Student-level analytics.** Deferred due to PII/compliance scope (FERPA/GDPR-equivalent depending on market) — see `09_RISKS_AND_OPEN_QUESTIONS.md`. Do not build this before P0/P1 are solid.
- [ ] **Full remediation system.** Depends on student-level tracking; also deferred. A class-level teacher-marked signal (`mastered` / `needs_reinforcement` / `reteach`) feeding replanning is the only remediation-adjacent feature in scope before this.

## Cross-cutting, ongoing throughout all phases

- [ ] **Metrics instrumentation** from day one, not bolted on later. Track: objective extraction precision/recall, question parsing accuracy, page attribution accuracy, citation precision/recall, unsupported-claim rate, question→objective precision@k, human correction rate, hard-constraint violations (target zero), schedule churn after a disruption, teacher edits required post-replan, and — the business metric — minutes required to go from uploaded sources to an acceptable term plan.
- [ ] **Confidence + origin tagging** enforced on every machine-derived record, checked in code review, not just documented as an intention.
- [ ] **Cost/latency tracking per LLM provider call**, tagged by task (generation vs. verification vs. mapping), from the first integration — not added retroactively when a bill is surprising.

## Suggested build order at a glance

```
Week 1–2:   Provider abstraction layer + one provider wired per capability
Week 2–4:   Ingestion pipeline + provenance store + evaluation corpus benchmark
Week 3–5:   Curriculum domain model schema + teacher review UI (basic)
Week 4–6:   Question/mark-scheme parser + question→objective ensemble mapper
Week 5–7:   Historical emphasis scoring
Week 6–9:   OR-Tools scheduling engine, hard constraints first
Week 8–10:  Teacher correction logging + soft constraints (incl. plan-instability minimization)
Week 9–11:  Grounded lesson generation (verify-then-render)
Week 10–12: End-to-end MVP demo flow + acceptance criteria from 06_MVP_SCOPE_AND_DEMO.md
```
This is a rough sequencing guide, not a committed schedule — adjust based on what the actual ingestion/parsing evaluation corpus reveals in weeks 1–2, since that will materially affect timeline confidence for everything downstream.
