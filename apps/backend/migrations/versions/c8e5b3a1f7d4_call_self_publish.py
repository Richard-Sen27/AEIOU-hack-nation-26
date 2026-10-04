"""calls: a verified professional may publish their own call without review

Revision ID: c8e5b3a1f7d4
Revises: d7f2a9c4e6b1
Create Date: 2026-10-05 03:00:00.000000

The user decided that an expert publishes a call themselves from the form. The application
chooses the mode with the setting CALLS_REVIEW_REQUIRED (default false): when review is not
required, submit calls publish_own_call(); when it is, nothing here is used and the operator
publishes through review_call() as before.

publish_own_call(call) (SECURITY DEFINER, owned by atlas_definer, EXECUTE for the API role):
moves the caller's OWN call from draft or pending_review to published, and nothing else. It
re-checks that the caller owns the call and still has a verified, visible card, marks the call
`self_published` and writes a 'self_published' row to call_reviews, so the log stays complete.
It cannot publish another user's call, a rejected, closed or withdrawn call, or change content.

calls.self_published: true for a call that went live without review. The API shows such a call
with "Published by the expert. Not reviewed by the Amber team." instead of the review badge.
calls_guard now also stops the API role from setting or changing self_published; everything it
refused before it still refuses (publishing or rejecting directly, touching review fields or
demo, editing a published call).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e5b3a1f7d4"
down_revision: str | Sequence[str] | None = "d7f2a9c4e6b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ME = "nullif(current_setting('app.user_id', true), '')::uuid"
VISIBLE_CARD = (
    "p.card_visible AND p.role_verified AND p.role IN ('doctor', 'researcher')"
    " AND p.card_id IS NOT NULL AND p.verification_method IS NOT NULL"
)


def _guard_sql(*, self_published: bool) -> str:
    """calls_guard, with or without the self_published checks (upgrade / downgrade)."""
    on_insert = " OR NEW.self_published" if self_published else ""
    on_update = (
        "\n       OR NEW.self_published IS DISTINCT FROM OLD.self_published"
        if self_published
        else ""
    )
    return f"""
CREATE OR REPLACE FUNCTION public.calls_guard()
RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp
AS $$
BEGIN
    IF current_user = 'atlas_definer' THEN
        RETURN NEW;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('draft', 'pending_review') OR NEW.review_note IS NOT NULL
           OR NEW.reviewed_at IS NOT NULL OR NEW.published_at IS NOT NULL{on_insert} THEN
            RAISE EXCEPTION 'calls are published only through review'
                USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.review_note IS DISTINCT FROM OLD.review_note
       OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
       OR NEW.published_at IS DISTINCT FROM OLD.published_at
       OR NEW.demo IS DISTINCT FROM OLD.demo{on_update}
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
"""


PUBLISH_SQL = f"""
CREATE FUNCTION public.publish_own_call(p_call uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    v_me uuid := {ME};
    v_status text;
    v_publisher uuid;
BEGIN
    IF v_me IS NULL THEN
        RAISE EXCEPTION 'sign-in required' USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT c.status, c.publisher_id INTO v_status, v_publisher
      FROM calls c WHERE c.id = p_call FOR UPDATE;
    IF NOT FOUND OR v_publisher <> v_me THEN
        RAISE EXCEPTION 'no such call' USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF v_status NOT IN ('draft', 'pending_review') THEN
        RAISE EXCEPTION 'only a draft or a call waiting for review can be published (status %)',
            v_status USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM profiles p WHERE p.user_id = v_me AND {VISIBLE_CARD}) THEN
        RAISE EXCEPTION 'only a verified professional with a visible card can publish'
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    UPDATE calls SET status = 'published', self_published = true, review_note = NULL,
                     reviewed_at = NULL, submitted_at = now(), published_at = now(),
                     updated_at = now()
     WHERE id = p_call;
    INSERT INTO call_reviews (call_id, publisher_id, action, operator)
    VALUES (p_call, v_me, 'self_published', 'publisher');
    RETURN 'published';
END
$$;

ALTER FUNCTION public.publish_own_call(uuid) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.publish_own_call(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.publish_own_call(uuid) TO atlas_app;
GRANT UPDATE (self_published, submitted_at) ON calls TO atlas_definer;
"""


def upgrade() -> None:
    op.add_column(
        "calls",
        sa.Column("self_published", sa.Boolean(), server_default="false", nullable=False),
    )
    op.drop_constraint("ck_call_reviews_action", "call_reviews", type_="check")
    op.create_check_constraint(
        "ck_call_reviews_action",
        "call_reviews",
        "action IN ('viewed', 'approved', 'rejected', 'self_published')",
    )
    op.execute(_guard_sql(self_published=True))
    op.execute(PUBLISH_SQL)


def downgrade() -> None:
    # Refuse rather than relabel: a call that went live without review must not turn into one
    # that carries the review badge.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM calls WHERE self_published)
               OR EXISTS (SELECT 1 FROM call_reviews WHERE action = 'self_published') THEN
                RAISE EXCEPTION 'self-published calls exist: delete them before downgrading';
            END IF;
        END
        $$
        """
    )
    op.execute("DROP FUNCTION IF EXISTS public.publish_own_call(uuid)")
    op.execute("REVOKE UPDATE (self_published, submitted_at) ON calls FROM atlas_definer")
    op.execute(_guard_sql(self_published=False))
    op.drop_constraint("ck_call_reviews_action", "call_reviews", type_="check")
    op.create_check_constraint(
        "ck_call_reviews_action", "call_reviews", "action IN ('viewed', 'approved', 'rejected')"
    )
    op.drop_column("calls", "self_published")
