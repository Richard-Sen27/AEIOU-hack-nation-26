"""sign-in providers: users keyed by (auth_provider, auth_subject)

Existing users become provider "openai" with their ChatGPT subject. A Google account and a
ChatGPT account with the same e-mail address stay two accounts: nothing is merged by e-mail.

Revision ID: f3b8d2a6c4e1
Revises: e7a1c3d5f9b2
Create Date: 2026-10-04 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f3b8d2a6c4e1"
down_revision: str | Sequence[str] | None = "e7a1c3d5f9b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPGRADE_SQL = """
ALTER TABLE users RENAME COLUMN chatgpt_sub TO auth_subject;
ALTER TABLE users ADD COLUMN auth_provider text NOT NULL DEFAULT 'openai';
ALTER TABLE users ALTER COLUMN auth_provider DROP DEFAULT;
ALTER TABLE users ADD CONSTRAINT ck_users_auth_provider
    CHECK (auth_provider IN ('openai', 'google'));
ALTER TABLE users DROP CONSTRAINT users_chatgpt_sub_key;
ALTER TABLE users ADD CONSTRAINT uq_users_auth_provider_subject
    UNIQUE (auth_provider, auth_subject);

CREATE FUNCTION public.auth_find_or_create_user(provider text, sub text, email text, name text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    uid uuid;
BEGIN
    IF provider IS NULL OR provider NOT IN ('openai', 'google') THEN
        RAISE EXCEPTION 'unknown provider';
    END IF;
    IF sub IS NULL OR length(sub) = 0 THEN
        RAISE EXCEPTION 'sub is required';
    END IF;
    INSERT INTO users AS u (auth_provider, auth_subject, email, name, last_login_at)
    VALUES (provider, sub, email, name, now())
    ON CONFLICT (auth_provider, auth_subject) DO UPDATE
        SET email = EXCLUDED.email, name = EXCLUDED.name, last_login_at = now()
    RETURNING u.id INTO uid;
    INSERT INTO profiles (user_id) VALUES (uid) ON CONFLICT (user_id) DO NOTHING;
    RETURN uid;
END
$$;
ALTER FUNCTION public.auth_find_or_create_user(text, text, text, text) OWNER TO atlas_definer;
REVOKE ALL ON FUNCTION public.auth_find_or_create_user(text, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.auth_find_or_create_user(text, text, text, text) TO atlas_app;

-- The three-argument form stays as the ChatGPT ("openai") sign-in.
CREATE OR REPLACE FUNCTION public.auth_find_or_create_user(sub text, email text, name text)
RETURNS uuid
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp
AS $$ SELECT public.auth_find_or_create_user('openai', sub, email, name) $$;
"""

DOWNGRADE_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM users WHERE auth_provider <> 'openai') THEN
        RAISE EXCEPTION 'users signed in with another provider exist; delete them first';
    END IF;
END
$$;
CREATE OR REPLACE FUNCTION public.auth_find_or_create_user(sub text, email text, name text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
AS $$
DECLARE
    uid uuid;
BEGIN
    IF sub IS NULL OR length(sub) = 0 THEN
        RAISE EXCEPTION 'sub is required';
    END IF;
    INSERT INTO users AS u (chatgpt_sub, email, name, last_login_at)
    VALUES (sub, email, name, now())
    ON CONFLICT (chatgpt_sub) DO UPDATE
        SET email = EXCLUDED.email, name = EXCLUDED.name, last_login_at = now()
    RETURNING u.id INTO uid;
    INSERT INTO profiles (user_id) VALUES (uid) ON CONFLICT (user_id) DO NOTHING;
    RETURN uid;
END
$$;
DROP FUNCTION public.auth_find_or_create_user(text, text, text, text);
ALTER TABLE users DROP CONSTRAINT uq_users_auth_provider_subject;
ALTER TABLE users DROP CONSTRAINT ck_users_auth_provider;
ALTER TABLE users DROP COLUMN auth_provider;
ALTER TABLE users RENAME COLUMN auth_subject TO chatgpt_sub;
ALTER TABLE users ADD CONSTRAINT users_chatgpt_sub_key UNIQUE (chatgpt_sub);
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
