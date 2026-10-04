"""allow the 'manual_simulated' verification method (demo auto-approval of manual requests)

Revision ID: b6d1f4a8c2e7
Revises: 247a1157973f
Create Date: 2026-10-04 09:00:00.000000

In local demo settings only (ORCID_MOCK on, API and frontend on loopback) a manual verification
request is approved at once; such verifications are stored as 'manual_simulated' and labelled
"demo, verification simulated" on the card.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d1f4a8c2e7"
down_revision: str | Sequence[str] | None = "247a1157973f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NAME = "ck_profiles_verification_method"


def upgrade() -> None:
    op.drop_constraint(NAME, "profiles", type_="check")
    op.create_check_constraint(
        NAME,
        "profiles",
        "verification_method IN ('orcid', 'orcid_simulated', 'institutional_email',"
        " 'manual_simulated')",
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "profiles", type_="check")
    op.create_check_constraint(
        NAME,
        "profiles",
        "verification_method IN ('orcid', 'orcid_simulated', 'institutional_email')",
    )
