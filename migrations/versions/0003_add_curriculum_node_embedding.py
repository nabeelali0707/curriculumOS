"""Add pgvector embedding column to curriculum nodes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-21
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "curriculum_nodes",
        sa.Column("embedding", Vector(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("curriculum_nodes", "embedding")
