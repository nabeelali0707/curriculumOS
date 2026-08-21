"""ORM models matching 03_DATA_MODELS.md §1 (core relational schema).

Two additions beyond the doc's literal SQL block, both flagged as gaps by
the build's own research pass and needed for MVP acceptance criteria in
06_MVP_SCOPE_AND_DEMO.md — not silent scope creep, called out here and in
the commit message that introduces them:

  * `claims` / `claim_evidence` — §2 defines the claim-verification JSON
    shape ("every generated instructional claim carries its own
    verification record... this is not optional metadata") but §1's SQL
    block has no table for it. The MVP demo explicitly requires "every
    generated claim carries a verification status, with unverified claims
    visibly flagged" — that needs somewhere to live.
  * `plan_versions` — `scheduled_units.plan_version` (§1) has no owning
    table. The MVP's most important demo scenario is reporting a plan
    diff ("7 lessons unchanged, 3 moved, 1 shortened") between two
    versions; this table anchors that. The diff itself is computed by
    comparing `scheduled_units` rows across two `plan_version` values at
    query time in app/planning/, not pre-stored — no separate diff table.
  * `question_spans` / `mark_scheme_entry_spans` — 07_TASK_ROADMAP.md
    requires the question parser to produce "page attribution", but
    neither `exam_questions` nor `mark_scheme_entries` has any span
    reference. See [QuestionSpan] for why these are join tables.

Everything else is a direct translation of the doc's schema, including
column names.
"""

import uuid
from datetime import date as date_
from datetime import datetime
from datetime import time as time_
from enum import Enum

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.base import Base, CreatedAtMixin, UUIDPk


class NodeType(str, Enum):
    TOPIC = "topic"
    SUBTOPIC = "subtopic"
    OBJECTIVE = "objective"


class Origin(str, Enum):
    OFFICIAL = "official"
    TEACHER_DEFINED = "teacher_defined"
    MACHINE_EXTRACTED = "machine_extracted"
    MACHINE_INFERRED = "machine_inferred"


class EdgeType(str, Enum):
    PREREQUISITE = "prerequisite"
    ASSESSED_BY = "assessed_by"
    COVERED_BY = "covered_by"
    PART_OF = "part_of"


class DocType(str, Enum):
    TEXTBOOK = "textbook"
    PAST_PAPER = "past_paper"
    MARK_SCHEME = "mark_scheme"
    SYLLABUS = "syllabus"
    CALENDAR = "calendar"


class MappingMethod(str, Enum):
    EMBEDDING = "embedding"
    LEXICAL = "lexical"
    LLM = "llm"
    HYBRID = "hybrid"
    HUMAN_CORRECTED = "human_corrected"


class DayType(str, Enum):
    SCHOOL_DAY = "school_day"
    NON_TEACHING = "non_teaching"
    EXAM_DAY = "exam_day"


class ScheduledUnitStatus(str, Enum):
    PLANNED = "planned"
    TAUGHT = "taught"
    MOVED = "moved"
    COMPRESSED = "compressed"
    REMOVED = "removed"


class MasteryStatus(str, Enum):
    MASTERED = "mastered"
    NEEDS_REINFORCEMENT = "needs_reinforcement"
    RETEACH = "reteach"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    PARTIALLY_SUPPORTED = "partially_supported"
    NOT_CHECKED = "not_checked"


def _confidence_column():
    return mapped_column(Float, nullable=False)


class CurriculumNode(UUIDPk, CreatedAtMixin, Base):
    __tablename__ = "curriculum_nodes"

    node_type: Mapped[NodeType] = mapped_column(SAEnum(NodeType, name="node_type"), nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    syllabus_ref: Mapped[str | None] = mapped_column(String, index=True)  # e.g. "BIO.ENZ.03"
    origin: Mapped[Origin] = mapped_column(SAEnum(Origin, name="origin"), nullable=False)
    confidence: Mapped[float] = _confidence_column()

    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_node_confidence"),
    )


class CurriculumEdge(UUIDPk, Base):
    __tablename__ = "curriculum_edges"

    source_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    edge_type: Mapped[EdgeType] = mapped_column(SAEnum(EdgeType, name="edge_type"), nullable=False)
    confidence: Mapped[float] = _confidence_column()
    origin: Mapped[Origin] = mapped_column(SAEnum(Origin, name="origin"), nullable=False)
    # Nullable per 03_DATA_MODELS.md — but only 'official'/'teacher_defined'
    # edges may legitimately lack provenance; anything machine_* must set
    # this. Enforced in app/domain code, not a DB constraint, since it's a
    # cross-column business rule.
    provenance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_spans.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_edge_confidence"),
    )


class SourceDocument(UUIDPk, Base):
    __tablename__ = "source_documents"

    title: Mapped[str] = mapped_column(String, nullable=False)
    doc_type: Mapped[DocType] = mapped_column(SAEnum(DocType, name="doc_type"), nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    ingested_at: Mapped[datetime | None] = mapped_column()
    parser_used: Mapped[str | None] = mapped_column(String)
    parser_confidence: Mapped[float | None] = mapped_column(Float)


class SourceSpan(UUIDPk, Base):
    __tablename__ = "source_spans"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    block_id: Mapped[str] = mapped_column(String, nullable=False)
    bbox: Mapped[list[float]] = mapped_column(ARRAY(Float), nullable=False)  # [x1, y1, x2, y2]
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # sha256 of `text` at extraction time. Purpose: detect drift when a
    # source document is re-ingested (changed hash on the same block_id
    # means anything citing this span needs re-verification), not just
    # dedup. Not enforced anywhere yet — re-ingestion handling is P0
    # ingestion-pipeline work, not schema work.
    content_hash: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("ix_source_spans_document_block", "document_id", "block_id"),)


class ExamQuestion(UUIDPk, Base):
    __tablename__ = "exam_questions"

    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_ref: Mapped[str] = mapped_column(String, nullable=False)  # e.g. "2024_p2_q5b"
    text: Mapped[str] = mapped_column(Text, nullable=False)
    marks: Mapped[int | None] = mapped_column(Integer)
    year: Mapped[int | None] = mapped_column(Integer)
    paper_ref: Mapped[str | None] = mapped_column(String)

    __table_args__ = (UniqueConstraint("document_id", "question_ref", name="uq_question_ref"),)


class MarkSchemeEntry(UUIDPk, Base):
    __tablename__ = "mark_scheme_entries"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    acceptable_terms: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    marks_awarded: Mapped[int | None] = mapped_column(Integer)


class QuestionSpan(Base):
    """Which source spans an exam question was extracted from.

    Not in 03_DATA_MODELS.md §1 — added because 07_TASK_ROADMAP.md requires
    the question parser to produce "marks and page attribution", and
    `exam_questions` has no span reference at all. A join table rather than
    a single FK because one question routinely spans several blocks (stem,
    parts, figure caption), and rather than a bare `page` int because the
    README's ground rule is an actual mechanically-checkable span
    reference, not "source: page 47".
    """

    __tablename__ = "question_spans"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="CASCADE"), primary_key=True
    )
    source_span_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_spans.id", ondelete="CASCADE"), primary_key=True
    )


class MarkSchemeEntrySpan(Base):
    """Span attribution for a mark-scheme entry — same rationale as
    [QuestionSpan], for the mark scheme half of the joint entity.
    """

    __tablename__ = "mark_scheme_entry_spans"

    mark_scheme_entry_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("mark_scheme_entries.id", ondelete="CASCADE"), primary_key=True
    )
    source_span_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_spans.id", ondelete="CASCADE"), primary_key=True
    )


class QuestionNodeMapping(UUIDPk, CreatedAtMixin, Base):
    __tablename__ = "question_node_mappings"

    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Contribution of this question to this objective. Multiple mappings for
    # one question are independent strengths, NOT required to sum to 1.0
    # across a question's mappings (03_DATA_MODELS.md §3 is explicit this is
    # multi-label, not classification — classification-style normalization
    # would misrepresent that).
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = _confidence_column()
    mapping_method: Mapped[MappingMethod] = mapped_column(
        SAEnum(MappingMethod, name="mapping_method"), nullable=False
    )
    corrected_by: Mapped[str | None] = mapped_column(String)  # teacher id, nullable

    __table_args__ = (
        CheckConstraint("weight >= 0.0 AND weight <= 1.0", name="ck_mapping_weight"),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_mapping_confidence"),
    )


class TeachingUnit(UUIDPk, Base):
    __tablename__ = "teaching_units"

    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    splittable: Mapped[bool] = mapped_column(nullable=False, default=False)
    minimum_session_minutes: Mapped[int | None] = mapped_column(Integer)
    priority: Mapped[float] = mapped_column(Float, nullable=False)
    prerequisite_unit_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True))
    )


class AcademicCalendar(UUIDPk, Base):
    __tablename__ = "academic_calendars"

    # Single-tenant MVP: school_id exists for record-keeping (this pilot's
    # school) but is not a tenant-isolation boundary. No row-level security
    # or cross-table school_id scoping — see project decision on deployment
    # model (single-tenant).
    school_id: Mapped[str] = mapped_column(String, nullable=False)
    term_start: Mapped[date_] = mapped_column(nullable=False)
    term_end: Mapped[date_] = mapped_column(nullable=False)


class CalendarDay(UUIDPk, Base):
    __tablename__ = "calendar_days"

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_calendars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date_] = mapped_column(nullable=False)
    day_type: Mapped[DayType] = mapped_column(SAEnum(DayType, name="day_type"), nullable=False)

    __table_args__ = (UniqueConstraint("calendar_id", "date", name="uq_calendar_day"),)


class InstructionWindow(UUIDPk, Base):
    __tablename__ = "instruction_windows"

    calendar_day_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_days.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject: Mapped[str] = mapped_column(String, nullable=False)
    # Which class this window belongs to. Doc doesn't specify how windows
    # for different classes sharing a room/time are reconciled — flagged
    # as an open question in the research pass; not resolved here. This
    # column just records the association; conflict handling is
    # app/planning/ solver logic (constraint), not a schema concern.
    class_id: Mapped[str] = mapped_column(String, nullable=False)
    start_time: Mapped[time_] = mapped_column(nullable=False)
    end_time: Mapped[time_] = mapped_column(nullable=False)
    available_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_available: Mapped[bool] = mapped_column(nullable=False, default=True)

    __table_args__ = (
        Index("ix_instruction_windows_day_subject_class", "calendar_day_id", "subject", "class_id"),
    )


class PlanVersion(UUIDPk, CreatedAtMixin, Base):
    """Not in 03_DATA_MODELS.md §1 — added because `scheduled_units.plan_version`
    needs an owning table and the MVP demo requires reporting what changed
    between two versions. See module docstring.
    """

    __tablename__ = "plan_versions"

    calendar_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_calendars.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="SET NULL")
    )
    # e.g. "initial_plan" | "calendar_disruption" | "teacher_edit"
    trigger_reason: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class ScheduledUnit(UUIDPk, Base):
    __tablename__ = "scheduled_units"

    unit_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("teaching_units.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instruction_window_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("instruction_windows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ScheduledUnitStatus] = mapped_column(
        SAEnum(ScheduledUnitStatus, name="scheduled_unit_status"), nullable=False
    )
    plan_version: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_scheduled_units_plan_unit", "plan_version", "unit_id"),
    )


class TeacherCorrection(UUIDPk, CreatedAtMixin, Base):
    __tablename__ = "teacher_corrections"

    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    before_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    teacher_id: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (Index("ix_teacher_corrections_entity", "entity_type", "entity_id"),)


class ClassMasterySignal(UUIDPk, CreatedAtMixin, Base):
    """Class-level only — see 09_RISKS_AND_OPEN_QUESTIONS.md. No student_id
    anywhere in this table or any other; do not add one in P2/P3 work.
    """

    __tablename__ = "class_mastery_signals"

    class_id: Mapped[str] = mapped_column(String, nullable=False)
    node_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[MasteryStatus] = mapped_column(
        SAEnum(MasteryStatus, name="mastery_status"), nullable=False
    )
    marked_by: Mapped[str] = mapped_column(String, nullable=False)  # teacher id


class Claim(UUIDPk, CreatedAtMixin, Base):
    """Not in 03_DATA_MODELS.md §1 — the doc's §2 defines this JSON shape
    and calls it "not optional metadata," but no relational table backs it.
    Added here; see module docstring. `scheduled_unit_id` is nullable
    because claim generation is P2 (lesson generation) work happening well
    after this schema exists — the FK target is ready, nothing populates
    it yet.
    """

    __tablename__ = "claims"

    scheduled_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("scheduled_units.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    generation_model: Mapped[str] = mapped_column(String, nullable=False)
    verification_model: Mapped[str] = mapped_column(String, nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        SAEnum(VerificationStatus, name="verification_status"), nullable=False
    )
    confidence: Mapped[float] = _confidence_column()

    __table_args__ = (
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_claim_confidence"),
        # generation_model and verification_model must differ — mirrors the
        # provider-router-level rule in app/providers/llm/__init__.py. Not a
        # DB constraint (both are free-text model names, not an enum), just
        # documented here; enforce it at the call site that inserts claims.
    )


class ClaimEvidence(Base):
    """Join table: a claim's `evidence` array (§2) as rows rather than an
    array column, so each evidence link is independently queryable (e.g.
    "which claims cite this span") without unpacking an array.
    """

    __tablename__ = "claim_evidence"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True
    )
    source_span_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_spans.id", ondelete="CASCADE"), primary_key=True
    )
