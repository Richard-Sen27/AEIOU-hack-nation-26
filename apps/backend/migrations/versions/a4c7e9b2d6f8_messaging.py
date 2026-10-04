"""messaging between patients and professionals, and the connect age group

Revision ID: a4c7e9b2d6f8
Revises: f3b8d2a6c4e1
Create Date: 2026-10-05 00:30:00.000000

Messaging is held under the `connect` consent ("Studies, surveys and contacts"). New columns on
profiles (owner-only as before): connect_age_group ('18_plus' | '16_17', self-declared at the
first connect action, correctable) and connect_age_group_at.

User tables (FORCE row-level security, cascade or set null from users):
- threads: participant policy (opener_id = me OR recipient_id = me). A card thread is created
  only by the SECURITY DEFINER function open_card_thread(card_id, ...), which resolves the card to
  the professional inside the database (the caller never learns a user id), checks that the card
  is visible, verified and accepts patient messages, that the caller is a patient, that nobody
  blocked anybody, and the limit of 5 new threads per day; it stores the request message too.
  Sign-up threads (stage 4) are inserted directly by the patient (origin 'signup', status
  'open'). Participants may UPDATE only status and last_message_at; the trigger threads_guard
  allows only the planned transitions (only the recipient accepts or declines) and, when a
  participant's account is deleted (ON DELETE SET NULL), drops that person's name snapshot and
  closes the thread. Participants may DELETE a thread only once it has been inactive for 12
  months or the other participant is gone.
- thread_reads: the user's own read marker, hidden flag and the guardian agreement of a 16- or
  17-year-old (text version and time) per thread; owner-only.
- messages: body_enc is Fernet ciphertext (MESSAGE_ENCRYPTION_KEY, never readable by the
  database). SELECT when I take part; INSERT only as myself into an open thread whose
  participants both exist and have not blocked each other; DELETE only my own; no UPDATE.
- blocks: the blocker's rows; checked through messaging_blocked(a, b), which answers only for a
  caller who is a or b.
- reports: the reporter's rows; filing one authorizes the operator to read that thread.

Operator access: admin_access_log (no API access) records every read of a reported thread with
operator and reason. The operator CLI runs as atlas_owner, which gets explicit policies on the
messaging tables (FORCE row-level security applies to the owner too) for reading reported
threads, key rotation and the 12-month clean-up.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c7e9b2d6f8"
down_revision: str | Sequence[str] | None = "f3b8d2a6c4e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ME = "nullif(current_setting('app.user_id', true), '')::uuid"
TABLES = ("threads", "thread_reads", "messages", "blocks", "reports")
CARD_NAME = "COALESCE(p.verified_name, NULLIF(concat_ws(' ', p.first_name, p.last_name), ''))"


def _created() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )


POLICIES_SQL = f"""
CREATE POLICY threads_participant ON threads FOR SELECT TO atlas_app
    USING (opener_id = {ME} OR recipient_id = {ME});
CREATE POLICY threads_signup_insert ON threads FOR INSERT TO atlas_app
    WITH CHECK (opener_id = {ME} AND origin = 'signup' AND status = 'open'
                AND recipient_id IS NOT NULL AND recipient_id <> {ME});
CREATE POLICY threads_participant_update ON threads FOR UPDATE TO atlas_app
    USING (opener_id = {ME} OR recipient_id = {ME})
    WITH CHECK (opener_id = {ME} OR recipient_id = {ME});
CREATE POLICY threads_participant_delete ON threads FOR DELETE TO atlas_app
    USING ((opener_id = {ME} OR recipient_id = {ME})
           AND (COALESCE(last_message_at, created_at) < now() - interval '12 months'
                OR opener_id IS NULL OR recipient_id IS NULL));
GRANT SELECT, INSERT, DELETE ON threads TO atlas_app;
GRANT UPDATE (status, last_message_at) ON threads TO atlas_app;

CREATE POLICY thread_reads_owner ON thread_reads TO atlas_app
    USING (user_id = {ME})
    WITH CHECK (user_id = {ME} AND EXISTS (SELECT 1 FROM threads t WHERE t.id = thread_id));
GRANT SELECT, INSERT, UPDATE, DELETE ON thread_reads TO atlas_app;

CREATE POLICY messages_participant ON messages FOR SELECT TO atlas_app
    USING (EXISTS (SELECT 1 FROM threads t WHERE t.id = thread_id));
CREATE POLICY messages_send ON messages FOR INSERT TO atlas_app
    WITH CHECK (sender_id = {ME} AND EXISTS (
        SELECT 1 FROM threads t
         WHERE t.id = thread_id AND t.status = 'open'
           AND t.opener_id IS NOT NULL AND t.recipient_id IS NOT NULL
           AND NOT public.messaging_blocked(t.opener_id, t.recipient_id)));
CREATE POLICY messages_own_delete ON messages FOR DELETE TO atlas_app
    USING (sender_id = {ME});
GRANT SELECT, INSERT, DELETE ON messages TO atlas_app;

CREATE POLICY blocks_owner ON blocks TO atlas_app
    USING (user_id = {ME}) WITH CHECK (user_id = {ME} AND blocked_user_id <> {ME});
GRANT SELECT, INSERT, DELETE ON blocks TO atlas_app;

CREATE POLICY reports_owner ON reports TO atlas_app
    USING (user_id = {ME})
    WITH CHECK (user_id = {ME} AND EXISTS (SELECT 1 FROM threads t WHERE t.id = thread_id));
GRANT SELECT, INSERT, DELETE ON reports TO atlas_app;

-- The functions' owner reads and writes only what they need.
GRANT SELECT (user_id, blocked_user_id) ON blocks TO atlas_definer;
GRANT SELECT, INSERT ON threads TO atlas_definer;
GRANT SELECT, INSERT ON messages TO atlas_definer;
GRANT SELECT, INSERT ON thread_reads TO atlas_definer;
CREATE POLICY blocks_definer ON blocks FOR SELECT TO atlas_definer USING (true);
CREATE POLICY threads_definer ON threads TO atlas_definer USING (true) WITH CHECK (true);
CREATE POLICY messages_definer ON messages TO atlas_definer USING (true) WITH CHECK (true);
CREATE POLICY thread_reads_definer ON thread_reads TO atlas_definer
    USING (true) WITH CHECK (true);

-- Operator CLI (atlas_owner): reported threads (logged), key rotation, 12-month clean-up.
CREATE POLICY threads_operator ON threads TO atlas_owner USING (true) WITH CHECK (true);
CREATE POLICY messages_operator ON messages TO atlas_owner USING (true) WITH CHECK (true);
CREATE POLICY reports_operator ON reports TO atlas_owner USING (true) WITH CHECK (true);
REVOKE ALL ON admin_access_log FROM atlas_app, atlas_definer, atlas_pipeline;
"""

FUNCTIONS_SQL = f"""
CREATE FUNCTION public.messaging_blocked(a uuid, b uuid)
RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT CASE WHEN {ME} IS NOT NULL AND {ME} IN (a, b) THEN EXISTS (
        SELECT 1 FROM blocks k
         WHERE (k.user_id = a AND k.blocked_user_id = b)
            OR (k.user_id = b AND k.blocked_user_id = a)) ELSE false END
$$;

CREATE FUNCTION public.open_card_thread(
    p_card_id uuid, p_opener_name text, p_body bytea, p_guardian_version text,
    p_daily_limit int)
RETURNS TABLE (thread_id uuid, recipient_name text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    me uuid := {ME};
    opener_role text;
    rid uuid;
    rname text;
    tid uuid;
BEGIN
    IF me IS NULL THEN
        RAISE EXCEPTION 'amber:sign_in';
    END IF;
    SELECT p.role INTO opener_role FROM profiles p WHERE p.user_id = me;
    IF opener_role IS DISTINCT FROM 'patient' THEN
        RAISE EXCEPTION 'amber:not_patient';
    END IF;
    SELECT p.user_id, {CARD_NAME} INTO rid, rname
      FROM profiles p
     WHERE p.card_id = p_card_id AND p.card_visible AND p.role_verified
       AND p.role IN ('doctor', 'researcher') AND p.verification_method IS NOT NULL
       AND p.accepts_patient_messages AND {CARD_NAME} IS NOT NULL;
    IF rid IS NULL OR rid = me OR EXISTS (
        SELECT 1 FROM blocks k
         WHERE (k.user_id = me AND k.blocked_user_id = rid)
            OR (k.user_id = rid AND k.blocked_user_id = me)) THEN
        RAISE EXCEPTION 'amber:not_available';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('amber-threads:' || me::text, 0));
    IF EXISTS (SELECT 1 FROM threads t
                WHERE t.opener_id = me AND t.recipient_id = rid
                  AND t.status IN ('requested', 'open', 'blocked')) THEN
        RAISE EXCEPTION 'amber:exists';
    END IF;
    IF (SELECT count(*) FROM threads t
         WHERE t.opener_id = me AND t.created_at > now() - interval '1 day') >= p_daily_limit THEN
        RAISE EXCEPTION 'amber:limit';
    END IF;
    INSERT INTO threads (opener_id, recipient_id, origin, recipient_card_id, opener_name,
                         recipient_name, status, last_message_at)
    VALUES (me, rid, 'card', p_card_id, p_opener_name, rname, 'requested', now())
    RETURNING id INTO tid;
    INSERT INTO messages (thread_id, sender_id, body_enc) VALUES (tid, me, p_body);
    INSERT INTO thread_reads (thread_id, user_id, last_read_at, guardian_agreed_at,
                              guardian_text_version)
    VALUES (tid, me, now(), CASE WHEN p_guardian_version IS NOT NULL THEN now() END,
            p_guardian_version);
    RETURN QUERY SELECT tid, rname;
END
$$;

CREATE FUNCTION public.threads_guard()
RETURNS trigger
LANGUAGE plpgsql SET search_path = public, pg_temp
AS $$
DECLARE
    me uuid := {ME};
    reopened text;
BEGIN
    -- A participant's account was deleted (ON DELETE SET NULL): forget their name, close.
    IF OLD.opener_id IS NOT NULL AND NEW.opener_id IS NULL THEN
        NEW.opener_name := NULL;
    END IF;
    IF OLD.recipient_id IS NOT NULL AND NEW.recipient_id IS NULL THEN
        NEW.recipient_name := NULL;
        NEW.recipient_card_id := NULL;
    END IF;
    IF NEW.opener_id IS NULL OR NEW.recipient_id IS NULL THEN
        IF NEW.status IN ('requested', 'open', 'blocked') THEN
            NEW.status := 'closed';
            NEW.closed_at := now();
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.status IS NOT DISTINCT FROM OLD.status OR me IS NULL THEN
        RETURN NEW;
    END IF;
    reopened := CASE WHEN OLD.accepted_at IS NOT NULL OR OLD.origin = 'signup'
                     THEN 'open' ELSE 'requested' END;
    IF OLD.status = 'requested' AND NEW.status = 'open' AND me = OLD.recipient_id THEN
        NEW.accepted_at := now();
    ELSIF OLD.status = 'requested' AND NEW.status = 'declined' AND me = OLD.recipient_id THEN
        NEW.closed_at := now();
    ELSIF OLD.status IN ('requested', 'open', 'blocked') AND NEW.status = 'closed' THEN
        NEW.closed_at := now();
    ELSIF OLD.status IN ('requested', 'open') AND NEW.status = 'blocked'
          AND public.messaging_blocked(OLD.opener_id, OLD.recipient_id) THEN
        NULL;
    ELSIF OLD.status = 'blocked' AND NEW.status = reopened
          AND NOT public.messaging_blocked(OLD.opener_id, OLD.recipient_id) THEN
        NULL;
    ELSE
        RAISE EXCEPTION 'amber:transition' USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$;

CREATE TRIGGER threads_guard BEFORE UPDATE ON threads
    FOR EACH ROW EXECUTE FUNCTION public.threads_guard();

ALTER FUNCTION public.messaging_blocked(uuid, uuid) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.messaging_blocked(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.messaging_blocked(uuid, uuid) TO atlas_app;
ALTER FUNCTION public.open_card_thread(uuid, text, bytea, text, int) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.open_card_thread(uuid, text, bytea, text, int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.open_card_thread(uuid, text, bytea, text, int) TO atlas_app;
REVOKE ALL ON FUNCTION public.threads_guard() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.threads_guard() TO atlas_app, atlas_definer;
"""


def upgrade() -> None:
    op.add_column("profiles", sa.Column("connect_age_group", sa.Text()))
    op.add_column("profiles", sa.Column("connect_age_group_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_profiles_connect_age_group", "profiles", "connect_age_group IN ('18_plus', '16_17')"
    )

    op.create_table(
        "threads",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("opener_id", sa.UUID(), nullable=True),
        sa.Column("recipient_id", sa.UUID(), nullable=True),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("call_id", sa.UUID(), nullable=True),
        sa.Column("signup_id", sa.UUID(), nullable=True),
        sa.Column("recipient_card_id", sa.UUID(), nullable=True),
        sa.Column("opener_name", sa.Text(), nullable=True),
        sa.Column("recipient_name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="requested", nullable=False),
        _created(),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("origin IN ('card', 'signup')", name="ck_threads_origin"),
        sa.CheckConstraint(
            "status IN ('requested', 'open', 'declined', 'closed', 'blocked')",
            name="ck_threads_status",
        ),
        sa.CheckConstraint(
            "origin <> 'signup' OR (call_id IS NOT NULL AND signup_id IS NOT NULL)",
            name="ck_threads_signup_refs",
        ),
        sa.CheckConstraint("opener_id <> recipient_id", name="ck_threads_two_people"),
        sa.CheckConstraint(
            "char_length(opener_name) BETWEEN 1 AND 60", name="ck_threads_opener_name_length"
        ),
        sa.CheckConstraint(
            "char_length(recipient_name) BETWEEN 1 AND 200",
            name="ck_threads_recipient_name_length",
        ),
        sa.ForeignKeyConstraint(["opener_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_threads_opener_id", "threads", ["opener_id"], unique=False)
    op.create_index("ix_threads_recipient_id", "threads", ["recipient_id"], unique=False)

    op.create_table(
        "thread_reads",
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("last_read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guardian_agreed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guardian_text_version", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "(guardian_agreed_at IS NULL) = (guardian_text_version IS NULL)",
            name="ck_thread_reads_guardian_pair",
        ),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("thread_id", "user_id"),
    )
    op.create_index("ix_thread_reads_user_id", "thread_reads", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=False),
        sa.Column("sender_id", sa.UUID(), nullable=False),
        sa.Column("body_enc", sa.LargeBinary(), nullable=False),
        _created(),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_thread_created", "messages", ["thread_id", "created_at"], unique=False
    )
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"], unique=False)

    op.create_table(
        "blocks",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("blocked_user_id", sa.UUID(), nullable=False),
        sa.Column("blocked_name", sa.Text(), nullable=True),
        _created(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["blocked_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "blocked_user_id", name="uq_blocks_pair"),
    )
    op.create_index("ix_blocks_blocked_user_id", "blocks", ["blocked_user_id"], unique=False)

    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authorization_version", sa.Text(), nullable=False),
        sa.Column(
            "authorized_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        _created(),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "reason IN ('harassment', 'spam', 'medical_advice', 'impersonation', 'other')",
            name="ck_reports_reason",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["thread_id"], ["threads.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_user_id", "reports", ["user_id"], unique=False)
    op.create_index("ix_reports_thread_id", "reports", ["thread_id"], unique=False)

    op.create_table(
        "admin_access_log",
        sa.Column("id", sa.UUID(), server_default=sa.func.gen_random_uuid(), nullable=False),
        sa.Column("operator", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("report_id", sa.UUID(), nullable=True),
        sa.Column("thread_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        _created(),
        sa.CheckConstraint(
            "char_length(operator) BETWEEN 1 AND 100", name="ck_admin_access_log_operator"
        ),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 10 AND 500", name="ck_admin_access_log_reason"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;"
        )
    # messaging_blocked() must exist before the policy that calls it.
    op.execute(FUNCTIONS_SQL)
    op.execute(POLICIES_SQL)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS threads_guard ON threads")
    op.drop_table("admin_access_log")
    op.drop_table("reports")
    op.drop_table("blocks")
    op.drop_table("messages")
    op.drop_table("thread_reads")
    op.drop_table("threads")
    op.execute("DROP FUNCTION IF EXISTS public.threads_guard()")
    op.execute("DROP FUNCTION IF EXISTS public.open_card_thread(uuid, text, bytea, text, int)")
    op.execute("DROP FUNCTION IF EXISTS public.messaging_blocked(uuid, uuid)")
    op.drop_constraint("ck_profiles_connect_age_group", "profiles", type_="check")
    op.drop_column("profiles", "connect_age_group_at")
    op.drop_column("profiles", "connect_age_group")
