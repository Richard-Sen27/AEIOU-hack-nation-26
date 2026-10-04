"""calls: surveys, studies and trials that verified professionals publish after review

Revision ID: 247a1157973f
Revises: a4c7e9b2d6f8
Create Date: 2026-10-05 01:00:00.000000

calls (user table, cascades from users): a publisher's survey, study or trial looking for
participants. Owner policy as on every user table, plus one more SELECT policy: every signed-in
user may read published calls (`status = 'published' AND app.user_id IS NOT NULL`). Guests see
nothing. Nothing about who reads a call is stored.

Moderation: only the operator publishes. The trigger calls_guard stops the API role from setting
status 'published' or 'rejected', from touching review_note, reviewed_at, published_at and demo,
and from changing the content of a published call (it can only be closed). The operator CLI
(atlas_owner) reviews through two SECURITY DEFINER functions owned by atlas_definer:
pending_calls(operator) lists calls waiting for review and logs a 'viewed' row per call;
review_call(call, decision, note, operator) approves or rejects and logs the decision. EXECUTE on
both is granted to atlas_owner only, never to the API role.

call_reviews: the operator log (viewed, approved, rejected), one row per action, with the
operator's name and note. The publisher may read the rows about their own calls (export); nobody
can write them except the definer functions; they go with the call and with the account.

call_publisher_cards() maps published calls to their publisher's public card (card_id only,
never the user id) while that card is visible and verified, for signed-in callers only. The API
joins it with professional_cards() to show "run by [card name], [institution]".
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "247a1157973f"
down_revision: str | Sequence[str] | None = "a4c7e9b2d6f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ME = "nullif(current_setting('app.user_id', true), '')::uuid"
VISIBLE_CARD = (
    "p.card_visible AND p.role_verified AND p.role IN ('doctor', 'researcher')"
    " AND p.card_id IS NOT NULL AND p.verification_method IS NOT NULL"
)
CARD_NAME = "COALESCE(p.verified_name, NULLIF(concat_ws(' ', p.first_name, p.last_name), ''))"

CHECKS = {
    "ck_calls_kind": "kind IN ('survey', 'study', 'trial')",
    "ck_calls_status": (
        "status IN ('draft', 'pending_review', 'published', 'closed', 'withdrawn', 'rejected')"
    ),
    "ck_calls_title_length": "char_length(title) BETWEEN 1 AND 140",
    "ck_calls_summary_length": "char_length(summary) BETWEEN 1 AND 1000",
    "ck_calls_participation_length": "char_length(participation) BETWEEN 1 AND 1000",
    "ck_calls_eligibility_length": "char_length(eligibility_text) BETWEEN 1 AND 1500",
    "ck_calls_diseases": "cardinality(disease_ids) BETWEEN 1 AND 10",
    "ck_calls_genes": "cardinality(gene_ids) <= 20",
    "ck_calls_phenotypes": "cardinality(phenotype_ids) <= 30",
    "ck_calls_countries": "cardinality(countries) <= 60",
    "ck_calls_requested_fields": (
        "requested_fields <@ ARRAY['diagnosis', 'genetic_findings', 'symptoms', 'age_range',"
        " 'country']::text[]"
    ),
    "ck_calls_ages": (
        "(min_age IS NULL OR min_age BETWEEN 0 AND 120)"
        " AND (max_age IS NULL OR max_age BETWEEN 0 AND 120)"
        " AND (min_age IS NULL OR max_age IS NULL OR min_age <= max_age)"
    ),
    "ck_calls_dates": "opens_at IS NULL OR closes_at IS NULL OR opens_at <= closes_at",
    "ck_calls_max_signups": "max_signups IS NULL OR max_signups BETWEEN 1 AND 10000",
    "ck_calls_run_by_label_length": "char_length(run_by_label) BETWEEN 1 AND 200",
    "ck_calls_ethics_body_length": "char_length(ethics_body) BETWEEN 1 AND 200",
    "ck_calls_ethics_reference_length": "char_length(ethics_reference) BETWEEN 1 AND 100",
    "ck_calls_review_note_length": "char_length(review_note) BETWEEN 1 AND 1000",
    "ck_calls_external_url": (
        "external_url IS NULL OR (external_url LIKE 'https://%' AND char_length(external_url)"
        " <= 500)"
    ),
    "ck_calls_ethics_required": "kind = 'survey' OR ethics_reference IS NOT NULL",
    "ck_calls_registry_required": "kind <> 'trial' OR registry_id IS NOT NULL",
    "ck_calls_registry_id": (
        "registry_id IS NULL OR registry_id ~ '^(NCT[0-9]{8}|DRKS[0-9]{8}"
        "|[0-9]{4}-[0-9]{6}-[0-9]{2}(-[0-9]{2})?)$'"
    ),
}

POLICIES_SQL = f"""
ALTER TABLE calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE calls FORCE ROW LEVEL SECURITY;
CREATE POLICY calls_owner ON calls
    USING (publisher_id = {ME}) WITH CHECK (publisher_id = {ME});
CREATE POLICY calls_published ON calls FOR SELECT TO atlas_app
    USING (status = 'published' AND {ME} IS NOT NULL);
GRANT SELECT, INSERT, UPDATE, DELETE ON calls TO atlas_app;

ALTER TABLE call_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY call_reviews_owner ON call_reviews FOR SELECT TO atlas_app
    USING (publisher_id = {ME});
GRANT SELECT ON call_reviews TO atlas_app;

-- The definer functions read and write only what they need.
GRANT SELECT ON calls TO atlas_definer;
GRANT UPDATE (status, review_note, reviewed_at, published_at, updated_at) ON calls
    TO atlas_definer;
GRANT INSERT ON call_reviews TO atlas_definer;
CREATE POLICY calls_definer ON calls TO atlas_definer USING (true) WITH CHECK (true);
CREATE POLICY call_reviews_definer ON call_reviews FOR INSERT TO atlas_definer
    WITH CHECK (true);
"""

FUNCTIONS_SQL = f"""
CREATE FUNCTION public.calls_guard()
RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp
AS $$
BEGIN
    IF current_user = 'atlas_definer' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('draft', 'pending_review') OR NEW.review_note IS NOT NULL
           OR NEW.reviewed_at IS NOT NULL OR NEW.published_at IS NOT NULL THEN
            RAISE EXCEPTION 'calls are published only through review'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.review_note IS DISTINCT FROM OLD.review_note
       OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
       OR NEW.published_at IS DISTINCT FROM OLD.published_at
       OR NEW.demo IS DISTINCT FROM OLD.demo
       OR NEW.publisher_id IS DISTINCT FROM OLD.publisher_id
       OR (NEW.status IS DISTINCT FROM OLD.status AND NEW.status IN ('published', 'rejected'))
       OR (OLD.status = 'published' AND NEW.status = 'published'
           AND to_jsonb(NEW) - 'updated_at' IS DISTINCT FROM to_jsonb(OLD) - 'updated_at') THEN
        RAISE EXCEPTION 'calls are published only through review'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER calls_guard BEFORE INSERT OR UPDATE ON calls
    FOR EACH ROW EXECUTE FUNCTION public.calls_guard();

CREATE FUNCTION public.call_publisher_cards()
RETURNS TABLE (call_id uuid, card_id uuid)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT c.id, p.card_id
      FROM calls c JOIN profiles p ON p.user_id = c.publisher_id
     WHERE c.status = 'published' AND {ME} IS NOT NULL AND {VISIBLE_CARD}
$$;

CREATE FUNCTION public.pending_calls(p_operator text)
RETURNS TABLE (call_id uuid, call jsonb, publisher jsonb)
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
BEGIN
    IF p_operator IS NULL OR char_length(btrim(p_operator)) NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'operator name is required';
    END IF;
    INSERT INTO call_reviews (call_id, publisher_id, action, operator)
    SELECT c.id, c.publisher_id, 'viewed', btrim(p_operator)
      FROM calls c WHERE c.status = 'pending_review';
    RETURN QUERY
    SELECT c.id,
           to_jsonb(c) - 'publisher_id',
           jsonb_build_object(
               'card_id', p.card_id, 'role', p.role, 'name', {CARD_NAME},
               'verification_method', p.verification_method,
               'institutions', p.institutions,
               'card_visible', p.card_visible, 'role_verified', p.role_verified)
      FROM calls c JOIN profiles p ON p.user_id = c.publisher_id
     WHERE c.status = 'pending_review'
     ORDER BY c.submitted_at, c.id;
END
$$;

CREATE FUNCTION public.review_call(p_call uuid, p_decision text, p_note text, p_operator text)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    v_status text;
    v_publisher uuid;
    v_note text := NULLIF(btrim(p_note), '');
BEGIN
    IF p_operator IS NULL OR char_length(btrim(p_operator)) NOT BETWEEN 1 AND 100 THEN
        RAISE EXCEPTION 'operator name is required';
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('approve', 'reject') THEN
        RAISE EXCEPTION 'decision must be approve or reject';
    END IF;
    IF p_decision = 'reject' AND v_note IS NULL THEN
        RAISE EXCEPTION 'a rejection needs a note for the publisher';
    END IF;
    SELECT c.status, c.publisher_id INTO v_status, v_publisher
      FROM calls c WHERE c.id = p_call FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no such call';
    END IF;
    IF v_status <> 'pending_review' THEN
        RAISE EXCEPTION 'the call is not waiting for review (status %)', v_status;
    END IF;
    IF p_decision = 'approve' THEN
        IF NOT EXISTS (SELECT 1 FROM profiles p
                        WHERE p.user_id = v_publisher AND {VISIBLE_CARD}) THEN
            RAISE EXCEPTION 'the publisher no longer has a verified, visible card';
        END IF;
        UPDATE calls SET status = 'published', review_note = v_note, reviewed_at = now(),
                         published_at = now(), updated_at = now()
         WHERE id = p_call;
    ELSE
        UPDATE calls SET status = 'rejected', review_note = v_note, reviewed_at = now(),
                         updated_at = now()
         WHERE id = p_call;
    END IF;
    INSERT INTO call_reviews (call_id, publisher_id, action, note, operator)
    VALUES (p_call, v_publisher,
            CASE WHEN p_decision = 'approve' THEN 'approved' ELSE 'rejected' END,
            v_note, btrim(p_operator));
    RETURN CASE WHEN p_decision = 'approve' THEN 'published' ELSE 'rejected' END;
END
$$;

ALTER FUNCTION public.call_publisher_cards() OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.call_publisher_cards() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.call_publisher_cards() TO atlas_app;
ALTER FUNCTION public.pending_calls(text) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.pending_calls(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.pending_calls(text) TO atlas_owner;
ALTER FUNCTION public.review_call(uuid, text, text, text) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.review_call(uuid, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.review_call(uuid, text, text, text) TO atlas_owner;
"""


def _created(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _text_array(name: str) -> sa.Column:
    return sa.Column(
        name, postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "calls",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("participation", sa.Text(), nullable=False),
        sa.Column("eligibility_text", sa.Text(), nullable=True),
        sa.Column("disease_ids", postgresql.ARRAY(sa.Text()), nullable=False),
        _text_array("gene_ids"),
        _text_array("phenotype_ids"),
        sa.Column("min_age", sa.Integer(), nullable=True),
        sa.Column("max_age", sa.Integer(), nullable=True),
        sa.Column("children_ok", sa.Boolean(), server_default="false", nullable=False),
        _text_array("countries"),
        sa.Column("remote", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("run_by_label", sa.Text(), nullable=True),
        sa.Column("run_by_node_id", sa.Text(), nullable=True),
        sa.Column("ethics_body", sa.Text(), nullable=True),
        sa.Column("ethics_reference", sa.Text(), nullable=True),
        sa.Column("registry_id", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("opens_at", sa.Date(), nullable=True),
        sa.Column("closes_at", sa.Date(), nullable=True),
        sa.Column("max_signups", sa.Integer(), nullable=True),
        _text_array("requested_fields"),
        sa.Column("status", sa.Text(), server_default="draft", nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("demo", sa.Boolean(), server_default="false", nullable=False),
        _created(),
        _created("updated_at"),
        *(sa.CheckConstraint(cond, name=name) for name, cond in CHECKS.items()),
        sa.ForeignKeyConstraint(["publisher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_calls_publisher_id", "calls", ["publisher_id"], unique=False)
    op.create_index("ix_calls_status", "calls", ["status", "published_at"], unique=False)
    op.create_index(
        "ix_calls_disease_ids", "calls", ["disease_ids"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "call_reviews",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=False),
        sa.Column("publisher_id", sa.UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("operator", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "action IN ('viewed', 'approved', 'rejected')", name="ck_call_reviews_action"
        ),
        sa.CheckConstraint(
            "char_length(operator) BETWEEN 1 AND 100", name="ck_call_reviews_operator"
        ),
        sa.CheckConstraint("char_length(note) BETWEEN 1 AND 1000", name="ck_call_reviews_note"),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publisher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_reviews_call_id", "call_reviews", ["call_id"], unique=False)
    op.create_index("ix_call_reviews_publisher_id", "call_reviews", ["publisher_id"], unique=False)
    op.execute(POLICIES_SQL)
    op.execute(FUNCTIONS_SQL)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.review_call(uuid, text, text, text)")
    op.execute("DROP FUNCTION IF EXISTS public.pending_calls(text)")
    op.execute("DROP FUNCTION IF EXISTS public.call_publisher_cards()")
    op.execute("DROP TRIGGER IF EXISTS calls_guard ON calls")
    op.execute("DROP FUNCTION IF EXISTS public.calls_guard()")
    op.drop_table("call_reviews")
    op.drop_table("calls")
