import re
import unicodedata
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, ValidationInfo, field_validator, model_validator

from backend.schemas.chat import ChatMessage, ChatRunExport, ChatSession
from backend.schemas.common import LANGUAGE_PATTERN, ApiModel
from backend.schemas.contributions import Contribution, EdgeFlag
from backend.schemas.documents import Document, Finding, Job
from backend.schemas.enums import ConsentType, NodeType, Role
from backend.schemas.follows import FollowExport, NotificationExport
from backend.schemas.profile import PatientProfile


class CurrentUser(ApiModel):
    """The signed-in user as resolved by get_optional_user (server-side only)."""

    id: UUID
    role: Role | None = Field(None, description="Null until the user picks a role.")
    role_verified: bool = False
    language: str = "en"
    expert_mode: bool = False
    age_confirmed: bool = False
    gpc_opt_out: bool = False


class Consent(ApiModel):
    id: UUID
    consent_type: ConsentType
    version: str = Field(description="Version of the consent text the user agreed to.")
    granted_at: datetime
    revoked_at: datetime | None = None
    about_child: bool = False
    parental_responsibility_confirmed: bool = False
    active: bool = Field(description="True while not revoked.")


# The consent texts the frontend shows (components/privacy/consent-texts.ts). A grant must
# name the current version, so every stored consent refers to a text that existed. Bump both
# sides together when a text changes.
CONSENT_TEXT_VERSIONS: dict[ConsentType, str] = {
    ConsentType.health_data: "health-data-2026-10-04",
    ConsentType.contribute: "contribute-2026-10-04",
}


class ConsentGrant(ApiModel):
    consent_type: ConsentType
    version: str = Field(
        min_length=1,
        max_length=40,
        description="Consent text version shown; must be the current version for the type "
        "(health_data: health-data-2026-10-04, contribute: contribute-2026-10-04).",
    )
    about_child: bool = Field(False, description="Consent covers data about a child.")
    parental_responsibility_confirmed: bool = Field(
        False, description="Required true when about_child is true."
    )

    @field_validator("version", mode="after")
    @classmethod
    def _current_text_version(cls, value: str, info: ValidationInfo) -> str:
        consent_type = info.data.get("consent_type")
        if consent_type is not None and value != CONSENT_TEXT_VERSIONS[consent_type]:
            raise ValueError("unknown consent text version")
        return value

    @model_validator(mode="after")
    def _child_needs_parental_responsibility(self) -> "ConsentGrant":
        if self.about_child and not self.parental_responsibility_confirmed:
            raise ValueError("parental responsibility must be confirmed for a child")
        return self


class SessionUser(ApiModel):
    id: UUID
    name: str | None = None
    email: str | None = None
    role: Role | None = Field(None, description="Null until the user picks a role.")
    role_verified: bool = False
    language: str = "en"
    expert_mode: bool = False
    age_confirmed: bool = Field(False, description="User confirmed they are 16 or older.")
    consents: list[ConsentType] = Field(default_factory=list, description="Active consents.")
    gpc_opt_out: bool = Field(
        False, description="A Global Privacy Control signal was recorded for this account."
    )


class SessionInfo(ApiModel):
    user: SessionUser | None = Field(None, description="Null for guests.")
    gpc: bool = Field(False, description="Global Privacy Control signal seen on this request.")
    demo_mode: bool = False
    data_version: str | None = Field(None, description="Graph data version served.")


class SettingsUpdate(ApiModel):
    role: Role | None = Field(None, description="patient, doctor or researcher (not guest).")
    language: str | None = Field(None, pattern=LANGUAGE_PATTERN)
    expert_mode: bool | None = None
    age_confirmed_16: bool | None = Field(None, description="Confirm the user is 16 or older.")

    @field_validator("role")
    @classmethod
    def _no_guest(cls, value: Role | None) -> Role | None:
        if value == Role.guest:
            raise ValueError("role must be patient, doctor or researcher")
        return value

    @field_validator("age_confirmed_16")
    @classmethod
    def _only_true(cls, value: bool | None) -> bool | None:
        if value is False:
            raise ValueError("age confirmation cannot be withdrawn; delete the account instead")
        return value


class ProfileSettings(ApiModel):
    role: Role | None = None
    role_verified: bool = False
    orcid_id: str | None = None
    language: str = "en"
    expert_mode: bool = False
    gpc_opt_out: bool = False
    age_confirmed_at: datetime | None = None


class AccountInfo(ApiModel):
    id: UUID
    email: str | None = None
    name: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None


class ChatSessionExport(ApiModel):
    session: ChatSession
    messages: list[ChatMessage]


class OpenAIConnection(ApiModel):
    """That a ChatGPT connection exists; the tokens themselves are never exported."""

    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    connected_at: datetime
    updated_at: datetime


# ---- work details (doctor and researcher roles; private to the account) -----------------------

ORCID_PATTERN = r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$"
MAX_NAME = 100
MAX_INSTITUTION_LABEL = 200
MAX_INSTITUTIONS = 3
MAX_NODE_ID = 200
_ORCID = re.compile(ORCID_PATTERN)


def orcid_checksum_ok(orcid: str) -> bool:
    """ISO 7064 mod 11-2 check digit of an ORCID iD in 0000-0000-0000-000X form."""
    digits = orcid.replace("-", "")
    total = 0
    for ch in digits[:-1]:
        total = (total + int(ch)) * 2
    result = (12 - total % 11) % 11
    return digits[-1] == ("X" if result == 10 else str(result))


def _has_control(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in value)


def _clean_text(value: str | None, max_length: int) -> str | None:
    """Collapse whitespace; blank becomes None; control characters and overlong values fail."""
    if value is None:
        return None
    if _has_control(value):
        raise ValueError("control characters are not allowed")
    value = " ".join(value.split())
    if len(value) > max_length:
        raise ValueError("too long")
    return value or None


def _clean_orcid(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip().upper()
    if not _ORCID.match(value) or not orcid_checksum_ok(value):
        raise ValueError("invalid ORCID iD")
    return value


class InstitutionInput(ApiModel):
    """An atlas institution (`node_id`, its label comes from the atlas) or free text (`label`)."""

    model_config = ConfigDict(extra="forbid")

    node_id: str | None = Field(
        None, max_length=MAX_NODE_ID, description="ID of an `institution` node in the atlas."
    )
    label: str | None = Field(
        None,
        description="Free-text institution name (max 200 characters), used when `node_id` is "
        "null. Ignored when `node_id` is set: the atlas label is stored instead.",
    )

    @field_validator("node_id")
    @classmethod
    def _node_id(cls, value: str | None) -> str | None:
        return _clean_text(value, MAX_NODE_ID)

    @field_validator("label")
    @classmethod
    def _label(cls, value: str | None) -> str | None:
        return _clean_text(value, MAX_INSTITUTION_LABEL)

    @model_validator(mode="after")
    def _one_of(self) -> "InstitutionInput":
        if self.node_id is None and self.label is None:
            raise ValueError("node_id or label is required")
        return self


class Institution(ApiModel):
    node_id: str | None = Field(None, description="Atlas institution node, null for free text.")
    label: str


class _WorkDetailsInput(ApiModel):
    model_config = ConfigDict(extra="forbid")

    first_name: str | None = Field(None, description="1-100 characters; blank means none.")
    last_name: str | None = Field(None, description="1-100 characters; blank means none.")
    orcid_id: str | None = Field(
        None, description="ORCID iD, 0000-0000-0000-000X, with a valid check digit."
    )
    institutions: list[InstitutionInput] = Field(
        default_factory=list, max_length=MAX_INSTITUTIONS, description="At most three."
    )

    @field_validator("first_name", "last_name")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return _clean_text(value, MAX_NAME)

    @field_validator("orcid_id")
    @classmethod
    def _orcid(cls, value: str | None) -> str | None:
        return _clean_orcid(value)


class ProfessionalProfileUpdate(_WorkDetailsInput):
    """Replaces all work details (PUT). Every field is optional."""

    atlas_node_id: str | None = Field(
        None,
        max_length=MAX_NODE_ID,
        description="The user's own `researcher` or `doctor` node (private link, not a claim).",
    )

    @field_validator("atlas_node_id")
    @classmethod
    def _node(cls, value: str | None) -> str | None:
        return _clean_text(value, MAX_NODE_ID)


class AtlasMatchRequest(_WorkDetailsInput):
    """A draft of the work details to look up candidate atlas entries. Nothing is stored."""


class SuggestedName(ApiModel):
    """Prefill from the ChatGPT account, computed on request and never stored."""

    first_name: str | None = None
    last_name: str | None = None
    source: Literal["chatgpt"] = "chatgpt"


class AtlasEntry(ApiModel):
    """Public fields of a researcher or doctor node."""

    node_id: str
    type: NodeType = Field(description="researcher or doctor.")
    label: str
    orcid_id: str | None = Field(None, description="Public ORCID iD of the node, if any.")
    institutions: list[Institution] = Field(
        default_factory=list, description="Affiliated atlas institutions (at most three)."
    )


class AtlasEntryCandidate(AtlasEntry):
    matched_by: Literal["orcid", "name_and_institution", "name"] = Field(
        description="orcid: exact ORCID iD; name_and_institution: same name and a shared "
        "institution; name: same name only."
    )


class AtlasMatches(ApiModel):
    candidates: list[AtlasEntryCandidate] = Field(description="At most five, best first.")


class ProfessionalProfile(ApiModel):
    """The user's private work details. Self-declared, not a verification; visible to nobody
    else and never sent to a model."""

    first_name: str | None = None
    last_name: str | None = None
    institutions: list[Institution] = Field(default_factory=list)
    orcid_id: str | None = None
    atlas_node_id: str | None = None
    linked_entry: AtlasEntry | None = Field(
        None, description="Public summary of `atlas_node_id` while the node is in the atlas."
    )
    linked_entry_missing: bool = Field(
        False, description="`atlas_node_id` is set but the node is no longer in the atlas."
    )
    updated_at: datetime | None = Field(None, description="Last save; null if never saved.")
    suggested: SuggestedName | None = Field(
        None, description="Name prefill from the ChatGPT account; null if it has no name."
    )


class ProfessionalExport(ApiModel):
    first_name: str | None = None
    last_name: str | None = None
    institutions: list[Institution] = Field(default_factory=list)
    orcid_id: str | None = None
    atlas_node_id: str | None = None
    updated_at: datetime | None = None
    # Verification and the opt-in public card (schemas/people.py).
    orcid_verified_at: datetime | None = None
    verified_name: str | None = None
    verification_method: str | None = None
    verified_at: datetime | None = None
    verification_reason: str | None = Field(None, description="The operator's logged reason.")
    verification_request: dict[str, Any] | None = None
    atlas_link_verified: bool = False
    card_id: UUID | None = None
    card_visible: bool = False
    card_visible_since: datetime | None = None
    card_headline: str | None = None
    card_show_institutions: bool = True
    card_show_atlas_entry: bool = True
    accepts_patient_messages: bool = False


class DataExport(ApiModel):
    """Everything stored about the user (GDPR Art. 15/20, CCPA right to know)."""

    exported_at: datetime
    account: AccountInfo
    settings: ProfileSettings
    openai_connected: bool = Field(description="Tokens exist (the tokens are not exported).")
    openai_connection: OpenAIConnection | None = Field(
        None, description="Scopes and expiry of the ChatGPT connection, without tokens."
    )
    consents: list[Consent]
    patient_profile: PatientProfile | None
    professional: ProfessionalExport | None = Field(
        None, description="Work details (doctor and researcher roles); null if none are stored."
    )
    chat_sessions: list[ChatSessionExport]
    chat_runs: list[ChatRunExport] = Field(
        default_factory=list, description="Dr. Wu turns still running, with their saved state."
    )
    documents: list[Document]
    findings: list[Finding]
    contributions: list[Contribution]
    edge_flags: list[EdgeFlag]
    jobs: list[Job]
    follows: list[FollowExport] = Field(description="Followed diseases.")
    notifications: list[NotificationExport] = Field(
        description="In-app notifications (no stored text)."
    )
