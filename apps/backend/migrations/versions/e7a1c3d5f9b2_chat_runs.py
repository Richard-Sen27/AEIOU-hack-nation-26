"""chat_runs: unfinished Dr. Wu turns with their latest LangGraph checkpoint (user table)

Revision ID: e7a1c3d5f9b2
Revises: 9c4e2a7b5d13
Create Date: 2026-10-04 23:00:00.000000

One row per turn that is still running. It holds the latest checkpoint of the turn's graph
(redacted message, steps, extraction results, draft or checked reply: the same class of content
as chat_messages; never raw text from before redaction, the profile or tokens). The row is
deleted in the same transaction that stores the reply or the failed turn, which prunes the
checkpoint. Health data under the `health_data` consent: it cascades from chat_sessions (session
deletion and consent withdrawal delete sessions) and from users (account deletion).

Owner-only (FORCE row-level security, the same policy as every other user table). The unique
session_id allows at most one active run per session.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c3d5f9b2"
down_revision: str | Sequence[str] | None = "9c4e2a7b5d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_USER = "nullif(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "chat_runs",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_message_id", sa.UUID(), nullable=False),
        sa.Column("worker", sa.Text(), nullable=False),
        sa.Column("checkpoint_id", sa.Text(), nullable=True),
        sa.Column("checkpoint_type", sa.Text(), nullable=True),
        sa.Column("checkpoint", sa.LargeBinary(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("ix_chat_runs_user_id", "chat_runs", ["user_id"], unique=False)
    op.create_index(
        "ix_chat_runs_user_message_id", "chat_runs", ["user_message_id"], unique=False
    )
    op.execute(
        "ALTER TABLE chat_runs ENABLE ROW LEVEL SECURITY;\n"
        "ALTER TABLE chat_runs FORCE ROW LEVEL SECURITY;\n"
        "CREATE POLICY chat_runs_owner ON chat_runs"
        f" USING (user_id = {APP_USER}) WITH CHECK (user_id = {APP_USER});\n"
        "GRANT SELECT, INSERT, UPDATE, DELETE ON chat_runs TO atlas_app;"
    )


def downgrade() -> None:
    op.drop_index("ix_chat_runs_user_message_id", table_name="chat_runs")
    op.drop_index("ix_chat_runs_user_id", table_name="chat_runs")
    op.drop_table("chat_runs")
