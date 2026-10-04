"""hpo_terms (HPO term table for symptom matching) and graph_changes (what a load added)

Revision ID: 0762472c35ce
Revises: 22c0044931d2
Create Date: 2026-10-04 19:00:00.000000

One row per HPO term under HP:0000118 plus HP:0000118 itself (about 20,000), including classes
that are not graph nodes: label, synonyms, direct is_a parents and the corpus information
content (null when the term and its descendants annotate nothing). A graph table: the pipeline
fills it in the same transaction as the other graph tables, the API only reads it (loaded into
memory at startup next to the graph). No row-level security, like the other graph tables.

graph_changes: one row per node (and edge) a pipeline load added to a disease's neighbourhood,
so in-app notifications can later say what changed between data versions. Written by the
pipeline in the load transaction, read-only for the application; nothing reads it yet.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0762472c35ce"
down_revision: str | Sequence[str] | None = "22c0044931d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_SQL = """
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON hpo_terms TO atlas_pipeline;
GRANT SELECT ON hpo_terms TO atlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON graph_changes TO atlas_pipeline;
GRANT SELECT ON graph_changes TO atlas_app;
"""


def upgrade() -> None:
    op.create_table(
        "hpo_terms",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column(
            "synonyms",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "parents",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("ic", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "graph_changes",
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("previous_version", sa.Text(), nullable=True),
        sa.Column("disease_id", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("change", sa.Text(), nullable=False),
        sa.Column("edge_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("data_version", "disease_id", "node_id", "change"),
    )
    op.execute(GRANT_SQL)


def downgrade() -> None:
    op.drop_table("graph_changes")
    op.drop_table("hpo_terms")
