"""Baseline schema (M10) — mirrors app/db/models.py at M9.

Revision ID: 20260813_0001
Revises:
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260813_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = 256


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)

    op.create_table(
        "opportunities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("org", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("remote", sa.Boolean(), nullable=False),
        sa.Column("salary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_opportunities_type"), "opportunities", ["type"], unique=False)
    op.create_index(op.f("ix_opportunities_source"), "opportunities", ["source"], unique=False)

    op.create_table(
        "profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("experience", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("languages", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("work_mode", sa.String(), nullable=True),
        sa.Column("salary_expectation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("priorities", sa.String(), nullable=False),
        sa.Column("job_search_status", sa.String(), nullable=False),
        sa.Column("hard_nos", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("availability", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("goals", sa.Text(), nullable=True),
        sa.Column("speaking_topics", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("enrichment_consent", sa.Boolean(), nullable=False),
        sa.Column("source_links", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_cv_ref", sa.String(), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("ready_for_matching", sa.Boolean(), nullable=False),
        sa.Column("onboarding_step", sa.Integer(), nullable=False),
        sa.Column("digest_schedule", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_digest_at", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_matches_profile_id"), "matches", ["profile_id"], unique=False)
    op.create_index(op.f("ix_matches_status"), "matches", ["status"], unique=False)

    op.create_table(
        "deadline_reminder_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("profile_id", sa.Uuid(), nullable=False),
        sa.Column("opportunity_id", sa.Uuid(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_deadline_reminder_logs_profile_id"),
        "deadline_reminder_logs",
        ["profile_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_deadline_reminder_logs_opportunity_id"),
        "deadline_reminder_logs",
        ["opportunity_id"],
        unique=False,
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("reaction", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_index(
        op.f("ix_deadline_reminder_logs_opportunity_id"),
        table_name="deadline_reminder_logs",
    )
    op.drop_index(
        op.f("ix_deadline_reminder_logs_profile_id"),
        table_name="deadline_reminder_logs",
    )
    op.drop_table("deadline_reminder_logs")
    op.drop_index(op.f("ix_matches_status"), table_name="matches")
    op.drop_index(op.f("ix_matches_profile_id"), table_name="matches")
    op.drop_table("matches")
    op.drop_table("profiles")
    op.drop_index(op.f("ix_opportunities_source"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_type"), table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_table("users")
