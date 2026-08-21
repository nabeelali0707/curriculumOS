# 05 — Tech Stack

> Verify all versions, pricing, and licensing terms against current provider docs before hardcoding — this list reflects research as of August 2026, and this space moves fast.

## Core application
- **Language:** Python
- **API framework:** FastAPI
- **Background jobs:** a task queue worker (e.g. Celery or an equivalent) for ingestion and solver jobs that shouldn't block request/response cycles
- **Object storage:** for original uploaded documents (S3-compatible)

## Data layer
- **Primary datastore:** PostgreSQL
- **Vector search:** `pgvector` extension on the same Postgres instance for the MVP — do not stand up a dedicated vector DB (Milvus/Qdrant) until you've measured a real need for it
- **Migration path only, not MVP:** Neo4j (only if graph traversal becomes a measured bottleneck), Qdrant/Milvus (only if pgvector's scale/latency becomes a measured bottleneck)

## Document ingestion
| Tool | License | Role |
|---|---|---|
| Docling (IBM / LF AI & Data Foundation) | MIT (codebase); `Granite-Docling-258M` model weights separately Apache-2.0 | Primary parser — born-digital PDFs, table extraction via TableFormer, preserves hierarchy via `DoclingDocument` |
| Marker | Apache-2.0 | Fallback parser, stronger on some multi-column/scanned layouts, optional LLM cleanup pass |
| RAGFlow | — | Reference implementation only — study its citation-backed chunking approach, don't necessarily adopt the platform |

Route by document type and parser confidence — see `04_PROVIDER_STRATEGY.md` §3.

## Embeddings
| Model | License | Role |
|---|---|---|
| Qwen3-Embedding-8B | Apache-2.0 | Primary candidate — validate against your own retrieval benchmark before committing |
| BGE-M3 | MIT | Alternative candidate — dense+sparse+multi-vector, 8,192-token context |
| ~~Nomic Embed Text v2~~ | — | Excluded — 512-token hard truncation, unsuitable for document-length chunks |

## LLM inference
- **Primary:** Anthropic Claude API
- **Fallback:** OpenAI API
- **Tertiary/self-hosted option:** open-weight model via a hosted inference provider (Together/Fireworks/Groq) or self-hosted
- Route all calls through a single internal abstraction (see `04_PROVIDER_STRATEGY.md` §1) — consider LiteLLM or an equivalent unified client library rather than hand-rolling per-provider clients.

## Constraint solving / scheduling
- **Primary:** OR-Tools CP-SAT (Google) — Python-native, no JVM dependency
- **Optional convenience wrapper:** PyJobShop (verify maintenance status before depending on it)
- **Explicitly excluded:** Timefold Solver — official Python support discontinued in 2026; community fork (SolverForge) not yet production-stable

## RAG orchestration
- **Haystack** — introduce once you outgrow raw pgvector hybrid queries; not required for the MVP

## Why not Mojo
Mojo went fully open source (Apache 2.0) on Aug 18, 2026, but it targets GPU/accelerator-level systems performance. This system is bottlenecked by LLM API round-trips, document parsing I/O, and solver execution — never by Python interpreter overhead. The Python ecosystem (FastAPI, sentence-transformers, OR-Tools, Docling) is mature; Mojo's is not, for this kind of application. Stick with Python.

## MVP-only stack (do not exceed this without a measured reason)
```
Python + FastAPI
PostgreSQL + pgvector
Docling (+ Marker as fallback)
One embedding model (chosen via benchmark)
OR-Tools CP-SAT
One LLM provider wired through the abstraction layer (fallback provider configured but not necessarily load-tested yet)
Object storage
Background task worker
```
