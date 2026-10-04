"""follows and notifications (user tables) for in-app updates about followed diseases

Revision ID: 5b8e1f3a7c92
Revises: 0762472c35ce
Create Date: 2026-10-04 21:00:00.000000

follows: the diseases a user follows (atlas MONDO ids, at most 50, enforced by the API). Health
data, held under the `health_data` consent: withdrawing it deletes follows and notifications.

notifications: filled lazily inside the user's own transaction from graph_changes and the
user's follows; no text is stored (labels are resolved from the graph when read). One row per
dedupe key and user. Purged after 90 days at read time.

Both are owner-only (FORCE row-level security, the same policy as every other user table) and
cascade from users. Two indexes on the graph table graph_changes keep the lazy fill cheap: the
join by disease and the newest-change lookup the unread count polls.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b8e1f3a7c92"
down_revision: str | Sequence[str] | None = "0762472c35ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_USER = "nullif(current_setting('app.user_id', true), '')::uuid"
TABLES = ("follows", "notifications")


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("since_version", sa.Text(), nullable=True),
        sa.CheckConstraint("node_id ~ '^MONDO:[0-9]{7}$'", name="ck_follows_mondo_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "node_id"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.Text(), nullable=False),
        sa.Column("subject_node_id", sa.Text(), nullable=True),
        sa.Column("data_version", sa.Text(), nullable=True),
        sa.Column("dedupe_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_dedupe"),
    )
    op.create_index(
        "ix_notifications_user_created", "notifications", ["user_id", "created_at"], unique=False
    )
    op.create_index(
        "ix_graph_changes_disease", "graph_changes", ["disease_id", "created_at"], unique=False
    )
    op.create_index("ix_graph_changes_created_at", "graph_changes", ["created_at"], unique=False)
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
            f"CREATE POLICY {table}_owner ON {table}"
            f" USING (user_id = {APP_USER}) WITH CHECK (user_id = {APP_USER});\n"
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO atlas_app;"
        )


def downgrade() -> None:
    op.drop_index("ix_graph_changes_created_at", table_name="graph_changes")
    op.drop_index("ix_graph_changes_disease", table_name="graph_changes")
    op.drop_index("ix_notifications_user_created", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("follows")
