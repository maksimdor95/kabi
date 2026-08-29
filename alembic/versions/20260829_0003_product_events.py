"""P1: product_events для воронки / impressions / реакций.

Revision ID: 20260829_0003
Revises: 20260829_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "20260829_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("props", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_product_events_profile_id", "product_events", ["profile_id"], unique=False
    )
    op.create_index("ix_product_events_name", "product_events", ["name"], unique=False)
    op.create_index(
        "ix_product_events_created_at", "product_events", ["created_at"], unique=False
    )
    op.create_index(
        "ix_product_events_profile_created",
        "product_events",
        ["profile_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_product_events_profile_created", table_name="product_events")
    op.drop_index("ix_product_events_created_at", table_name="product_events")
    op.drop_index("ix_product_events_name", table_name="product_events")
    op.drop_index("ix_product_events_profile_id", table_name="product_events")
    op.drop_table("product_events")
