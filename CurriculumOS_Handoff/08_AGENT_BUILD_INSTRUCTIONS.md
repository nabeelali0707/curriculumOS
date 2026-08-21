# 08 — Agent Build Instructions

These are operational instructions for whoever (or whatever) builds this — written assuming an agentic coding tool will be executing tasks from `07_TASK_ROADMAP.md` with limited human oversight per-task.

## Suggested repo structure

```
curriculumos/
├── app/
│   ├── ingestion/          # parsers, provenance extraction, routing by doc type
│   ├── domain/             # curriculum domain model, ORM models matching 03_DATA_MODELS.md
│   ├── mapping/            # question<->objective ensemble mapper
│   ├── emphasis/           # historical assessment emphasis scoring
│   ├── planning/           # OR-Tools CP-SAT models, teaching-unit scheduling
│   ├── generation/         # verify-then-render lesson/assessment generation
│   ├── providers/          # provider abstraction layer (LLM, embeddings, parsing, solver)
│   │   ├── llm/
│   │   ├── embeddings/
│   │   ├── parsing/
│   │   └── solver/
│   ├── api/                # FastAPI routes
│   └── workers/            # background jobs (ingestion, solve, embedding)
├── migrations/              # Postgres schema migrations
├── tests/
├── eval/                    # ingestion parser benchmark corpus + scoring scripts,
│                             # retrieval benchmark (~200 query/source pairs), mapping eval set
├── config/
│   └── providers.yaml       # provider priority config, see 04_PROVIDER_STRATEGY.md §7
└── docs/                    # this handoff package lives here for reference
```

## Provider abstraction — concrete implementation guidance

- Define one interface per capability (`LLMProvider`, `EmbeddingProvider`, `DocumentParser`, `SchedulerBackend`) with a common method signature, so any concrete provider implementation is swappable.
- Concrete provider classes live under `app/providers/<capability>/<provider_name>.py` and implement the interface.
- A `ProviderRouter` (or similar) reads `config/providers.yaml`, resolves the priority list per task, and implements retry/backoff + circuit breaker logic described in `04_PROVIDER_STRATEGY.md`.
- **Do not** scatter direct SDK calls to a specific provider (`anthropic.Client()`, `openai.Client()`, etc.) anywhere outside the `app/providers/` layer. If you find yourself importing a provider SDK directly in `app/generation/` or `app/mapping/`, that's a signal the abstraction boundary is being violated — route it through the provider layer instead.

## Secrets & configuration

- All provider API keys go in environment variables, never committed to the repo. Use a `.env.example` file listing required variable names (not values) for every configured provider.
- `config/providers.yaml` defines *priority and routing logic*, not secrets — keys are injected via environment variables referenced by the provider classes, not stored in this file.
- Document, in `docs/` or the main README, exactly which environment variables are required for the MVP to run with a single (non-fallback) provider configuration, so a fresh setup isn't blocked on configuring every fallback provider on day one.

## Testing expectations

- **Ingestion:** unit tests against the evaluation corpus in `eval/` — assert that known documents produce expected page/bbox/question-number extraction, not just "doesn't crash."
- **Provenance:** test that every claim produced by the generation pipeline resolves to a real, existing span — a broken provenance link should fail a test, not just look wrong in the UI.
- **Mapping:** test the ensemble mapper against a small hand-labeled set (aim for the ~50–100 question set mentioned in `09_RISKS_AND_OPEN_QUESTIONS.md`) and track precision@k over time as a regression metric, not just a one-time check.
- **Scheduling:** test that the solver output has zero hard-constraint violations across multiple synthetic calendars, including edge cases (a disruption on the last day before an exam, a disruption affecting a prerequisite chain).
- **Provider fallback:** simulate a primary-provider failure (e.g. mock a 5xx or timeout) and assert that the system fails over to the configured fallback rather than surfacing an unhandled error to the teacher workspace.

## Definition of done, per task

A task from `07_TASK_ROADMAP.md` is not done until:
1. It passes its own tests (see above).
2. Any new external dependency (LLM call, embedding call, parser, solver) is routed through the provider abstraction layer, not called directly.
3. Any new machine-derived data carries `confidence` and `origin` fields, per `03_DATA_MODELS.md` §6.
4. Any generated instructional claim carries a provenance reference and verification status, per `03_DATA_MODELS.md` §2 — no exceptions, even for "obviously correct" content.
5. Cost/latency of any new provider call path is logged, tagged by task type.

## When something in this spec looks wrong or outdated

This package was written in August 2026. Provider APIs, pricing, model rankings, and even library maintenance status (see the Timefold situation in `04_PROVIDER_STRATEGY.md`) move fast. If a build task depends on a specific claim in this spec (a model's context window, a library's license, a solver's Python support), **verify it against current documentation before implementing**, and flag the discrepancy rather than silently building against stale information. See `09_RISKS_AND_OPEN_QUESTIONS.md` for the standing list of things that should be re-verified rather than assumed.
