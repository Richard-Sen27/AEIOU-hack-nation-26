"""optional private work details for doctors and researchers on profiles

Revision ID: 22c0044931d2
Revises: c3d5f7a9b1e2
Create Date: 2026-10-04 18:00:00.000000

First and last name, up to three institutions, the ORCID iD (the column already exists) and a
private link to the user's own researcher or doctor node. Private to the account: the existing
owner policy on profiles covers the new columns, so no policy or grant changes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "22c0044931d2"
down_revision: str | Sequence[str] | None = "c3d5f7a9b1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECKS = {
    "ck_profiles_first_name_length": "char_length(first_name) BETWEEN 1 AND 100",
    "ck_profiles_last_name_length": "char_length(last_name) BETWEEN 1 AND 100",
    "ck_profiles_institutions_max_3": (
        "jsonb_typeof(institutions) = 'array' AND jsonb_array_length(institutions) <= 3"
    ),
    "ck_profiles_atlas_node_id_length": "char_length(atlas_node_id) BETWEEN 1 AND 200",
}


def upgrade() -> None:
    op.add_column("profiles", sa.Column("first_name", sa.Text(), nullable=True))
    op.add_column("profiles", sa.Column("last_name", sa.Text(), nullable=True))
    op.add_column(
        "profiles",
        sa.Column(
            "institutions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("profiles", sa.Column("atlas_node_id", sa.Text(), nullable=True))
    op.add_column(
        "profiles",
        sa.Column("professional_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "profiles", condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, "profiles", type_="check")
    for column in (
        "professional_updated_at",
        "atlas_node_id",
        "institutions",
        "last_name",
        "first_name",
    ):
        op.drop_column("profiles", column)
