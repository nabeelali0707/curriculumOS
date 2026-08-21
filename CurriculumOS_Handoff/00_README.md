# CurriculumOS — Build Handoff Package

This folder is a complete build brief for **CurriculumOS**: a curriculum planning engine that grounds every scheduled lesson in a verifiable source, and automatically repairs the term plan when the calendar changes.

It's written to be handed to an agentic coding tool (or a human engineering team) as a self-contained spec. Read the files in this order:

| # | File | What it answers |
|---|---|---|
| 1 | `01_PROJECT_BRIEF.md` | What are we building and why does it matter? |
| 2 | `02_ARCHITECTURE.md` | How do the pieces fit together? |
| 3 | `03_DATA_MODELS.md` | What does the actual schema look like? |
| 4 | `04_PROVIDER_STRATEGY.md` | Which external providers do we depend on, and what happens when one fails? |
| 5 | `05_TECH_STACK.md` | What libraries/tools/versions do we use, and why? |
| 6 | `06_MVP_SCOPE_AND_DEMO.md` | What exactly ships first, and how do we know it worked? |
| 7 | `07_TASK_ROADMAP.md` | What order do we build things in? |
| 8 | `08_AGENT_BUILD_INSTRUCTIONS.md` | Repo conventions, secrets handling, definition of done |
| 9 | `09_RISKS_AND_OPEN_QUESTIONS.md` | What should the builder flag instead of silently deciding? |

## Ground rules for whoever (or whatever) builds this

1. **Don't build the whole v1 architecture on day one.** `06_MVP_SCOPE_AND_DEMO.md` defines a deliberately narrow first slice. Resist adding Neo4j, a dedicated vector DB, or multi-provider embedding routing until the MVP proves the core loop and you've actually measured a bottleneck.
2. **Every generated instructional claim must carry provenance.** No "source: page 47" — an actual span reference that can be mechanically checked. See `03_DATA_MODELS.md` §2.
3. **No student-level data in v1.** Class-level, teacher-entered mastery signals only. See `09_RISKS_AND_OPEN_QUESTIONS.md`.
4. **Treat every external API (LLM, embeddings, parsing) as something that will fail or get deprecated.** `04_PROVIDER_STRATEGY.md` is not optional — build the abstraction layer first, wire a single provider through it, and only then add the fallback chain.
5. **When something in these docs is ambiguous or looks wrong, stop and flag it rather than guessing.** This spec was written in August 2026; provider APIs, pricing, and model rankings move fast — verify anything provider-specific (model names, pricing, rate limits) against current docs before hard-coding it.

## One-line project description (for commit messages / repo README)

> CurriculumOS ingests textbooks, past papers, mark schemes, and academic calendars to build a grounded, citable term plan — and automatically replans it when the calendar changes, while minimizing disruption to what's already been taught.
