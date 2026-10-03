"""one health_data consent replaces the upload consent

Revision ID: c3d5f7a9b1e2
Revises: b2c4e6a8d0f1
Create Date: 2026-10-04 12:00:00.000000

consents.consent_type is plain text (no CHECK constraint or enum type), so only the existing
rows change: an active or revoked `upload` consent becomes `health_data`, which covers the
same processing and more (chat, profile, documents). Versions stay as stored, so each row
still names the text the user agreed to.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d5f7a9b1e2"
down_revision: str | Sequence[str] | None = "b2c4e6a8d0f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _rename(old: str, new: str) -> None:
    # consents has FORCE ROW LEVEL SECURITY: lift it for the owner while rewriting all rows.
    op.execute("ALTER TABLE consents NO FORCE ROW LEVEL SECURITY")
    op.execute(f"UPDATE consents SET consent_type = '{new}' WHERE consent_type = '{old}'")
    op.execute("ALTER TABLE consents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rename("upload", "health_data")


def downgrade() -> None:
    _rename("health_data", "upload")
