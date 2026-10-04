"""verification and the opt-in public card for doctors and researchers

Revision ID: 9c4e2a7b5d13
Revises: 5b8e1f3a7c92
Create Date: 2026-10-04 23:00:00.000000

New columns on profiles (owner-only, FORCE row-level security as before):
- verification: orcid_verified_at, verified_name, verification_method ('orcid',
  'orcid_simulated' for the local mock, 'institutional_email'), verified_at,
  verification_reason (the operator's logged reason), verification_request (a pending or
  rejected manual review request), atlas_link_verified;
- the card, off by default: card_id (opaque, never the user id), card_visible,
  card_visible_since, card_headline (<= 160), card_show_institutions, card_show_atlas_entry,
  accepts_patient_messages (stored flag only; messaging is not built).

Other users see a card only through the SECURITY DEFINER function professional_cards(), and only
while card_visible AND role_verified for a doctor or researcher; it returns the chosen card fields
and never user_id, e-mail or the private work details behind them (an unverified atlas link or
ORCID iD stays private). atlas_definer's SELECT on profiles becomes column-scoped to what its
functions read. pending_verification_requests() is for the operator CLI only (EXECUTE granted to
atlas_owner, not to the API role).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c4e2a7b5d13"
down_revision: str | Sequence[str] | None = "5b8e1f3a7c92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BOOL_COLUMNS = {
    "atlas_link_verified": "false",
    "card_visible": "false",
    "card_show_institutions": "true",
    "card_show_atlas_entry": "true",
    "accepts_patient_messages": "false",
}
CHECKS = {
    "ck_profiles_verification_method": (
        "verification_method IN ('orcid', 'orcid_simulated', 'institutional_email')"
    ),
    "ck_profiles_verified_name_length": "char_length(verified_name) BETWEEN 1 AND 200",
    "ck_profiles_verification_reason_length": (
        "char_length(verification_reason) BETWEEN 1 AND 500"
    ),
    "ck_profiles_card_headline_length": "char_length(card_headline) BETWEEN 1 AND 160",
    "ck_profiles_card_visible_has_id": "NOT card_visible OR card_id IS NOT NULL",
    "ck_profiles_verification_request_object": (
        "verification_request IS NULL OR jsonb_typeof(verification_request) = 'object'"
    ),
}

# Every column atlas_definer's functions read on profiles (auth_find_or_create_user inserts only).
DEFINER_COLUMNS = (
    "user_id, role, role_verified, first_name, last_name, institutions, orcid_id, atlas_node_id,"
    " verified_name, orcid_verified_at, verification_method, verification_request,"
    " atlas_link_verified, card_id, card_visible, card_headline, card_show_institutions,"
    " card_show_atlas_entry, accepts_patient_messages"
)

CARD_NAME = "COALESCE(p.verified_name, NULLIF(concat_ws(' ', p.first_name, p.last_name), ''))"

FUNCTIONS_SQL = f"""
CREATE FUNCTION public.professional_cards()
RETURNS TABLE (card_id uuid, role text, name text, name_verified boolean, institutions jsonb,
               orcid_id text, atlas_node_id text, headline text,
               accepts_patient_messages boolean, verification_method text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT p.card_id, p.role, {CARD_NAME}, p.verified_name IS NOT NULL,
           CASE WHEN p.card_show_institutions THEN p.institutions ELSE '[]'::jsonb END,
           CASE WHEN p.orcid_verified_at IS NOT NULL THEN p.orcid_id END,
           CASE WHEN p.atlas_link_verified AND p.card_show_atlas_entry THEN p.atlas_node_id END,
           p.card_headline, p.accepts_patient_messages, p.verification_method
      FROM profiles p
     WHERE p.card_visible AND p.role_verified AND p.role IN ('doctor', 'researcher')
       AND p.card_id IS NOT NULL AND p.verification_method IS NOT NULL
       AND {CARD_NAME} IS NOT NULL
$$;

CREATE FUNCTION public.pending_verification_requests()
RETURNS TABLE (user_id uuid, role text, first_name text, last_name text, institutions jsonb,
               orcid_id text, request jsonb)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT p.user_id, p.role, p.first_name, p.last_name, p.institutions, p.orcid_id,
           p.verification_request
      FROM profiles p
     WHERE p.verification_request->>'status' = 'pending'
     ORDER BY p.verification_request->>'requested_at'
$$;

ALTER FUNCTION public.professional_cards() OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.professional_cards() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.professional_cards() TO atlas_app;
ALTER FUNCTION public.pending_verification_requests() OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.pending_verification_requests() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.pending_verification_requests() TO atlas_owner;
"""


def upgrade() -> None:
    op.add_column("profiles", sa.Column("orcid_verified_at", sa.DateTime(timezone=True)))
    op.add_column("profiles", sa.Column("verified_name", sa.Text()))
    op.add_column("profiles", sa.Column("verification_method", sa.Text()))
    op.add_column("profiles", sa.Column("verified_at", sa.DateTime(timezone=True)))
    op.add_column("profiles", sa.Column("verification_reason", sa.Text()))
    op.add_column(
        "profiles",
        sa.Column("verification_request", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column("profiles", sa.Column("card_id", sa.UUID()))
    op.add_column("profiles", sa.Column("card_visible_since", sa.DateTime(timezone=True)))
    op.add_column("profiles", sa.Column("card_headline", sa.Text()))
    for name, default in BOOL_COLUMNS.items():
        op.add_column(
            "profiles",
            sa.Column(name, sa.Boolean(), server_default=default, nullable=False),
        )
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "profiles", condition)
    op.create_index("uq_profiles_card_id", "profiles", ["card_id"], unique=True)
    # One account per confirmed ORCID iD (self-declared, unconfirmed iDs may repeat).
    op.create_index(
        "uq_profiles_verified_orcid",
        "profiles",
        ["orcid_id"],
        unique=True,
        postgresql_where=sa.text("orcid_verified_at IS NOT NULL"),
    )
    op.execute(
        "REVOKE SELECT ON profiles FROM atlas_definer;\n"
        f"GRANT SELECT ({DEFINER_COLUMNS}) ON profiles TO atlas_definer;"
    )
    op.execute(FUNCTIONS_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.pending_verification_requests()")
    op.execute("DROP FUNCTION IF EXISTS public.professional_cards()")
    op.execute(
        f"REVOKE SELECT ({DEFINER_COLUMNS}) ON profiles FROM atlas_definer;\n"
        "GRANT SELECT ON profiles TO atlas_definer;"
    )
    op.drop_index("uq_profiles_verified_orcid", table_name="profiles")
    op.drop_index("uq_profiles_card_id", table_name="profiles")
    for name in CHECKS:
        op.drop_constraint(name, "profiles", type_="check")
    for column in (
        *BOOL_COLUMNS,
        "card_headline",
        "card_visible_since",
        "card_id",
        "verification_request",
        "verification_reason",
        "verified_at",
        "verification_method",
        "verified_name",
        "orcid_verified_at",
    ):
        op.drop_column("profiles", column)
