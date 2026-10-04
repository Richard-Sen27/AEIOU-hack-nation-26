"""sign-ups to calls, the suggestions setting, and sign-up threads tied to their sign-up

Revision ID: d7f2a9c4e6b1
Revises: b6d1f4a8c2e7
Create Date: 2026-10-05 02:00:00.000000

Held under the `connect` consent (connect stage 4).

profiles (owner-only as before): suggestions_enabled (default off) and suggestions_enabled_at.
Suggestions themselves are never stored: they are computed in the patient's own request; the
only trace is the patient's own `call_match` rows in notifications.

call_signups (user table, FORCE row-level security, cascades from the patient's account; call_id
SET NULL when the call is deleted): the patient's sign-up to a published call with exactly the
items they ticked (`shared`), a display name, an optional note, the authorization (text version,
time, the named recipient) and, for a 16- or 17-year-old, the guardian agreement (text version,
time). Policies:
- call_signups_patient: the patient has full access to their own rows. The trigger
  call_signups_guard limits what the patient may change: withdraw (which clears shared and note
  at once and keeps a stub for 30 days) and link the sign-up's own conversation once.
- call_signups_publisher: the publisher of the call may SELECT the sign-ups of their own calls.
  There is no other cross-user read: no counts, no lists of matches.
- the publisher's decline goes through the SECURITY DEFINER function decline_call_signup(id)
  (clears shared and note, keeps a stub for 30 days).
- the trigger call_signups_admit (SECURITY DEFINER) admits a new sign-up only to a published,
  unexpired call of somebody else whose card is visible and verified, below max_signups
  (serialized per call).
- the trigger calls_end_signups (SECURITY DEFINER) marks the active sign-ups of a call that
  closes or is withdrawn as call_closed, purged 90 days later; a deleted call turns its sign-ups
  into stubs at once (call_signups_guard on the ON DELETE SET NULL update).
- atlas_owner (operator CLI) may delete rows past purge_after (`backend.cli purge-messages`).

threads: foreign keys from call_id (calls) and signup_id (call_signups), both SET NULL; the check
now only says that card threads carry no call or sign-up; the insert policy for sign-up threads
requires the patient's own active sign-up to that call, addressed to the call's publisher, with
no conversation yet. Existing sign-up references (written before the table existed) are cleared.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d7f2a9c4e6b1"
down_revision: str | Sequence[str] | None = "b6d1f4a8c2e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ME = "nullif(current_setting('app.user_id', true), '')::uuid"
VISIBLE_CARD = (
    "p.card_visible AND p.role_verified AND p.role IN ('doctor', 'researcher')"
    " AND p.card_id IS NOT NULL AND p.verification_method IS NOT NULL"
)
STUB_DAYS = 30
CLOSED_DAYS = 90
# What the patient's withdrawal may change; everything else stays as it was.
WITHDRAW_KEYS = "ARRAY['status', 'withdrawn_at', 'shared', 'note', 'purge_after', 'updated_at']"

CHECKS = {
    "ck_call_signups_status": "status IN ('active', 'withdrawn', 'declined', 'call_closed')",
    "ck_call_signups_display_name": "char_length(display_name) BETWEEN 1 AND 60",
    "ck_call_signups_note": "char_length(note) BETWEEN 1 AND 1000",
    "ck_call_signups_title": "char_length(call_title_snapshot) BETWEEN 1 AND 140",
    "ck_call_signups_recipient": "char_length(recipient_name) BETWEEN 1 AND 400",
    "ck_call_signups_shared": "jsonb_typeof(shared) = 'object'",
    "ck_call_signups_guardian_pair": (
        "(guardian_agreed_at IS NULL) = (guardian_text_version IS NULL)"
    ),
    "ck_call_signups_cleared": (
        "status IN ('active', 'call_closed') OR (shared = '{}'::jsonb AND note IS NULL)"
    ),
}

FUNCTIONS_SQL = f"""
CREATE FUNCTION public.call_signups_admit()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    v_status text;
    v_publisher uuid;
    v_closes date;
    v_max int;
BEGIN
    SELECT c.status, c.publisher_id, c.closes_at, c.max_signups
      INTO v_status, v_publisher, v_closes, v_max
      FROM calls c WHERE c.id = NEW.call_id;
    IF NOT FOUND OR v_status <> 'published'
       OR (v_closes IS NOT NULL AND v_closes < current_date) THEN
        RAISE EXCEPTION 'amber:closed' USING ERRCODE = 'check_violation';
    END IF;
    IF v_publisher = NEW.patient_id THEN
        RAISE EXCEPTION 'amber:own_call' USING ERRCODE = 'check_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM profiles p WHERE p.user_id = v_publisher AND {VISIBLE_CARD}) THEN
        RAISE EXCEPTION 'amber:not_available' USING ERRCODE = 'check_violation';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('amber-signups:' || NEW.call_id::text, 0));
    IF v_max IS NOT NULL AND (SELECT count(*) FROM call_signups s
                               WHERE s.call_id = NEW.call_id AND s.status = 'active') >= v_max THEN
        RAISE EXCEPTION 'amber:full' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION public.call_signups_guard()
RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp
AS $$
DECLARE
    withdrawing boolean;
    linking boolean;
    ignored text[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF current_user = 'atlas_app' AND (
               NEW.status <> 'active' OR NEW.call_id IS NULL OR NEW.withdrawn_at IS NOT NULL
               OR NEW.declined_at IS NOT NULL OR NEW.call_ended_at IS NOT NULL
               OR NEW.purge_after IS NOT NULL OR NEW.thread_id IS NOT NULL) THEN
            RAISE EXCEPTION 'amber:signup_insert' USING ERRCODE = 'insufficient_privilege';
        END IF;
        RETURN NEW;
    END IF;
    -- The call was deleted (ON DELETE SET NULL): nobody can receive the items any more.
    IF OLD.call_id IS NOT NULL AND NEW.call_id IS NULL THEN
        IF NEW.status IN ('active', 'call_closed') THEN
            NEW.status := 'call_closed';
            NEW.call_ended_at := COALESCE(NEW.call_ended_at, now());
        END IF;
        NEW.shared := '{{}}'::jsonb;
        NEW.note := NULL;
        NEW.purge_after := LEAST(COALESCE(NEW.purge_after, 'infinity'::timestamptz),
                                 now() + interval '{STUB_DAYS} days');
    END IF;
    IF current_user <> 'atlas_app' THEN
        RETURN NEW;  -- definer functions, the operator and foreign-key actions
    END IF;
    -- The patient: withdraw (clears the shared items and the note at once), or link the
    -- sign-up's own conversation once. Nothing else changes.
    withdrawing := NEW.status = 'withdrawn' AND OLD.status IN ('active', 'call_closed');
    IF withdrawing THEN
        NEW.withdrawn_at := now();
        NEW.shared := '{{}}'::jsonb;
        NEW.note := NULL;
        NEW.purge_after := now() + interval '{STUB_DAYS} days';
    END IF;
    linking := NEW.thread_id IS DISTINCT FROM OLD.thread_id;
    IF linking AND NOT (OLD.thread_id IS NULL AND EXISTS (
            SELECT 1 FROM threads t WHERE t.id = NEW.thread_id AND t.signup_id = NEW.id)) THEN
        RAISE EXCEPTION 'amber:signup_update' USING ERRCODE = 'insufficient_privilege';
    END IF;
    ignored := ARRAY['thread_id', 'updated_at'];
    IF withdrawing THEN
        ignored := ignored || {WITHDRAW_KEYS};
    END IF;
    IF (to_jsonb(NEW) - ignored) IS DISTINCT FROM (to_jsonb(OLD) - ignored) THEN
        RAISE EXCEPTION 'amber:signup_update' USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION public.decline_call_signup(p_signup uuid)
RETURNS text
LANGUAGE plpgsql VOLATILE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    me uuid := {ME};
    v_status text;
BEGIN
    IF me IS NULL THEN
        RAISE EXCEPTION 'amber:not_found';
    END IF;
    SELECT s.status INTO v_status
      FROM call_signups s JOIN calls c ON c.id = s.call_id
     WHERE s.id = p_signup AND c.publisher_id = me
       FOR UPDATE OF s;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'amber:not_found';
    END IF;
    IF v_status = 'declined' THEN
        RETURN v_status;
    END IF;
    IF v_status <> 'active' THEN
        RAISE EXCEPTION 'amber:not_active';
    END IF;
    UPDATE call_signups
       SET status = 'declined', declined_at = now(), shared = '{{}}'::jsonb, note = NULL,
           purge_after = now() + interval '{STUB_DAYS} days', updated_at = now()
     WHERE id = p_signup;
    RETURN 'declined';
END
$$;

CREATE FUNCTION public.calls_end_signups()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
BEGIN
    IF NEW.status IN ('closed', 'withdrawn') AND OLD.status NOT IN ('closed', 'withdrawn') THEN
        UPDATE call_signups
           SET status = 'call_closed', call_ended_at = now(),
               purge_after = now() + interval '{CLOSED_DAYS} days', updated_at = now()
         WHERE call_id = NEW.id AND status = 'active';
    END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER call_signups_admit BEFORE INSERT ON call_signups
    FOR EACH ROW EXECUTE FUNCTION public.call_signups_admit();
CREATE TRIGGER call_signups_guard BEFORE INSERT OR UPDATE ON call_signups
    FOR EACH ROW EXECUTE FUNCTION public.call_signups_guard();
CREATE TRIGGER calls_end_signups AFTER UPDATE OF status ON calls
    FOR EACH ROW EXECUTE FUNCTION public.calls_end_signups();

ALTER FUNCTION public.call_signups_admit() OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.call_signups_admit() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.call_signups_admit() TO atlas_app;
REVOKE ALL ON FUNCTION public.call_signups_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.call_signups_guard() TO atlas_app, atlas_definer;
ALTER FUNCTION public.decline_call_signup(uuid) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.decline_call_signup(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.decline_call_signup(uuid) TO atlas_app;
ALTER FUNCTION public.calls_end_signups() OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.calls_end_signups() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.calls_end_signups() TO atlas_app, atlas_definer;
"""

POLICIES_SQL = f"""
ALTER TABLE call_signups ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_signups FORCE ROW LEVEL SECURITY;
CREATE POLICY call_signups_patient ON call_signups TO atlas_app
    USING (patient_id = {ME}) WITH CHECK (patient_id = {ME});
CREATE POLICY call_signups_publisher ON call_signups FOR SELECT TO atlas_app
    USING (EXISTS (SELECT 1 FROM calls c
                    WHERE c.id = call_signups.call_id AND c.publisher_id = {ME}));
GRANT SELECT, INSERT, UPDATE, DELETE ON call_signups TO atlas_app;

-- The definer functions read and write only what they need.
GRANT SELECT ON call_signups TO atlas_definer;
GRANT UPDATE (status, declined_at, call_ended_at, shared, note, purge_after, updated_at)
    ON call_signups TO atlas_definer;
CREATE POLICY call_signups_definer ON call_signups TO atlas_definer
    USING (true) WITH CHECK (true);
-- Operator CLI (atlas_owner): the daily purge of rows past purge_after.
CREATE POLICY call_signups_operator ON call_signups TO atlas_owner
    USING (true) WITH CHECK (true);

DROP POLICY threads_signup_insert ON threads;
CREATE POLICY threads_signup_insert ON threads FOR INSERT TO atlas_app
    WITH CHECK (opener_id = {ME} AND origin = 'signup' AND status = 'open'
                AND recipient_id IS NOT NULL AND recipient_id <> {ME}
                AND EXISTS (
                    SELECT 1 FROM call_signups s JOIN calls c ON c.id = s.call_id
                     WHERE s.id = threads.signup_id AND s.call_id = threads.call_id
                       AND s.patient_id = {ME} AND s.status = 'active'
                       AND s.thread_id IS NULL AND c.publisher_id = threads.recipient_id));
"""

OLD_THREADS_INSERT_SQL = f"""
DROP POLICY threads_signup_insert ON threads;
CREATE POLICY threads_signup_insert ON threads FOR INSERT TO atlas_app
    WITH CHECK (opener_id = {ME} AND origin = 'signup' AND status = 'open'
                AND recipient_id IS NOT NULL AND recipient_id <> {ME});
"""


def _ts(name: str, *, now: bool = False) -> sa.Column:
    if now:
        return sa.Column(
            name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        )
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def upgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("suggestions_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "profiles", sa.Column("suggestions_enabled_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "call_signups",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("patient_id", sa.UUID(), nullable=False),
        sa.Column("call_title_snapshot", sa.Text(), nullable=False),
        sa.Column("recipient_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "shared",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("about_child", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("authorization_version", sa.Text(), nullable=False),
        _ts("authorized_at", now=True),
        _ts("guardian_agreed_at"),
        sa.Column("guardian_text_version", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        _ts("withdrawn_at"),
        _ts("declined_at"),
        _ts("call_ended_at"),
        _ts("purge_after"),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        _ts("created_at", now=True),
        _ts("updated_at", now=True),
        *(sa.CheckConstraint(cond, name=name) for name, cond in CHECKS.items()),
        sa.ForeignKeyConstraint(["call_id"], ["calls.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["patient_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_call_signups_patient_id", "call_signups", ["patient_id"], unique=False)
    op.create_index("ix_call_signups_call_id", "call_signups", ["call_id"], unique=False)
    op.create_index(
        "uq_call_signups_one_per_call",
        "call_signups",
        ["call_id", "patient_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'declined')"),
    )

    # Threads: sign-up references become real foreign keys (cleared where they point nowhere).
    op.drop_constraint("ck_threads_signup_refs", "threads", type_="check")
    op.execute(
        "UPDATE threads SET call_id = NULL WHERE call_id IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM calls c WHERE c.id = threads.call_id)"
    )
    op.execute("UPDATE threads SET signup_id = NULL WHERE signup_id IS NOT NULL")
    op.create_check_constraint(
        "ck_threads_signup_refs",
        "threads",
        "origin = 'signup' OR (call_id IS NULL AND signup_id IS NULL)",
    )
    op.create_foreign_key(
        "threads_call_id_fkey", "threads", "calls", ["call_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "threads_signup_id_fkey",
        "threads",
        "call_signups",
        ["signup_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_threads_signup_id", "threads", ["signup_id"], unique=False)

    op.execute(FUNCTIONS_SQL)
    op.execute(POLICIES_SQL)


def downgrade() -> None:
    op.execute(OLD_THREADS_INSERT_SQL)
    op.drop_index("ix_threads_signup_id", table_name="threads")
    op.drop_constraint("threads_signup_id_fkey", "threads", type_="foreignkey")
    op.drop_constraint("threads_call_id_fkey", "threads", type_="foreignkey")
    op.drop_constraint("ck_threads_signup_refs", "threads", type_="check")
    op.execute("DELETE FROM threads WHERE origin = 'signup'")
    op.create_check_constraint(
        "ck_threads_signup_refs",
        "threads",
        "origin <> 'signup' OR (call_id IS NOT NULL AND signup_id IS NOT NULL)",
    )
    op.execute("DROP TRIGGER IF EXISTS calls_end_signups ON calls")
    op.drop_table("call_signups")
    op.execute("DROP FUNCTION IF EXISTS public.calls_end_signups()")
    op.execute("DROP FUNCTION IF EXISTS public.decline_call_signup(uuid)")
    op.execute("DROP FUNCTION IF EXISTS public.call_signups_guard()")
    op.execute("DROP FUNCTION IF EXISTS public.call_signups_admit()")
    op.drop_column("profiles", "suggestions_enabled_at")
    op.drop_column("profiles", "suggestions_enabled")
