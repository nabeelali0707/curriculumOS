# CurriculumOS

> CurriculumOS ingests textbooks, past papers, mark schemes, and academic calendars to build a grounded, citable term plan — and automatically replans it when the calendar changes, while minimizing disruption to what's already been taught.

## Status

Early build, single-tenant MVP. See [`CurriculumOS_Handoff/`](CurriculumOS_Handoff/) for the full spec this is built from — start with [`00_README.md`](CurriculumOS_Handoff/00_README.md).

## Ground rules

1. Every generated instructional claim carries provenance (a mechanically checkable span reference, not "page 47").
2. No student-level data. Class-level, teacher-entered mastery signals only.
3. Every external API (LLM, embeddings, parsing) goes through the provider abstraction in `app/providers/` — never call an SDK directly elsewhere.
4. Minimizing replan churn is a first-class scheduling objective, not an afterthought.

## Local development

Requires Docker (for Postgres + pgvector) and Python 3.11+.

```bash
cp .env.example .env          # fill in provider API keys
docker compose up -d db
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## Required environment variables (MVP, single non-fallback provider)

See [`.env.example`](.env.example) for the full list. At minimum, MVP needs:

- `DATABASE_URL` — Postgres connection string
- `ANTHROPIC_API_KEY` — LLM generation + verification
- One embedding provider key (see `config/providers.yaml`)

## Repo layout

```
app/
  providers/    # LLM, embedding, and parsing abstractions — the only place SDKs are called
  ingestion/    # document parsing -> source_documents / source_spans
  domain/       # curriculum graph, calendar, and ORM models
  mapping/      # question -> objective ensemble mapper
  emphasis/     # historical assessment emphasis scoring
  planning/     # OR-Tools CP-SAT scheduler / replanner
  generation/   # verify-then-render lesson & assessment generation (post-P0)
  api/          # FastAPI routes
  workers/      # Celery tasks
migrations/     # Alembic
config/         # provider routing config (no secrets)
eval/           # retrieval/extraction benchmarks
```
