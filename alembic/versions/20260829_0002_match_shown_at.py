"""Pitch 2.0: Match.shown_at для anti-spam / org cooldown.

Revision ID: 20260829_0002
Revises: 20260813_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260829_0002"
down_revision = "20260813_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("matches", "shown_at")
