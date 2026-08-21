"""Initial schema — 03_DATA_MODELS.md §1 plus claims/plan_versions
(see app/domain/models.py module docstring for why those two were added).

NOT verified against a live database in this environment (Docker Desktop
wasn't running here). Run `alembic upgrade head` against the
docker-compose Postgres and fix anything that doesn't apply cleanly
before relying on this.

Revision ID: 0001
Revises:
Create Date: 2026-08-21

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _uuid_pk():
    return sa.Column(
        "id", pg.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')  # gen_random_uuid()
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')  # pgvector, for future embedding columns

    node_type = pg.ENUM("topic", "subtopic", "objective", name="node_type")
    origin = pg.ENUM(
        "official", "teacher_defined", "machine_extracted", "machine_inferred", name="origin"
    )
    edge_type = pg.ENUM(
        "prerequisite", "assessed_by", "covered_by", "part_of", name="edge_type"
    )
    doc_type = pg.ENUM(
        "textbook", "past_paper", "mark_scheme", "syllabus", "calendar", name="doc_type"
    )
    mapping_method = pg.ENUM(
        "embedding", "lexical", "llm", "hybrid", "human_corrected", name="mapping_method"
    )
    day_type = pg.ENUM("school_day", "non_teaching", "exam_day", name="day_type")
    scheduled_unit_status = pg.ENUM(
        "planned", "taught", "moved", "compressed", "removed", name="scheduled_unit_status"
    )
    mastery_status = pg.ENUM(
        "mastered", "needs_reinforcement", "reteach", name="mastery_status"
    )
    verification_status = pg.ENUM(
        "verified", "unsupported", "partially_supported", "not_checked", name="verification_status"
    )

    bind = op.get_bind()
    for enum in (
        node_type, origin, edge_type, doc_type, mapping_method,
        day_type, scheduled_unit_status, mastery_status, verification_status,
    ):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "source_documents",
        _uuid_pk(),
        sa.Column("title", sa.String, nullable=False),
        sa.Column("doc_type", doc_type, nullable=False),
        sa.Column("file_path", sa.String, nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True)),
        sa.Column("parser_used", sa.String),
        sa.Column("parser_confidence", sa.Float),
    )

    op.create_table(
        "source_spans",
        _uuid_pk(),
        sa.Column(
            "document_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("page", sa.Integer, nullable=False),
        sa.Column("block_id", sa.String, nullable=False),
        sa.Column("bbox", pg.ARRAY(sa.Float), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String, nullable=False),
    )
    op.create_index("ix_source_spans_document_id", "source_spans", ["document_id"])
    op.create_index(
        "ix_source_spans_document_block", "source_spans", ["document_id", "block_id"]
    )

    op.create_table(
        "curriculum_nodes",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("node_type", node_type, nullable=False),
        sa.Column("label", sa.String, nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("syllabus_ref", sa.String),
        sa.Column("origin", origin, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_node_confidence"),
    )
    op.create_index("ix_curriculum_nodes_syllabus_ref", "curriculum_nodes", ["syllabus_ref"])

    op.create_table(
        "curriculum_edges",
        _uuid_pk(),
        sa.Column(
            "source_node_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "target_node_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("edge_type", edge_type, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("origin", origin, nullable=False),
        sa.Column(
            "provenance_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("source_spans.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_edge_confidence"),
    )
    op.create_index("ix_curriculum_edges_source_node_id", "curriculum_edges", ["source_node_id"])
    op.create_index("ix_curriculum_edges_target_node_id", "curriculum_edges", ["target_node_id"])

    op.create_table(
        "exam_questions",
        _uuid_pk(),
        sa.Column(
            "document_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("question_ref", sa.String, nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("marks", sa.Integer),
        sa.Column("year", sa.Integer),
        sa.Column("paper_ref", sa.String),
        sa.UniqueConstraint("document_id", "question_ref", name="uq_question_ref"),
    )
    op.create_index("ix_exam_questions_document_id", "exam_questions", ["document_id"])

    op.create_table(
        "mark_scheme_entries",
        _uuid_pk(),
        sa.Column(
            "question_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("acceptable_terms", pg.ARRAY(sa.String)),
        sa.Column("marks_awarded", sa.Integer),
    )
    op.create_index("ix_mark_scheme_entries_question_id", "mark_scheme_entries", ["question_id"])

    op.create_table(
        "question_node_mappings",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "question_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("exam_questions.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "node_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("mapping_method", mapping_method, nullable=False),
        sa.Column("corrected_by", sa.String),
        sa.CheckConstraint("weight >= 0.0 AND weight <= 1.0", name="ck_mapping_weight"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_mapping_confidence"),
    )
    op.create_index("ix_question_node_mappings_question_id", "question_node_mappings", ["question_id"])
    op.create_index("ix_question_node_mappings_node_id", "question_node_mappings", ["node_id"])

    op.create_table(
        "teaching_units",
        _uuid_pk(),
        sa.Column(
            "node_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("splittable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("minimum_session_minutes", sa.Integer),
        sa.Column("priority", sa.Float, nullable=False),
        sa.Column("prerequisite_unit_ids", pg.ARRAY(pg.UUID(as_uuid=True))),
    )
    op.create_index("ix_teaching_units_node_id", "teaching_units", ["node_id"])

    op.create_table(
        "academic_calendars",
        _uuid_pk(),
        sa.Column("school_id", sa.String, nullable=False),
        sa.Column("term_start", sa.Date, nullable=False),
        sa.Column("term_end", sa.Date, nullable=False),
    )

    op.create_table(
        "calendar_days",
        _uuid_pk(),
        sa.Column(
            "calendar_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("academic_calendars.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("day_type", day_type, nullable=False),
        sa.UniqueConstraint("calendar_id", "date", name="uq_calendar_day"),
    )
    op.create_index("ix_calendar_days_calendar_id", "calendar_days", ["calendar_id"])

    op.create_table(
        "instruction_windows",
        _uuid_pk(),
        sa.Column(
            "calendar_day_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("calendar_days.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("subject", sa.String, nullable=False),
        sa.Column("class_id", sa.String, nullable=False),
        sa.Column("start_time", sa.Time, nullable=False),
        sa.Column("end_time", sa.Time, nullable=False),
        sa.Column("available_minutes", sa.Integer, nullable=False),
        sa.Column("is_available", sa.Boolean, nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_instruction_windows_calendar_day_id", "instruction_windows", ["calendar_day_id"])
    op.create_index(
        "ix_instruction_windows_day_subject_class",
        "instruction_windows", ["calendar_day_id", "subject", "class_id"],
    )

    op.create_table(
        "plan_versions",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "calendar_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("academic_calendars.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "parent_version_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("plan_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("trigger_reason", sa.String, nullable=False),
        sa.Column("notes", sa.Text),
    )
    op.create_index("ix_plan_versions_calendar_id", "plan_versions", ["calendar_id"])

    op.create_table(
        "scheduled_units",
        _uuid_pk(),
        sa.Column(
            "unit_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("teaching_units.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "instruction_window_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("instruction_windows.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("scheduled_minutes", sa.Integer, nullable=False),
        sa.Column("status", scheduled_unit_status, nullable=False),
        sa.Column(
            "plan_version", pg.UUID(as_uuid=True),
            sa.ForeignKey("plan_versions.id", ondelete="CASCADE"), nullable=False,
        ),
    )
    op.create_index("ix_scheduled_units_unit_id", "scheduled_units", ["unit_id"])
    op.create_index(
        "ix_scheduled_units_instruction_window_id", "scheduled_units", ["instruction_window_id"]
    )
    op.create_index("ix_scheduled_units_plan_version", "scheduled_units", ["plan_version"])
    op.create_index("ix_scheduled_units_plan_unit", "scheduled_units", ["plan_version", "unit_id"])

    op.create_table(
        "teacher_corrections",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("entity_type", sa.String, nullable=False),
        sa.Column("entity_id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("before_value", pg.JSONB, nullable=False),
        sa.Column("after_value", pg.JSONB, nullable=False),
        sa.Column("teacher_id", sa.String, nullable=False),
    )
    op.create_index(
        "ix_teacher_corrections_entity", "teacher_corrections", ["entity_type", "entity_id"]
    )

    op.create_table(
        "class_mastery_signals",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("class_id", sa.String, nullable=False),
        sa.Column(
            "node_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("curriculum_nodes.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("status", mastery_status, nullable=False),
        sa.Column("marked_by", sa.String, nullable=False),
    )
    op.create_index("ix_class_mastery_signals_node_id", "class_mastery_signals", ["node_id"])

    op.create_table(
        "claims",
        _uuid_pk(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "scheduled_unit_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("scheduled_units.id", ondelete="CASCADE"),
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("generation_model", sa.String, nullable=False),
        sa.Column("verification_model", sa.String, nullable=False),
        sa.Column("verification_status", verification_status, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_claim_confidence"),
    )
    op.create_index("ix_claims_scheduled_unit_id", "claims", ["scheduled_unit_id"])

    op.create_table(
        "claim_evidence",
        sa.Column(
            "claim_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column(
            "source_span_id", pg.UUID(as_uuid=True),
            sa.ForeignKey("source_spans.id", ondelete="CASCADE"), primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("claim_evidence")
    op.drop_table("claims")
    op.drop_table("class_mastery_signals")
    op.drop_table("teacher_corrections")
    op.drop_table("scheduled_units")
    op.drop_table("plan_versions")
    op.drop_table("instruction_windows")
    op.drop_table("calendar_days")
    op.drop_table("academic_calendars")
    op.drop_table("teaching_units")
    op.drop_table("question_node_mappings")
    op.drop_table("mark_scheme_entries")
    op.drop_table("exam_questions")
    op.drop_table("curriculum_edges")
    op.drop_table("curriculum_nodes")
    op.drop_table("source_spans")
    op.drop_table("source_documents")

    bind = op.get_bind()
    for name in (
        "verification_status", "mastery_status", "scheduled_unit_status", "day_type",
        "mapping_method", "doc_type", "edge_type", "origin", "node_type",
    ):
        pg.ENUM(name=name).drop(bind, checkfirst=True)
