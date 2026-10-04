"""Verification and the opt-in public card of doctors and researchers ("Reachable in Amber").

A card exists for others only while the person is a doctor or researcher, verified
(`role_verified`) and has switched it on (`card_visible`). It carries only the fields below and
never the user ID, e-mail, ChatGPT identity, a self-declared ORCID iD or an unverified atlas link.
Patients never have cards and are never listed, searched or counted.
"""

import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from backend.schemas.common import ApiModel
from backend.schemas.enums import Role

MAX_HEADLINE = 160
MAX_EMAIL = 254
MAX_URL = 500

VerificationMethod = Literal["orcid", "orcid_simulated", "institutional_email"]
NameSource = Literal["orcid", "reviewed", "self_declared"]

# What each method checked; never "licensed physician".
VERIFICATION_LABELS: dict[str, str] = {
    "orcid": "ORCID iD confirmed",
    "orcid_simulated": "Demo, verification simulated (no real ORCID check)",
    "institutional_email": "Identity checked by the Amber team (institutional e-mail)",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_URLISH = re.compile(r"://|www\.", re.IGNORECASE)


def _has_control(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Zl", "Zp") for c in value)


class CardInstitution(ApiModel):
    node_id: str | None = Field(None, description="Atlas institution node, null for free text.")
    label: str


class CardVerification(ApiModel):
    method: VerificationMethod
    label: str = Field(description="What was checked, ready to show.")
    simulated: bool = Field(
        description="True when verified through the local ORCID mock: show the label, which says "
        "'demo, verification simulated'."
    )


class PublicCard(ApiModel):
    """What other signed-in users see. Everything here was chosen by the person."""

    card_id: UUID = Field(description="Opaque card ID (never the user ID).")
    role: Role = Field(description="doctor or researcher; self-declared, show it as such.")
    role_self_declared: Literal[True] = True
    name: str
    name_source: NameSource = Field(
        description="orcid: from the ORCID record; reviewed: checked by the Amber team; "
        "self_declared: from the person's own work details."
    )
    institutions: list[CardInstitution] = Field(
        default_factory=list, description="Self-declared, at most three; empty if hidden."
    )
    orcid_id: str | None = Field(None, description="Only when confirmed by ORCID sign-in.")
    orcid_url: str | None = None
    atlas_node_id: str | None = Field(
        None,
        description="The person's own atlas entry, only when that link is verified (exact ORCID "
        "match or manual review) and the person chose to show it.",
    )
    atlas_node_label: str | None = None
    headline: str | None = Field(None, description="Optional, at most 160 characters.")
    accepts_patient_messages: bool = Field(
        description="The person's setting. Messaging is not built yet; nothing can be sent."
    )
    verification: CardVerification


class PeopleList(ApiModel):
    disease_id: str
    items: list[PublicCard] = Field(
        description="Visible verified cards whose verified atlas entry is linked to the disease "
        "(through papers, grants or trials in the atlas). Professionals only."
    )


class VerificationRequestState(ApiModel):
    status: Literal["pending", "rejected"]
    requested_at: datetime
    decided_at: datetime | None = None
    institutional_email: str | None = Field(None, description="While pending only.")
    profile_url: str | None = Field(None, description="While pending only.")


class VerificationState(ApiModel):
    verified: bool = Field(description="role_verified: identity checked for this role.")
    method: VerificationMethod | None = None
    label: str | None = None
    simulated: bool = False
    verified_at: datetime | None = None
    orcid_id_confirmed: bool = Field(False, description="The ORCID iD is confirmed and locked.")
    atlas_link_verified: bool = False
    request: VerificationRequestState | None = None
    orcid_available: bool = Field(description="ORCID sign-in can be started on this server.")
    orcid_simulated: bool = Field(description="ORCID sign-in is the local simulated mock.")


class CardSettings(ApiModel):
    visible: bool = False
    visible_since: datetime | None = None
    headline: str | None = None
    accepts_patient_messages: bool = False
    show_institutions: bool = True
    show_atlas_entry: bool = True


class MyCard(ApiModel):
    """The user's own verification state, card settings and a preview of the card."""

    verification: VerificationState
    settings: CardSettings
    card_id: UUID | None = Field(None, description="Set once the card was first switched on.")
    can_show: bool = Field(description="The card can be switched on now.")
    blocked_reason: Literal["role", "not_verified", "no_name"] | None = Field(
        None,
        description="Why it cannot: role (not a doctor or researcher), not_verified, no_name "
        "(no name from ORCID and none in the work details).",
    )
    preview: PublicCard | None = Field(
        None, description="Exactly what others would see; null while it cannot be shown."
    )


class CardSettingsUpdate(ApiModel):
    """Replaces the card settings (PUT). The card is off by default."""

    model_config = ConfigDict(extra="forbid")

    visible: bool = False
    headline: str | None = Field(
        None, description="At most 160 characters; no e-mail addresses, links or phone numbers."
    )
    accepts_patient_messages: bool = False
    show_institutions: bool = True
    show_atlas_entry: bool = True

    @field_validator("headline")
    @classmethod
    def _headline(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if _has_control(value):
            raise ValueError("control characters are not allowed")
        value = " ".join(value.split())
        if len(value) > MAX_HEADLINE:
            raise ValueError("too long")
        if "@" in value or _URLISH.search(value) or re.search(r"\d{6,}", value.replace(" ", "")):
            raise ValueError("no contact details in the headline")
        return value or None


class VerificationRequestCreate(ApiModel):
    """Manual review: the Amber team checks the institutional e-mail and the public profile."""

    model_config = ConfigDict(extra="forbid")

    institutional_email: str = Field(max_length=MAX_EMAIL)
    profile_url: str = Field(
        max_length=MAX_URL, description="https link to a public staff or profile page."
    )

    @field_validator("institutional_email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip()
        if _has_control(value) or not _EMAIL.match(value):
            raise ValueError("invalid e-mail address")
        return value

    @field_validator("profile_url")
    @classmethod
    def _url(cls, value: str) -> str:
        value = value.strip()
        if _has_control(value) or not value.lower().startswith("https://"):
            raise ValueError("an https link is required")
        return value


class OrcidStartRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    return_to: str | None = Field(
        None, description="Relative frontend path to return to (default /profile)."
    )


class OrcidStart(ApiModel):
    authorize_url: str = Field(description="Open this URL in the browser (top-level navigation).")
    simulated: bool = Field(description="True for the local simulated ORCID sign-in.")
