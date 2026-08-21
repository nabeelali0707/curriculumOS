# 04 — Multi-Provider Strategy & Fallbacks

## Why this document exists

Every external dependency in this system — LLM inference, embeddings, document parsing, constraint solving — is a third-party service or library that can go down, get rate-limited, change pricing, or get deprecated (see: Timefold's Python solver being discontinued mid-2026). **No single-provider hard dependency should exist anywhere in the codebase.** Every capability below must be built behind an internal abstraction interface, with a configured provider priority list and an explicit fallback policy — even if only one provider is wired up at first.

**Build order:** abstraction interface → one working provider behind it → fallback chain. Don't build the fallback chain before the abstraction interface exists, and don't wire multiple providers before the interface is stable.

---

## 1. LLM Inference (generation + verification)

### Why multi-provider matters here specifically
This system makes two *different kinds* of LLM calls with different risk profiles:
- **Generation** (drafting lesson content, drafting question→objective mapping candidates) — moderate risk if wrong, teacher reviews it.
- **Verification** (checking whether a generated claim is actually supported by a retrieved source span) — high risk if wrong, because this is the trust mechanism of the whole product.

**Use a different model (or at minimum a fresh, independent call) for verification than for generation**, to avoid a model rubber-stamping its own output. This is a correctness requirement, not just a resilience one.

### Provider abstraction
Route all LLM calls through a single internal interface (`llm_client.complete(task, prompt, ...)`), backed by a unified routing layer (e.g. LiteLLM, or a thin custom wrapper) so that swapping providers is a config change, not a code change.

### Suggested provider priority (verify current pricing/limits before hardcoding — this moves fast)

| Role | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Generation | Anthropic Claude (API) | OpenAI GPT (API) | Self-hosted open-weight model (e.g. via Together/Fireworks/Groq) |
| Verification | A *different* provider/model than whichever generated the claim | Rotate to another configured provider | Fall back to a stricter rules-based span-matching check (lexical overlap threshold) rather than skipping verification entirely |
| Question→objective mapping (LLM signal only — see §4) | Same as generation | Same fallback chain | — |

### Fallback policy
- **Retry with backoff** (e.g. 3 attempts, exponential backoff) on transient errors (5xx, timeouts, rate limits) before failing over to the next provider.
- **Circuit breaker per provider**: after N consecutive failures, mark a provider "down" for a cooldown window and skip straight to the next one, rather than retrying a dead provider on every request.
- **Never silently fall back for verification without flagging it.** If verification had to fall back to a weaker method (e.g. lexical matching instead of a second LLM pass), the resulting claim's `verification_status` should reflect reduced confidence — don't let a degraded verification path produce a `verified` status indistinguishable from a full LLM verification pass.
- **Log which provider served every request** (for cost tracking, quality monitoring, and debugging inconsistent outputs).

### Cost/latency note
Generation and verification are the most expensive line items in this system's unit economics. Track cost-per-lesson and cost-per-verified-claim from day one so provider choice can be revisited with real data, not vibes.

---

## 2. Embeddings

### The critical constraint fallback logic must respect
**Embeddings from different models are not interchangeable within the same vector index.** Unlike LLM text generation, you cannot silently fail over mid-request from one embedding model to another and keep using the same similarity index — the vector spaces aren't compatible. Design around this explicitly:

- Fallback for embeddings means **provider-level failover with a pre-built parallel index**, not per-call fallback. If you want resilience, maintain a secondary index built with the fallback model, kept in sync in the background, and switch the *active* index wholesale if the primary provider becomes unavailable — don't try to mix vectors from two models in one similarity search.
- For most teams at pilot scale, this is over-engineering for v1. **Recommendation: pick one embedding provider for the MVP, run it locally or via a stable hosted API, and treat "swap embedding models" as a re-indexing job, not a runtime fallback.** Only build the parallel-index failover once retrieval is business-critical enough to justify it.

### Suggested provider priority

| Priority | Model | Notes |
|---|---|---|
| Primary | Qwen3-Embedding-8B | Strong multilingual retrieval, 32K context. Verify current MTEB standing before relying on any specific ranking claim — leaderboards move. |
| Alternative (pick via benchmark, not by default) | BGE-M3 | MIT license, dense+sparse+multi-vector in one model, good production track record. |
| Fallback (hosted, zero self-hosting) | A commercial hosted embedding API (e.g. OpenAI or Google's current embedding offering) | Use only as an emergency fallback path or for teams that don't want to self-host inference — verify current pricing/limits before depending on it. |
| Do not use for general documents | ~~Nomic Embed Text v2~~ | Confirmed 512-token hard truncation limit — unsuitable for textbook-chapter-length chunks. Only viable for single-question/short-span embeddings if ever used at all. |

### Build requirement
Before locking in a provider, build a small CurriculumOS-specific retrieval benchmark (~200 query → expected-source-span pairs drawn from real ingested textbooks/past papers) and evaluate Recall@5/10, MRR, and citation-source recall. Do not select purely from public MTEB leaderboard rank.

---

## 3. Document Parsing / Ingestion

### Why fallback matters here
Real-world source documents vary wildly in quality: born-digital textbook PDFs, scanned chapters, multi-column past papers, tables, diagrams, equations. No single parser handles all of these equally well.

### Suggested routing strategy (route by document characteristics, not a fixed priority order)

| Document type | Primary parser | Fallback |
|---|---|---|
| Born-digital PDF (has text layer) | Docling (skips OCR, fastest + most accurate for this case) | Marker |
| Scanned / image-only pages | Docling with OCR enabled, or Marker | A dedicated OCR-first pipeline (e.g. Tesseract + layout model), or a managed OCR API as a last resort |
| Complex multi-column past papers / mark schemes | Marker (strong layout handling) or Docling | Managed API (e.g. LlamaParse) if self-hosted parsers score poorly in your benchmark on this document type |
| Heavily malformed / low-confidence output from primary | — | Route to a managed parsing API and flag the document for manual review rather than silently accepting low-confidence extraction |

### Confidence-gated fallback
Every parse should produce a `parser_confidence` score (stored on `source_documents`, see `03_DATA_MODELS.md`). If confidence falls below a threshold, automatically retry with the fallback parser before accepting the result — don't require a human to notice a bad parse after the fact.

### Build requirement before committing to a primary parser
Assemble a small, deliberately ugly evaluation corpus (a handful of born-digital textbooks, scanned chapters, past papers, mark schemes, tables, multi-column layouts, and equation-heavy pages) and score candidate parsers on what actually matters for this product: *can it reliably recover "Question 4(c)(ii)", its marks, its page, and its associated diagram* — not generic markdown quality.

---

## 4. Question → Curriculum-Objective Mapping

This isn't a single "provider," but it should be built as an **ensemble of signals with a fallback/consensus policy**, because no single method is reliable enough alone:

```
final_mapping = combine(
    embedding_similarity_signal,
    lexical_keyword_retrieval_signal,
    syllabus_terminology_match_signal,
    llm_classification_signal,          # uses the LLM provider chain from §1
    human_correction_signal              # highest-trust, always wins when present
)
```

- If the LLM classification provider is unavailable, fall back to the non-LLM signals (embedding + lexical + terminology matching) and lower the resulting `confidence` score accordingly — don't block the pipeline entirely on LLM availability.
- Every teacher correction should be logged (`teacher_corrections` table) and weighted as ground truth going forward. Once ~500+ corrected mappings exist, consider training a lightweight classifier on this data as an additional ensemble signal — this is a valuable, defensible dataset over time, not just a fallback mechanism.

---

## 5. Constraint Solver (Scheduling / Replanning)

### Current landscape (verify before building — this space moves fast)
- **OR-Tools CP-SAT (Google)** — Python-native, actively maintained, no JVM dependency. **Primary pick for this project.**
- **Timefold Solver** — do not depend on this. Its official Python solver (JPype-bridged to a JVM) was discontinued in 2026; the vendor is refocused on Java/Kotlin. A community fork (SolverForge) is rewriting a native-Rust Python solver but it is still alpha/beta as of this writing. Too much platform risk for a core dependency right now — re-evaluate only if it reaches a stable release with a track record.
- **PyJobShop** — a friendlier modeling layer over OR-Tools CP-SAT, usable if raw CP-SAT modeling is too low-level, but lightly maintained — verify it still meets your needs before depending on it, and be prepared to drop straight to raw CP-SAT if it stalls.

### Fallback policy specific to the solver
Unlike LLM/embedding/parsing providers, there generally is not a meaningfully different "alternative solver" to fail over to mid-request — solver swaps are an engineering decision, not a runtime routing decision. Instead, build resilience into the solver invocation itself:

- **Time-box every solve.** If CP-SAT doesn't reach a feasible solution within a configured time limit, fall back to a simpler greedy/heuristic scheduler that guarantees *a* feasible (if suboptimal) plan rather than returning no plan at all.
- **Always validate hard constraints post-solve** before presenting a plan to a teacher — a solver bug or timeout-truncated solution should never silently violate a hard constraint (e.g., scheduling a lesson on a non-teaching day).
- Track solver library health/maintenance status as an ongoing risk item (see `09_RISKS_AND_OPEN_QUESTIONS.md`), not a one-time decision.

---

## 6. Summary table — capability → provider chain

| Capability | Primary | Fallback(s) | Fallback mechanism |
|---|---|---|---|
| LLM generation | Anthropic Claude | OpenAI GPT → self-hosted open-weight | Retry/backoff → circuit breaker → next provider |
| LLM verification | Different provider than generation | Rotate providers → lexical-match degraded mode | Same as above, but flag reduced confidence on degraded mode |
| Embeddings | Qwen3-Embedding-8B (pending benchmark) | BGE-M3 → hosted commercial API | Provider-level failover with parallel pre-built index, not per-call |
| Document parsing | Docling (born-digital) | Marker → managed API (low-confidence docs) | Confidence-gated auto-retry with next parser |
| Question→objective mapping | LLM + embedding + lexical ensemble | Non-LLM signals only if LLM provider down | Confidence-weighted combination, never single-point-of-failure |
| Constraint solver | OR-Tools CP-SAT | Greedy heuristic (time-boxed) | Time-box primary solve, fall back to feasible-not-optimal plan |

## 7. Configuration, not code, should define provider choice

All of the above should be driven by a config file (YAML/JSON/env vars), not hardcoded provider names scattered through the codebase:

```yaml
providers:
  llm:
    generation:
      priority: [anthropic, openai, self_hosted]
    verification:
      priority: [openai, anthropic]   # deliberately different default order than generation
  embeddings:
    active: qwen3-embedding-8b
    fallback: bge-m3
  parsing:
    born_digital: docling
    scanned: docling_ocr
    low_confidence_fallback: managed_api
  solver:
    primary: ortools_cpsat
    time_limit_seconds: 30
    fallback: greedy_heuristic
```

This makes provider swaps, A/B testing, and cost optimization a config change reviewable in a PR — not a code refactor.
