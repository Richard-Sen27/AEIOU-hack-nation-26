"""SQLAlchemy models for every table (Alembic autogenerate target).

Graph tables are written only by the pipeline (atlas_pipeline) and read by the API.
User tables are protected by row-level security; see the migrations for policies and grants.
User tables never reference graph tables (the pipeline truncates and reloads the graph).
"""

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
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
    """What a pipeline load added around a disease. Written by the pipeline, read-only for the
    API, which turns rows for followed diseases into the user's notifications."""

    __tablename__ = "graph_changes"
    __table_args__ = (
        PrimaryKeyConstraint("data_version", "disease_id", "node_id", "change"),
        Index("ix_graph_changes_disease", "disease_id", "created_at"),
        Index("ix_graph_changes_created_at", "created_at"),
    )

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
    """One account per sign-in identity: (auth_provider, auth_subject). Never merged by e-mail."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "auth_subject", name="uq_users_auth_provider_subject"),
        CheckConstraint("auth_provider IN ('openai', 'google')", name="ck_users_auth_provider"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False)  # "openai" | "google"
    auth_subject: Mapped[str] = mapped_column(Text, nullable=False)  # the provider's `sub`
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
    # Verification and the opt-in public card (contract basis; off by default). Other users see
    # a card only through professional_cards(), only while card_visible AND role_verified.
    orcid_verified_at: Mapped[datetime | None] = mapped_column()
    verified_name: Mapped[str | None] = mapped_column(Text)  # from ORCID or the reviewer
    verification_method: Mapped[str | None] = mapped_column(Text)
    verified_at: Mapped[datetime | None] = mapped_column()
    verification_reason: Mapped[str | None] = mapped_column(Text)  # operator's logged reason
    verification_request: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    atlas_link_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    card_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # opaque, public
    card_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    card_visible_since: Mapped[datetime | None] = mapped_column()
    card_headline: Mapped[str | None] = mapped_column(Text)
    card_show_institutions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    card_show_atlas_entry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    accepts_patient_messages: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )  # stored flag only; messaging is not built
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    gpc_opt_out: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    expert_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    age_confirmed_at: Mapped[datetime | None] = mapped_column()
    # Self-declared at the first connect action ('18_plus' | '16_17'), correctable; held under
    # the connect consent and cleared when it is withdrawn.
    connect_age_group: Mapped[str | None] = mapped_column(Text)
    connect_age_group_at: Mapped[datetime | None] = mapped_column()
    # Suggestions of calls (connect consent, off by default); computed per request, never stored.
    suggestions_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    suggestions_enabled_at: Mapped[datetime | None] = mapped_column()
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


class ChatRunRecord(Base):
    """An unfinished Dr. Wu turn and its latest LangGraph checkpoint (redacted content only).

    The row exists only while the turn runs: it is deleted in the same transaction that stores
    the reply or the failed turn, which also prunes the checkpoint."""

    __tablename__ = "chat_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = _user_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # at most one active run per session
    )
    user_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    worker: Mapped[str] = mapped_column(Text, nullable=False)  # boot id of the running process
    checkpoint_id: Mapped[str | None] = mapped_column(Text)
    checkpoint_type: Mapped[str | None] = mapped_column(Text)
    checkpoint: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


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


class FollowRecord(Base):
    """A disease the user follows (health data, held under the health_data consent)."""

    __tablename__ = "follows"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "node_id"),
        CheckConstraint("node_id ~ '^MONDO:[0-9]{7}$'", name="ck_follows_mondo_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    node_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    since_version: Mapped[str | None] = mapped_column(Text)  # data version live when followed


class NotificationRecord(Base):
    """In-app notification. No text: labels are resolved from the graph when read."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_dedupe"),
        Index("ix_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # added | now_recruiting
    ref_id: Mapped[str] = mapped_column(Text, nullable=False)  # the new item's node id
    subject_node_id: Mapped[str | None] = mapped_column(Text)  # the followed disease
    data_version: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column()


# --- messaging (connect consent; policies and functions in migration a4c7e9b2d6f8) -------------


class ThreadRecord(Base):
    """A conversation between a patient (opener) and a professional (recipient).

    Visible to both participants. Names are snapshots shown to the other side; a deleted
    account's id and name become NULL (the thread closes)."""

    __tablename__ = "threads"
    __table_args__ = (
        Index("ix_threads_opener_id", "opener_id"),
        Index("ix_threads_recipient_id", "recipient_id"),
        Index("ix_threads_signup_id", "signup_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    opener_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False)  # card | signup
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    signup_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("call_signups.id", ondelete="SET NULL", use_alter=True),  # cycle with threads
    )
    recipient_card_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opener_name: Mapped[str | None] = mapped_column(Text)
    recipient_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    created_at: Mapped[datetime] = _created()
    accepted_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()
    last_message_at: Mapped[datetime | None] = mapped_column()


class ThreadReadRecord(Base):
    """A participant's own read marker, hidden flag and guardian agreement (16-17) per thread."""

    __tablename__ = "thread_reads"
    __table_args__ = (
        PrimaryKeyConstraint("thread_id", "user_id"),
        Index("ix_thread_reads_user_id", "user_id"),
    )

    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    last_read_at: Mapped[datetime | None] = mapped_column()
    hidden_at: Mapped[datetime | None] = mapped_column()
    guardian_agreed_at: Mapped[datetime | None] = mapped_column()
    guardian_text_version: Mapped[str | None] = mapped_column(Text)


class MessageRecord(Base):
    """One message; the body is Fernet ciphertext (MESSAGE_ENCRYPTION_KEY)."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_thread_created", "thread_id", "created_at"),
        Index("ix_messages_sender_id", "sender_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    body_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _created()


class BlockRecord(Base):
    """The blocker's (user_id) block of another account; no messages either way."""

    __tablename__ = "blocks"
    __table_args__ = (
        UniqueConstraint("user_id", "blocked_user_id", name="uq_blocks_pair"),
        Index("ix_blocks_blocked_user_id", "blocked_user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    blocked_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    blocked_name: Mapped[str | None] = mapped_column(Text)  # snapshot from the thread
    created_at: Mapped[datetime] = _created()


class ReportRecord(Base):
    """A report of a thread by a participant; authorizes the operator to read that thread."""

    __tablename__ = "reports"
    __table_args__ = (
        Index("ix_reports_user_id", "user_id"),
        Index("ix_reports_thread_id", "thread_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL")
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    authorization_version: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = _created()
    created_at: Mapped[datetime] = _created()
    reviewed_at: Mapped[datetime | None] = mapped_column()


class AdminAccessLogRecord(Base):
    """Operator reads of reported threads (no API access; written by the CLI)."""

    __tablename__ = "admin_access_log"

    id: Mapped[uuid.UUID] = _uuid_pk()
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    report_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()


# User tables whose rows two people share (threads, messages) or that hang off a thread: FORCE
# row-level security with participant or owner policies, proven in tests/account/test_messaging.py
# (the generic owner-column checks over USER_TABLES do not fit them).
MESSAGING_TABLES = ("threads", "thread_reads", "messages", "blocks", "reports")


# --- calls (policies, trigger and functions in migration 247a1157973f) ----------------------


class CallRecord(Base):
    """A survey, study or trial looking for participants, owned by its publisher.

    Owner-only, except that every signed-in user may read published calls. Only the operator
    publishes or rejects (definer function review_call; the trigger calls_guard enforces it)."""

    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_publisher_id", "publisher_id"),
        Index("ix_calls_status", "status", "published_at"),
        Index("ix_calls_disease_ids", "disease_ids", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # survey | study | trial
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    participation: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_text: Mapped[str | None] = mapped_column(Text)
    disease_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    gene_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    phenotype_ids: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    min_age: Mapped[int | None] = mapped_column(Integer)
    max_age: Mapped[int | None] = mapped_column(Integer)
    children_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    countries: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    remote: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    run_by_label: Mapped[str | None] = mapped_column(Text)
    run_by_node_id: Mapped[str | None] = mapped_column(Text)  # atlas node, not a foreign key
    ethics_body: Mapped[str | None] = mapped_column(Text)
    ethics_reference: Mapped[str | None] = mapped_column(Text)
    registry_id: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    opens_at: Mapped[date | None] = mapped_column(Date)
    closes_at: Mapped[date | None] = mapped_column(Date)
    max_signups: Mapped[int | None] = mapped_column(Integer)
    requested_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    review_note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column()
    published_at: Mapped[datetime | None] = mapped_column()
    closed_at: Mapped[datetime | None] = mapped_column()
    demo: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


class CallReviewRecord(Base):
    """Operator log of call reviews (viewed, approved, rejected). Written only by the definer
    functions; the publisher can read the rows about their own calls."""

    __tablename__ = "call_reviews"
    __table_args__ = (
        Index("ix_call_reviews_call_id", "call_id"),
        Index("ix_call_reviews_publisher_id", "publisher_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    publisher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    operator: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created()


# --- sign-ups to calls (connect consent; policies, triggers and functions in d7f2a9c4e6b1) ----


class CallSignupRecord(Base):
    """A patient's sign-up to a published call with exactly the items they ticked.

    The patient has full access to their own rows (the trigger call_signups_guard allows only
    withdrawing and linking the sign-up's conversation); the call's publisher may read the
    sign-ups of their own calls; the publisher declines through decline_call_signup()."""

    __tablename__ = "call_signups"
    __table_args__ = (
        Index("ix_call_signups_patient_id", "patient_id"),
        Index("ix_call_signups_call_id", "call_id"),
        Index(
            "uq_call_signups_one_per_call",
            "call_id",
            "patient_id",
            unique=True,
            postgresql_where=text("status IN ('active', 'declined')"),
        ),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("calls.id", ondelete="SET NULL")
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    call_title_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    recipient_name: Mapped[str] = mapped_column(Text, nullable=False)  # named in the authorization
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    shared: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    about_child: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    note: Mapped[str | None] = mapped_column(Text)
    authorization_version: Mapped[str] = mapped_column(Text, nullable=False)
    authorized_at: Mapped[datetime] = _created()
    guardian_agreed_at: Mapped[datetime | None] = mapped_column()
    guardian_text_version: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    withdrawn_at: Mapped[datetime | None] = mapped_column()
    declined_at: Mapped[datetime | None] = mapped_column()
    call_ended_at: Mapped[datetime | None] = mapped_column()
    purge_after: Mapped[datetime | None] = mapped_column()
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("threads.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _created()


# Shared between the patient and the call's publisher, so outside the generic owner-column tests
# over USER_TABLES; FORCE row-level security proven in tests/account/test_signups.py.
SIGNUP_TABLES = ("call_signups",)


USER_TABLES = (
    "users",
    "openai_tokens",
    "profiles",
    "consents",
    "patient_profiles",
    "chat_sessions",
    "chat_messages",
    "chat_runs",
    "documents",
    "findings",
    "contributions",
    "edge_flags",
    "jobs",
    "follows",
    "notifications",
    "calls",
)
