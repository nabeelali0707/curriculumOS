"""Span attribution for exam questions and mark-scheme entries.

07_TASK_ROADMAP.md requires the question parser to produce "marks and
page attribution", but 03_DATA_MODELS.md §1 gives neither table a span
reference. Join tables (not a single FK) because one question spans
several blocks; span-level (not a `page` int) because the README's ground
rule is a mechanically-checkable reference, not "source: page 47".

Like 0001, NOT verified against a live database — no Docker in the build
environment. Run `alembic upgrade head` before trusting it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_spans",
        sa.Column(
            "question_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("exam_questions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_span_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("source_spans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_question_spans_source_span_id", "question_spans", ["source_span_id"])

    op.create_table(
        "mark_scheme_entry_spans",
        sa.Column(
            "mark_scheme_entry_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("mark_scheme_entries.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_span_id",
            pg.UUID(as_uuid=True),
            sa.ForeignKey("source_spans.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "ix_mark_scheme_entry_spans_source_span_id",
        "mark_scheme_entry_spans",
        ["source_span_id"],
    )


def downgrade() -> None:
    op.drop_table("mark_scheme_entry_spans")
    op.drop_table("question_spans")
