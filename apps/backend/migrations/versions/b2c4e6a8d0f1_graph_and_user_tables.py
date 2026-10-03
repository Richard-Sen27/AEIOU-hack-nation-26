"""graph and user tables

Revision ID: b2c4e6a8d0f1
Revises: acf47917b108
Create Date: 2026-10-03 23:56:49.035026

"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b2c4e6a8d0f1"
down_revision: str | Sequence[str] | None = "acf47917b108"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GRAPH_TABLES = (
    "clusters",
    "nodes",
    "node_synonyms",
    "edges",
    "evidence",
    "explanations_cache",
    "ingestion_runs",
)
USER_TABLES = (
    "users",
    "openai_tokens",
    "profiles",
    "consents",
    "patient_profiles",
    "chat_sessions",
    "chat_messages",
    "documents",
    "findings",
    "contributions",
    "edge_flags",
    "jobs",
)
APP_USER = "nullif(current_setting('app.user_id', true), '')::uuid"

PRE_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

CREATE OR REPLACE FUNCTION public.f_unaccent(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$;
"""

INDEX_SQL = """
CREATE INDEX ix_node_synonyms_synonym_trgm
    ON node_synonyms USING gin (public.f_unaccent(lower(synonym)) gin_trgm_ops);
CREATE INDEX ix_nodes_label_trgm
    ON nodes USING gin (public.f_unaccent(lower(label)) gin_trgm_ops);
"""

GRANT_SQL = f"""
GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {", ".join(GRAPH_TABLES)} TO atlas_pipeline;
GRANT USAGE, SELECT, UPDATE ON SEQUENCE node_synonyms_id_seq, evidence_id_seq TO atlas_pipeline;
GRANT SELECT ON {", ".join(GRAPH_TABLES)} TO atlas_app;
GRANT INSERT, UPDATE ON explanations_cache TO atlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(USER_TABLES)} TO atlas_app;
"""

# atlas_definer owns the SECURITY DEFINER functions; it gets only what they need.
DEFINER_SQL = """
GRANT SELECT, INSERT ON users TO atlas_definer;
GRANT UPDATE (email, name, last_login_at) ON users TO atlas_definer;
GRANT SELECT, INSERT ON profiles TO atlas_definer;
GRANT SELECT (edge_id, status) ON edge_flags TO atlas_definer;
GRANT SELECT (id, kind, payload, status, created_at, consent_id) ON contributions TO atlas_definer;
GRANT SELECT (id, consent_type, revoked_at) ON consents TO atlas_definer;

CREATE POLICY users_definer ON users TO atlas_definer USING (true) WITH CHECK (true);
CREATE POLICY profiles_definer ON profiles TO atlas_definer USING (true) WITH CHECK (true);
CREATE POLICY edge_flags_definer ON edge_flags FOR SELECT TO atlas_definer USING (true);
CREATE POLICY contributions_definer ON contributions FOR SELECT TO atlas_definer USING (true);
CREATE POLICY consents_definer ON consents FOR SELECT TO atlas_definer USING (true);

CREATE FUNCTION public.auth_find_or_create_user(sub text, email text, name text)
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

CREATE FUNCTION public.edge_flag_counts()
RETURNS TABLE (edge_id text, open_flags int)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT f.edge_id, count(*)::int FROM edge_flags f WHERE f.status = 'open' GROUP BY f.edge_id
$$;

CREATE FUNCTION public.shared_contributions()
RETURNS TABLE (id uuid, kind text, payload jsonb, status text, created_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp
AS $$
    SELECT c.id, c.kind, c.payload, c.status, c.created_at
      FROM contributions c JOIN consents k ON k.id = c.consent_id
     WHERE k.consent_type = 'contribute' AND k.revoked_at IS NULL
     ORDER BY c.created_at DESC
$$;
"""

DEFINER_FUNCTIONS = (
    "auth_find_or_create_user(text, text, text)",
    "edge_flag_counts()",
    "shared_contributions()",
)


def _rls_sql() -> str:
    parts = []
    for table in USER_TABLES:
        column = "id" if table == "users" else "user_id"
        parts.append(
            f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;\n"
            f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;\n"
            f"CREATE POLICY {table}_owner ON {table}"
            f" USING ({column} = {APP_USER}) WITH CHECK ({column} = {APP_USER});"
        )
    return "\n".join(parts)


def _function_ownership_sql() -> str:
    parts = []
    for fn in DEFINER_FUNCTIONS:
        parts.append(f"ALTER FUNCTION public.{fn} OWNER TO atlas_definer;")
        parts.append(f"REVOKE ALL ON FUNCTION public.{fn} FROM PUBLIC;")
        parts.append(f"GRANT EXECUTE ON FUNCTION public.{fn} TO atlas_app;")
    return "\n".join(parts)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute(PRE_SQL)
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "clusters",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("mechanism_summary", sa.Text(), nullable=True),
        sa.Column("member_count", sa.Integer(), nullable=True),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("data_version", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "explanations_cache",
        sa.Column("path_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("path_id", "role", "language", "data_version"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("data_version", sa.Text(), nullable=False),
        sa.Column("pipeline_commit", sa.Text(), nullable=True),
        sa.Column("source_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("data_version"),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "attrs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("cluster_id", sa.Text(), nullable=True),
        sa.Column("x", sa.Float(), nullable=True),
        sa.Column("y", sa.Float(), nullable=True),
        sa.Column("centrality", sa.Float(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("data_version", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_nodes_cluster_id", "nodes", ["cluster_id"], unique=False)
    op.create_index(
        "ix_nodes_embedding_hnsw",
        "nodes",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index("ix_nodes_type", "nodes", ["type"], unique=False)
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("chatgpt_sub", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chatgpt_sub"),
    )
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_sessions_user_id"), "chat_sessions", ["user_id"], unique=False)
    op.create_table(
        "consents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("consent_type", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("about_child", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "parental_responsibility_confirmed",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_consents_user_id"), "consents", ["user_id"], unique=False)
    op.create_index(
        "uq_consents_active",
        "consents",
        ["user_id", "consent_type"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("doc_type", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("raw_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_user_id"), "documents", ["user_id"], unique=False)
    op.create_table(
        "edge_flags",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("edge_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edge_flags_edge_id", "edge_flags", ["edge_id"], unique=False)
    op.create_index(op.f("ix_edge_flags_user_id"), "edge_flags", ["user_id"], unique=False)
    op.create_index(
        "uq_edge_flags_open",
        "edge_flags",
        ["edge_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_table(
        "edges",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("relation", sa.Text(), nullable=False),
        sa.Column("family", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("data_version", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["nodes.id"],
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["nodes.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_edges_source_id", "edges", ["source_id"], unique=False)
    op.create_index("ix_edges_target_id", "edges", ["target_id"], unique=False)
    op.create_table(
        "node_synonyms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False),
        sa.Column("synonym", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_node_synonyms_node_id"), "node_synonyms", ["node_id"], unique=False)
    op.create_table(
        "openai_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("client_id", sa.Text(), nullable=True),
        sa.Column("access_token_enc", sa.Text(), nullable=True),
        sa.Column("refresh_token_enc", sa.Text(), nullable=True),
        sa.Column("id_token_enc", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "patient_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "profile",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("role_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("orcid_id", sa.Text(), nullable=True),
        sa.Column("language", sa.Text(), server_default="en", nullable=False),
        sa.Column("gpc_opt_out", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("expert_mode", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("age_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reply", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_chat_messages_session_id"), "chat_messages", ["session_id"], unique=False
    )
    op.create_index(op.f("ix_chat_messages_user_id"), "chat_messages", ["user_id"], unique=False)
    op.create_table(
        "contributions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), server_default="pending_review", nullable=False),
        sa.Column("consent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["consent_id"], ["consents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_contributions_consent_id"), "contributions", ["consent_id"], unique=False
    )
    op.create_index(op.f("ix_contributions_user_id"), "contributions", ["user_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("edge_id", sa.Text(), nullable=False),
        sa.Column("tier", sa.Text(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("polarity", sa.Text(), server_default="supports", nullable=False),
        sa.Column("claim_type", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["edge_id"], ["edges.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_edge_id", "evidence", ["edge_id"], unique=False)
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_id", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("confirmed", sa.Boolean(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_findings_document_id"), "findings", ["document_id"], unique=False)
    op.create_index(op.f("ix_findings_user_id"), "findings", ["user_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("document_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_document_id"), "jobs", ["document_id"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    # ### end Alembic commands ###
    op.execute(INDEX_SQL)
    op.execute(GRANT_SQL)
    op.execute(_rls_sql())
    op.execute(DEFINER_SQL)
    op.execute(_function_ownership_sql())


def downgrade() -> None:
    """Downgrade schema."""
    for fn in DEFINER_FUNCTIONS:
        op.execute(f"DROP FUNCTION IF EXISTS public.{fn}")
    op.execute("DROP INDEX IF EXISTS ix_node_synonyms_synonym_trgm")
    op.execute("DROP INDEX IF EXISTS ix_nodes_label_trgm")
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_document_id"), table_name="jobs")
    op.drop_table("jobs")
    op.drop_index(op.f("ix_findings_user_id"), table_name="findings")
    op.drop_index(op.f("ix_findings_document_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_evidence_edge_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index(op.f("ix_contributions_user_id"), table_name="contributions")
    op.drop_index(op.f("ix_contributions_consent_id"), table_name="contributions")
    op.drop_table("contributions")
    op.drop_index(op.f("ix_chat_messages_user_id"), table_name="chat_messages")
    op.drop_index(op.f("ix_chat_messages_session_id"), table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("profiles")
    op.drop_table("patient_profiles")
    op.drop_table("openai_tokens")
    op.drop_index(op.f("ix_node_synonyms_node_id"), table_name="node_synonyms")
    op.drop_table("node_synonyms")
    op.drop_index("ix_edges_target_id", table_name="edges")
    op.drop_index("ix_edges_source_id", table_name="edges")
    op.drop_table("edges")
    op.drop_index(
        "uq_edge_flags_open", table_name="edge_flags", postgresql_where=sa.text("status = 'open'")
    )
    op.drop_index(op.f("ix_edge_flags_user_id"), table_name="edge_flags")
    op.drop_index("ix_edge_flags_edge_id", table_name="edge_flags")
    op.drop_table("edge_flags")
    op.drop_index(op.f("ix_documents_user_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(
        "uq_consents_active", table_name="consents", postgresql_where=sa.text("revoked_at IS NULL")
    )
    op.drop_index(op.f("ix_consents_user_id"), table_name="consents")
    op.drop_table("consents")
    op.drop_index(op.f("ix_chat_sessions_user_id"), table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_table("users")
    op.drop_index("ix_nodes_type", table_name="nodes")
    op.drop_index(
        "ix_nodes_embedding_hnsw",
        table_name="nodes",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_nodes_cluster_id", table_name="nodes")
    op.drop_table("nodes")
    op.drop_table("ingestion_runs")
    op.drop_table("explanations_cache")
    op.drop_table("clusters")
    # ### end Alembic commands ###
    op.execute("DROP FUNCTION IF EXISTS public.f_unaccent(text)")
