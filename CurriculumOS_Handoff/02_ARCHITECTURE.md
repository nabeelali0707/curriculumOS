# 02 — Architecture

## System diagram

```
┌─────────────────────────────────────────────────┐
│ 1. SOURCE INGESTION                             │
│ PDF / DOCX / calendar                           │
│ → structured blocks + coordinates + metadata    │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│ 2. PROVENANCE STORE  (first-class, not optional)│
│ document → page → block → span                  │
│ hashes, bounding boxes, extraction confidence   │
└─────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│ 3. CURRICULUM DOMAIN MODEL                      │
│ objectives, topics, prerequisites               │
│ questions, mark schemes, source mappings        │
│ confidence + provenance on every relationship   │
└─────────────────────────────────────────────────┘
          ↓                        ↓
┌───────────────────────┐   ┌─────────────────────────┐
│ 4. RETRIEVAL/GENERATION│   │ 5. PLANNING ENGINE      │
│ hybrid retrieval       │   │ teaching units          │
│ reranking              │   │ hard/medium/soft        │
│ claim ↔ evidence verify│   │ constraints, solver     │
└───────────────────────┘   └─────────────────────────┘
          ↓                        ↓
          └───────────┬────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│ 6. TEACHER WORKSPACE                            │
│ plan · evidence · edits · calendar · replan     │
└─────────────────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────┐
│ 7. OPTIONAL — LEARNING FEEDBACK (post-MVP)      │
│ class-level (not student-level) mastery signal  │
│ → remediation → replanning                       │
└─────────────────────────────────────────────────┘
```

## Layer-by-layer

### 1. Source Ingestion
Turns raw PDFs/DOCX/calendars into structured blocks with page numbers, bounding boxes, and reading order. Must handle: born-digital textbooks, scanned chapters, past-paper PDFs (often multi-column, with diagrams and mark allocations like `[3]`), mark schemes, syllabi, and academic calendar exports (ICS or spreadsheet).

**Design requirement:** the output of this layer is never "flat text." It's structured blocks with coordinates, because the provenance layer depends on being able to point back to an exact location, not just "this document."

### 2. Provenance Store
This is the layer most systems in this category skip, and skipping it is why AI lesson planners hallucinate curriculum codes and citations. Every fact extracted from a source resolves to:

```json
{
  "document_id": "bio-textbook-v3",
  "page": 47,
  "block_id": "blk-0231",
  "bbox": [102, 340, 480, 402],
  "text": "Mitosis produces two genetically identical daughter cells.",
  "content_hash": "sha256:..."
}
```

Anything downstream (curriculum objectives, generated lesson content, question mappings) links to spans in this store, not to raw document IDs. This is what makes "verify this claim" a database query instead of a re-reading exercise.

### 3. Curriculum Domain Model
The structured representation of what's being taught: objectives, subtopics, prerequisites, exam questions, mark scheme entries, and the mappings between them. Every node and edge in this model carries a **confidence score** and an **origin tag** (`official` / `teacher-defined` / `machine-extracted` / `machine-inferred`) — never let a machine-inferred prerequisite look as authoritative as one stated in the official syllabus. See `03_DATA_MODELS.md` for the concrete schema.

### 4. Retrieval / Generation
Hybrid retrieval (lexical + embedding) over the provenance store, feeding a generation pipeline that is **verify-then-render**, not **generate-then-cite**:

```
retrieve evidence
      ↓
generate structured claims
      ↓
claim ↔ evidence verification (separate pass/model)
      ↓
reject unsupported claims
      ↓
render final lesson
```

Each claim in the output carries its own evidence reference and verification status — see the schema in `03_DATA_MODELS.md` §2.

### 5. Planning Engine
Operates on **teaching units**, not finished lessons:

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

The solver places units onto the calendar (itself modeled as available instructional capacity, not just dates — see below). Lesson *content* generation happens only after a unit has a scheduled slot — never generate full lesson material speculatively and then try to fit it in.

**Why this ordering matters:** rescheduling a lightweight unit descriptor is cheap. Rescheduling a fully generated, teacher-edited lesson is expensive and creates resistance to replanning. Keep the solver's inputs small.

### 6. Teacher Workspace
Where a teacher reviews the extracted curriculum structure, corrects question→objective mappings, sets availability, and reviews/triggers replans. Every teacher correction here should be logged and fed back into the mapping layer — this correction history is a real, compounding asset (see `07_TASK_ROADMAP.md`).

### 7. Learning Feedback (post-MVP, explicitly deferred)
Class-level (not student-level) mastery signals feeding remediation and replanning. Kept out of v1 scope — see `09_RISKS_AND_OPEN_QUESTIONS.md` for why.

## Calendar modeling

Don't store the calendar as a flat list of dates. Model it as:

```
AcademicCalendar → Term → SchoolDay → InstructionWindow → Event → AssessmentDeadline → UnavailablePeriod
```

...and derive `available_minutes(subject, class, date)` from that structure. A school day is not a slot — assemblies, labs, and swapped periods all change actual available teaching minutes, and the solver needs that derived capacity number, not raw dates.

## The single most important non-functional requirement

**Minimize plan instability.** When the solver replans after a disruption, heavily penalize unnecessary changes to lessons that were already scheduled (and especially already taught). A mathematically optimal replan that rewrites three months of a term plan after one snow day will be rejected by teachers even if it's "better." The target demo behavior:

> "School closed March 12." → *Replanning...* → "Cell division moved Mar 12→15. Enzymes compressed 3 sessions→2. Low-priority enrichment task removed. Revision block preserved. Exam date unchanged. **7 lessons unchanged, 3 moved, 1 shortened.**"

Build the "minimize churn" constraint in from the start of the planning engine work — don't bolt it on after the solver already works.
