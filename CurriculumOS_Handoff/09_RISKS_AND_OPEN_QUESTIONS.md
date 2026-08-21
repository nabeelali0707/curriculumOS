# 09 — Risks & Open Questions

Things the builder should flag and get a decision on, rather than silently resolving.

## Deliberate scope exclusions (don't quietly re-add these)

### Student-level data — excluded from v1
Tracking individual student performance introduces:
- PII and data-protection obligations (FERPA/GDPR-equivalent depending on the target market)
- Rostering and authorization complexity
- Assessment grading infrastructure
- Safeguarding concerns

None of this proves the core thesis (grounded planning + replanning). **For v1, support only class-level, teacher-entered outcomes:**
```
Teacher marks objective:
✓ mastered   ~ needs reinforcement   ✗ reteach
```
Replan around that signal. No student profiles, no per-student data model, anywhere in v1. If a future phase needs student-level tracking, that should be a deliberate, separately-scoped decision — not something that creeps in via a "just add a student_id column" shortcut during P2/P3 work.

## Standing risks to monitor, not one-time decisions

### Content licensing
Textbooks and past papers are not ours to redistribute. Internal RAG use (retrieving snippets to ground generated content for the school that uploaded them) is a reasonable use; reselling or redistributing generated content that closely mirrors copyrighted source material is a different legal question. Get this reviewed properly before any multi-tenant or resale product shape, not just at MVP stage.

### Citation/grounding trust
A wrong grounded citation is worse than an ungrounded guess, because it looks authoritative. This is why `03_DATA_MODELS.md` §2 and the verify-then-render pipeline in `02_ARCHITECTURE.md` §4 are treated as core architecture, not a risk mitigation bolted on later. Keep measuring unsupported-claim rate as a first-class metric, forever — not just during initial development.

### Question-mapping reliability
Naive zero-shot LLM classification of exam questions against curriculum objectives will be inconsistent across runs (same question, different objective on a re-run). This is why `04_PROVIDER_STRATEGY.md` §4 specifies an ensemble approach with a growing human-corrected dataset, not a single LLM call. Track precision@k on a held-out labeled set as a regression metric.

### Plan churn / teacher trust
A technically optimal replan that changes too much of an already-communicated term plan will be rejected by teachers regardless of its mathematical quality. "Minimize plan instability" must be a heavily weighted soft constraint from the first version of the scheduling engine, not something added after teachers complain in a pilot.

### Solver platform risk
Constraint-solver libraries in this space have shown real platform instability recently — Timefold's official Python solver was discontinued in 2026 mid-development, with a community fork still stabilizing. OR-Tools CP-SAT is the current recommended choice specifically because it's Python-native and Google-maintained with no JVM dependency, but **treat this as a decision to periodically re-verify**, not a permanent fact. Any time this spec's solver recommendation is acted on, check current maintenance status first.

### Provider API/model drift
Every specific claim in this package about a model's context window, MTEB ranking, license, or pricing reflects research done in August 2026. These facts age quickly. Before hardcoding any specific model choice, context-window assumption, or pricing-based cost estimate into production code, verify it against the provider's current documentation.

### GTM/sales cycle (business risk, not engineering, but worth the builder knowing)
Schools are slow, budget-cycle-bound buyers regardless of product quality. This affects how much infrastructure investment is justified before there's a paying pilot customer — lean toward the minimal MVP stack in `05_TECH_STACK.md` rather than building for hypothetical future scale.

## Open questions requiring a human decision (not to be resolved silently by the builder)

- [ ] Which specific exam board/curriculum standard is the pilot subject aligned to? (Affects syllabus parsing assumptions and terminology matching in the mapping ensemble.)
- [ ] What's the actual data-sharing/licensing arrangement with the pilot school for their textbooks and past papers? (Affects what can legally be stored/processed, and whether generated content can ever be shared beyond the uploading institution.)
- [ ] What's the target deployment model — single-tenant per school, or multi-tenant SaaS? (Affects the data model's isolation requirements and the calendar/instruction-window schema's multi-school considerations, even if only one school is onboarded for the pilot.)
- [ ] What is the actual acceptable time-limit for a solver run before falling back to the greedy heuristic (`04_PROVIDER_STRATEGY.md` §5)? This should be set based on real usage patterns (how often teachers trigger a replan, and how long they're willing to wait), not an arbitrary default.
- [ ] Who reviews and approves the retrieval benchmark and ingestion evaluation corpus results before a specific embedding model/parser is locked in for production? This shouldn't be an autonomous decision by the build process alone, given how much downstream architecture depends on it.
