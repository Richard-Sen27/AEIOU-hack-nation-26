"""SQLAlchemy models for every table (Alembic autogenerate target).

Graph tables are written only by the pipeline (atlas_pipeline) and read by the API.
User tables are protected by row-level security; see the migrations for policies and grants.
User tables never reference graph tables (the pipeline truncates and reloads the graph).
"""

import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBEDDING_DIM = 384


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSONB,
        datetime: DateTime(timezone=True),
    }


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )


def _user_fk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


def _created() -> Mapped[datetime]:
    return mapped_column(server_default=func.now(), nullable=False)


# --- graph tables ------------------------------------------------------------------------


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)
    mechanism_summary: Mapped[str | None] = mapped_column(Text)
    member_count: Mapped[int | None] = mapped_column(Integer)
    attrs: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    data_version: Mapped[str | None] = mapped_column(Text)


class Node(Base):
    __tablename__ = "nodes"
    __table_args__ = (
        Index("ix_nodes_type", "type"),
        Index("ix_nodes_cluster_id", "cluster_id"),
        Index(
            "ix_nodes_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    cluster_id: Mapped[str | None] = mapped_column(Text)
    x: Mapped[float | None] = mapped_column(Float)
    y: Mapped[float | None] = mapped_column(Float)
    centrality: Mapped[float | None] = mapped_column(Float)
    embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    data_version: Mapped[str | None] = mapped_column(Text)


class NodeSynonym(Base):
    __tablename__ = "node_synonyms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    node_id: Mapped[str] = mapped_column(
        Text, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    synonym: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text)


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        Index("ix_edges_source_id", "source_id"),
        Index("ix_edges_target_id", "target_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("nodes.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("nodes.id"), nullable=False)
    relation: Mapped[str] = mapped_column(Text, nullable=False)
    family: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    origin: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    features: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    data_version: Mapped[str | None] = mapped_column(Text)


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (Index("ix_evidence_edge_id", "edge_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    edge_id: Mapped[str] = mapped_column(
        Text, ForeignKey("edges.id", ondelete="CASCADE"), nullable=False
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    quote: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime | None] = mapped_column()
    polarity: Mapped[str] = mapped_column(Text, nullable=False, server_default="supports")
    claim_type: Mapped[str | None] = mapped_column(Text)


class ExplanationCache(Base):
    __tablename__ = "explanations_cache"
    __table_args__ = (PrimaryKeyConstraint("path_id", "role", "language", "data_version"),)

    path_id: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text)
    data_version: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[Any] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = _created()


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    data_version: Mapped[str] = mapped_column(Text, primary_key=True)
    pipeline_commit: Mapped[str | None] = mapped_column(Text)
    source_versions: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    counts: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class HpoTerm(Base):
    """One HPO term under HP:0000118 (graph nodes or not): read into memory at startup to
    resolve symptom mentions and to rank diseases by symptom overlap."""

    __tablename__ = "hpo_terms"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    parents: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )  # direct is_a parents
    ic: Mapped[float | None] = mapped_column(Float)  # null: annotates nothing in the corpus


class GraphChange(Base):
    """What a pipeline load added around a disease (for later in-app notifications). Written by
    the pipeline, read-only for the API; nothing reads it yet."""

    __tablename__ = "graph_changes"
    __table_args__ = (PrimaryKeyConstraint("data_version", "disease_id", "node_id", "change"),)

    data_version: Mapped[str] = mapped_column(Text)
    previous_version: Mapped[str | None] = mapped_column(Text)
    disease_id: Mapped[str] = mapped_column(Text)
    node_id: Mapped[str] = mapped_column(Text)
    node_type: Mapped[str] = mapped_column(Text, nullable=False)
    change: Mapped[str] = mapped_column(Text)
    edge_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


GRAPH_TABLES = (
    "clusters",
    "nodes",
    "node_synonyms",
    "edges",
    "evidence",
    "explanations_cache",
    "ingestion_runs",
    "hpo_terms",
    "graph_changes",
)


# --- user tables (RLS) -------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    chatgpt_sub: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[datetime | None] = mapped_column()


class OpenAIToken(Base):
    """Encrypted (Fernet) OpenAI tokens, used to bill LLM calls to the user's ChatGPT plan."""

    __tablename__ = "openai_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    client_id: Mapped[str | None] = mapped_column(Text)
    access_token_enc: Mapped[str | None] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    id_token_enc: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column()
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(Text)
    role_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    orcid_id: Mapped[str | None] = mapped_column(Text)
    # Optional private work details (doctor and researcher roles only; never sent to a model).
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str | None] = mapped_column(Text)
    institutions: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    atlas_node_id: Mapped[str | None] = mapped_column(Text)
    professional_updated_at: Mapped[datetime | None] = mapped_column()
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    gpc_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expert_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    age_confirmed_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ConsentRecord(Base):
    __tablename__ = "consents"
    __table_args__ = (
        Index(
            "uq_consents_active",
            "user_id",
            "consent_type",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    consent_type: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column()
    about_child: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    parental_responsibility_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )


class PatientProfileRecord(Base):
    __tablename__ = "patient_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    profile: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb")
    )
    updated_at: Mapped[datetime] = _created()


class ChatSessionRecord(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class ChatMessageRecord(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # redacted text only
    reply: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class DocumentRecord(Base):
    """Document metadata only: no filename, no raw bytes."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    doc_type: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()
    raw_deleted_at: Mapped[datetime | None] = mapped_column()


class FindingRecord(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = _user_fk()
    type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_id: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    snippet: Mapped[str | None] = mapped_column(Text)
    confirmed: Mapped[bool | None] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb")
    )
    decided_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = _created()


class ContributionRecord(Base):
    __tablename__ = "contributions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_review")
    consent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consents.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class EdgeFlagRecord(Base):
    """User flag on a graph edge. edge_id is not a foreign key (graph reloads)."""

    __tablename__ = "edge_flags"
    __table_args__ = (
        Index("ix_edge_flags_edge_id", "edge_id"),
        Index(
            "uq_edge_flags_open",
            "edge_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    edge_id: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[uuid.UUID] = _user_fk()
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class JobRecord(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)  # error code only, never content
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


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
