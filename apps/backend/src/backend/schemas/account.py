from datetime import datetime
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from backend.schemas.chat import ChatMessage, ChatSession
from backend.schemas.common import LANGUAGE_PATTERN, ApiModel
from backend.schemas.contributions import Contribution, EdgeFlag
from backend.schemas.documents import Document, Finding, Job
from backend.schemas.enums import ConsentType, Role
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


class ConsentGrant(ApiModel):
    consent_type: ConsentType
    version: str = Field(min_length=1, max_length=40, description="Consent text version shown.")
    about_child: bool = Field(False, description="Consent covers data about a child.")
    parental_responsibility_confirmed: bool = Field(
        False, description="Required true when about_child is true."
    )

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
    chat_sessions: list[ChatSessionExport]
    documents: list[Document]
    findings: list[Finding]
    contributions: list[Contribution]
    edge_flags: list[EdgeFlag]
    jobs: list[Job]
