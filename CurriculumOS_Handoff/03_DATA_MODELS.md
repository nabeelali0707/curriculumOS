# 03 — Data Models

## 0. Storage choice for the MVP

Use **PostgreSQL** (with the `pgvector` extension for embeddings) as the single datastore for the MVP. The curriculum has graph-shaped relationships, but that does not require a graph database — represent edges as rows and traverse them with recursive CTEs until you've *measured* that traversal is a real bottleneck. Only then consider Neo4j.

Do not stand up a separate vector database (Milvus/Qdrant) for the MVP. `pgvector` in the same Postgres instance is enough at pilot scale and removes an entire service from the deployment.

## 1. Core relational schema

```sql
-- Curriculum graph, represented relationally
curriculum_nodes (
  id, node_type,           -- 'topic' | 'subtopic' | 'objective'
  label, description,
  syllabus_ref,            -- e.g. "BIO.ENZ.03"
  origin,                  -- 'official' | 'teacher_defined' | 'machine_extracted' | 'machine_inferred'
  confidence,              -- 0.0–1.0
  created_at
)

curriculum_edges (
  id, source_node_id, target_node_id,
  edge_type,                -- 'prerequisite' | 'assessed_by' | 'covered_by' | 'part_of'
  confidence,
  origin,
  provenance_id             -- FK -> source_spans, nullable
)

source_documents (
  id, title, doc_type,      -- 'textbook' | 'past_paper' | 'mark_scheme' | 'syllabus' | 'calendar'
  file_path, ingested_at, parser_used, parser_confidence
)

source_spans (
  id, document_id, page,
  block_id, bbox,           -- [x1, y1, x2, y2]
  text, content_hash
)

exam_questions (
  id, document_id, question_ref,   -- e.g. "2024_p2_q5b"
  text, marks, year, paper_ref
)

mark_scheme_entries (
  id, question_id, text, acceptable_terms, marks_awarded
)

question_node_mappings (
  id, question_id, node_id,
  weight,                   -- contribution of this question to this objective, 0.0–1.0
  confidence,
  mapping_method,           -- 'embedding' | 'lexical' | 'llm' | 'human_corrected'
  corrected_by,             -- teacher id, nullable
  created_at
)

teaching_units (
  id, node_id, duration_minutes, splittable,
  minimum_session_minutes, priority, prerequisite_unit_ids
)

academic_calendars (
  id, school_id, term_start, term_end
)

calendar_days (
  id, calendar_id, date, day_type,   -- 'school_day' | 'non_teaching' | 'exam_day'
)

instruction_windows (
  id, calendar_day_id, subject, class_id,
  start_time, end_time, available_minutes, is_available
)

scheduled_units (
  id, unit_id, instruction_window_id,
  scheduled_minutes, status,   -- 'planned' | 'taught' | 'moved' | 'compressed' | 'removed'
  plan_version
)

teacher_corrections (
  id, entity_type, entity_id,   -- what was corrected
  before_value, after_value,
  teacher_id, created_at
)

class_mastery_signals (   -- class-level only, see 09_RISKS_AND_OPEN_QUESTIONS.md
  id, class_id, node_id, status,   -- 'mastered' | 'needs_reinforcement' | 'reteach'
  marked_by, created_at
)
```

## 2. Provenance & claim-verification schema (the trust layer)

Every extracted fact resolves to a span:

```json
{
  "document_id": "bio-textbook-v3",
  "page": 47,
  "block_id": "blk-0231",
  "bbox": [102, 340, 480, 402],
  "text": "Mitosis produces two genetically identical daughter cells.",
  "content_hash": "sha256:6f2c..."
}
```

Every generated instructional claim in a lesson carries its own verification record — this is not optional metadata, it's the core trust mechanism of the product:

```json
{
  "claim": "Mitosis produces two genetically identical daughter cells.",
  "evidence": ["bio-p47-blk-0231"],
  "generation_model": "claude-sonnet-5",
  "verification_model": "claude-sonnet-5",
  "verification_status": "verified",
  "confidence": 0.96
}
```

`verification_status` should be an enum: `verified | unsupported | partially_supported | not_checked`. Anything not `verified` must not silently render in the final lesson — surface it to the teacher instead of hiding it.

## 3. Question → objective mapping (multi-label, not classification)

A single exam question frequently tests multiple objectives with different weights. Never model this as single-label classification.

```json
{
  "question_id": "2024_p2_q5b",
  "objective_mappings": [
    {"objective_id": "BIO.ENZ.03", "weight": 0.55, "confidence": 0.94, "mapping_method": "hybrid"},
    {"objective_id": "BIO.ENZ.06", "weight": 0.45, "confidence": 0.88, "mapping_method": "hybrid"}
  ]
}
```

## 4. Historical assessment emphasis score

Not raw frequency. A topic that appeared often from 2016–2023 may be irrelevant if the syllabus changed in 2025.

```
E(topic) = w1*F + w2*R + w3*M + w4*W + w5*S

F = frequency of appearance across past papers
R = recency (weighted toward recent years)
M = marks allocated
W = current syllabus weighting
S = structural similarity to the current exam specification

weight(year) = e^(-λ * Δyear)     -- decay older papers
```

Call this a **"historical assessment emphasis score"** in all UI and documentation — not "exam prediction" — until there is empirical validation that it actually predicts future emphasis. Past papers should influence prioritization within the syllabus, never override the syllabus specification.

## 5. Teaching unit (solver input)

```json
{
  "unit_id": "BIO.ENZ.04",
  "duration_minutes": 90,
  "splittable": true,
  "minimum_session_minutes": 30,
  "priority": 0.82,
  "prerequisites": ["BIO.CELL.02"]
}
```

The solver operates only on objects shaped like this — never on generated lesson content. Generate lesson materials after a unit has a confirmed calendar slot.

## 6. Confidence & origin — non-negotiable on every relationship

Every row in `curriculum_edges`, `question_node_mappings`, and any machine-derived table must carry both a `confidence` float and an `origin` tag. The teacher workspace UI must visually distinguish `official`/`teacher_defined` data from `machine_extracted`/`machine_inferred` data — never render them identically.
