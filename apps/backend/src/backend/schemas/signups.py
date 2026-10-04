"""Suggestions of calls and sign-ups to them (connect stage 4, `connect` consent).

Suggestions are computed in the patient's own request from confirmed profile items and are never
stored (apart from the patient's own `call_match` notifications); publishers never learn who was
suggested. A sign-up sends exactly the items the patient ticks, limited to what the call asks for
and targets, to the call's publisher; it is an authorization recorded with its text version and
time. User ids never appear in these schemas: the publisher sees a display name the patient
chose, and the patient sees the publisher's card name.
"""

import unicodedata
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from backend.schemas.calls import AtlasRef, Call
from backend.schemas.common import ApiModel
from backend.schemas.messaging import clean_name

MAX_NOTE = 1000
MAX_ITEMS = 200
STUB_DAYS = 30  # a withdrawn or declined sign-up is a stub this long
CLOSED_DAYS = 90  # sign-ups of a closed call are purged this long after it closed

# The authorization on the sign-up screen (connect-plan section 5 D). {recipient} is the card
# name with the first institution, {name} the card name; the screen lists the ticked items where
# {items} stands. The version is stored on every sign-up. Bump it with every wording change.
AUTHORIZATION_VERSION = "signup-authorization-2026-10-04"
AUTHORIZATION_TEXT = (
    "You are sending the following to {recipient}, who runs this call: {items}. After sending, "
    "{name} is responsible for this information under their ethics approval. You can withdraw "
    "here at any time; that deletes it from Amber but cannot undo what the team has already "
    "noted. Signing up does not mean you are eligible: only the study team can decide."
)
# The suggestion sentence: "Suggested because your profile lists Dravet syndrome and SCN1A. ..."
SUGGESTION_SENTENCE = (
    "Suggested because your profile lists {reasons}. This is not an eligibility check; only the "
    "study team decides."
)
SUGGESTIONS_NOTICE = (
    "Suggestions compare the confirmed items of your profile with published calls, inside your "
    "own account. Nobody else sees them, and study teams never learn who was suggested. Every "
    "published call stays listed for everyone; suggestions only point to some of them."
)
MINOR_LABEL = "Participant is 16 or 17; a parent or guardian agreed (self-declared)"
FOR_ADULTS_LABEL = "For adults: this call does not take sign-ups from people aged 16 or 17."


def _has_control(value: str) -> bool:
    return any(unicodedata.category(c) in ("Cc", "Zl", "Zp") and c not in "\n\t" for c in value)


def clean_note(value: str | None) -> str | None:
    """Plain text, CRLF becomes LF, other control characters fail, at most 1,000 characters;
    empty becomes None."""
    if value is None:
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if _has_control(value):
        raise ValueError("control characters are not allowed")
    value = value.strip()
    if not value:
        return None
    if len(value) > MAX_NOTE:
        raise ValueError("at most 1,000 characters")
    return value


# ---- suggestions ----------------------------------------------------------------------------


class SuggestionReasonKind(StrEnum):
    """disease: an exact disease of the profile is a disease of the call (strong); gene: a gene
    of the profile, or the gene of a profile variant, is a gene of the call; symptoms: at least
    two exact symptoms (HPO ids) of the profile are symptoms of the call."""

    disease = "disease"
    gene = "gene"
    symptoms = "symptoms"


class SuggestionReason(ApiModel):
    kind: SuggestionReasonKind
    items: list[AtlasRef] = Field(description="The matching atlas entries, labels from the atlas.")
    via_variant: bool = Field(
        False, description="gene only: at least one gene came from a variant in the profile."
    )


class SignupBlock(StrEnum):
    """Why the sign-up button is not offered (the call stays visible in every case)."""

    not_patient = "not_patient"  # doctors and researchers do not sign up
    own_call = "own_call"
    for_adults = "for_adults"  # min_age 18 or more and the user said 16 or 17
    already_signed_up = "already_signed_up"
    declined = "declined"  # the study team declined an earlier sign-up
    not_open_yet = "not_open_yet"  # opens_at is in the future


class SignupAvailability(ApiModel):
    can_sign_up: bool = Field(
        description="Offer the sign-up button. The consent and the age group are asked just in "
        "time on the sign-up screen and do not block it here."
    )
    blocked_by: SignupBlock | None = None
    label: str | None = Field(None, description="Text to show instead of the button, if any.")
    signup_id: UUID | None = Field(None, description="My active or declined sign-up, if any.")


class SuggestedCall(ApiModel):
    call: Call
    score: int = Field(description="disease 3, gene 2, symptoms 1, summed; higher first.")
    reasons: list[SuggestionReason]
    sentence: str = Field(description="Show as is: 'Suggested because your profile lists ...'.")
    age_fits: bool | None = Field(
        description="Information only, never used to hide: the profile's age or age range fits "
        "the call's ages; null when either side gives none."
    )
    country_listed: bool | None = Field(
        description="Information only: the profile's country is one of the call's countries; "
        "null when the profile has no country or the call lists none."
    )
    signup: SignupAvailability


class SuggestionList(ApiModel):
    consent_active: bool = Field(description="An active `connect` consent of the current text.")
    enabled: bool = Field(description="The user switched suggestions on.")
    items: list[SuggestedCall] = Field(
        description="Empty unless consent_active and enabled. Strongest first, then newest."
    )
    notice: str = SUGGESTIONS_NOTICE


class SuggestionSettings(ApiModel):
    enabled: bool = Field(description="Suggestions are switched on (off by default).")
    enabled_at: datetime | None
    consent_active: bool = Field(description="An active `connect` consent of the current text.")
    notice: str = SUGGESTIONS_NOTICE


class SuggestionSettingsUpdate(ApiModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(
        description="Switching on needs the connect consent (403 consent_required). Switching off "
        "deletes the call_match notifications."
    )


# ---- sign-ups -------------------------------------------------------------------------------


class SignupStatus(StrEnum):
    """active; withdrawn (by the patient: items deleted, stub for 30 days); declined (by the
    study team: items deleted, stub for 30 days); call_closed (the call closed or was deleted:
    deleted 90 days after it closed, at once if it was deleted)."""

    active = "active"
    withdrawn = "withdrawn"
    declined = "declined"
    call_closed = "call_closed"


class SignupOptionKind(StrEnum):
    diagnosis = "diagnosis"
    gene = "gene"
    variant = "variant"
    symptom = "symptom"
    age_range = "age_range"
    country = "country"


class SignupOption(ApiModel):
    """One item the patient may tick. Only confirmed, non-excluded profile items that the call
    asks for (requested_fields) and targets (its diseases, genes, symptoms) are offered."""

    key: str = Field(description="Send back in SignupRequest.items to share it.")
    kind: SignupOptionKind
    label: str
    detail: str | None = Field(None, description="Variant notation and classification, if any.")
    preselected: bool = Field(description="Only a matching diagnosis is pre-ticked.")


class SignupOptions(ApiModel):
    call_id: UUID
    call_title: str
    recipient: str = Field(description="Card name and first institution ('who runs this call').")
    recipient_name: str = Field(description="Card name.")
    options: list[SignupOption]
    authorization_text: str = Field(
        description="With the recipient filled in; replace {items} with the ticked items."
    )
    authorization_version: str = AUTHORIZATION_VERSION
    consent_active: bool = Field(
        description="An active `connect` consent of the current text; ask for it before sending."
    )
    age_group_needed: bool = Field(description="Ask for the age group before sending.")
    guardian_required: bool = Field(
        description="The user said 16 or 17: show guardian_text as one more required checkbox."
    )
    guardian_text: str = Field(description="With the recipient filled in.")
    guardian_text_version: str
    about_child: bool = Field(
        description="The profile describes a child (parental responsibility confirmed)."
    )
    availability: SignupAvailability
    max_note: int = MAX_NOTE


class SignupRequest(ApiModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(
        description="How the study team sees you (1-60 characters). Your e-mail, account name and "
        "profile are never shown."
    )
    items: list[str] = Field(
        default_factory=list,
        max_length=MAX_ITEMS,
        description="Keys of the ticked SignupOptions; anything not offered is refused (422).",
    )
    note: str | None = Field(None, description="Optional note to the study team, plain text.")
    authorized: bool = Field(description="The authorization was shown and ticked; must be true.")
    authorization_version: str = Field(description="Must be the current authorization version.")
    guardian_agreed: bool = Field(False, description="Required true when the age group is 16_17.")
    open_conversation: bool = Field(
        False,
        description="Also open a conversation with the study team (no message yet; counts "
        "towards 5 new conversations a day).",
    )

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return clean_name(value)

    @field_validator("note")
    @classmethod
    def _note(cls, value: str | None) -> str | None:
        return clean_note(value)

    @field_validator("items")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class SharedItem(ApiModel):
    id: str | None = Field(None, description="Atlas id (MONDO, HGNC, HP) or ClinVar id.")
    label: str
    detail: str | None = None


class SharedItems(ApiModel):
    """Exactly what the patient ticked; empty after a withdrawal or a decline."""

    diagnoses: list[SharedItem] = Field(default_factory=list)
    genes: list[SharedItem] = Field(default_factory=list)
    variants: list[SharedItem] = Field(default_factory=list)
    symptoms: list[SharedItem] = Field(default_factory=list)
    age_range: str | None = None
    country: str | None = None


class MySignup(ApiModel):
    id: UUID
    call_id: UUID | None = Field(description="Null once the call was deleted.")
    call_title: str = Field(description="The call's title when I signed up.")
    call_open: bool = Field(description="The call is still published and open.")
    recipient: str = Field(description="Who received it, as named in the authorization.")
    display_name: str
    shared: SharedItems
    note: str | None
    status: SignupStatus
    about_child: bool
    authorization_version: str
    authorized_at: datetime
    guardian_agreed_at: datetime | None
    guardian_text_version: str | None
    created_at: datetime
    withdrawn_at: datetime | None
    declined_at: datetime | None
    call_ended_at: datetime | None
    delete_after: datetime | None = Field(description="When this sign-up is deleted for good.")
    thread_id: UUID | None = Field(description="The conversation opened with this sign-up.")


class MySignupList(ApiModel):
    items: list[MySignup] = Field(description="Newest first.")


class ReceivedSignup(ApiModel):
    """A sign-up to one of my calls, as the study team sees it. Never an account id or e-mail."""

    id: UUID
    display_name: str
    shared: SharedItems
    note: str | None
    status: SignupStatus = Field(description="withdrawn: show 'withdrew' (a stub, items deleted).")
    about_child: bool = Field(description="The sign-up is about a child (a parent signs up).")
    minor: bool = Field(description="The participant said they are 16 or 17.")
    minor_label: str | None = Field(description="Show when minor is true.")
    authorization_version: str
    authorized_at: datetime
    created_at: datetime
    withdrawn_at: datetime | None
    declined_at: datetime | None
    thread_id: UUID | None = Field(description="The conversation the participant opened, if any.")


class ReceivedSignupList(ApiModel):
    call_id: UUID
    call_title: str
    active_count: int = Field(description="Active sign-ups of this call.")
    max_signups: int | None
    items: list[ReceivedSignup] = Field(description="Newest first; stubs included.")


class SignupExport(ApiModel):
    id: UUID
    call_id: UUID | None
    call_title_snapshot: str
    recipient_name: str
    display_name: str
    shared: SharedItems
    about_child: bool
    note: str | None
    authorization_version: str
    authorized_at: datetime
    guardian_agreed_at: datetime | None
    guardian_text_version: str | None
    status: SignupStatus
    withdrawn_at: datetime | None
    declined_at: datetime | None
    call_ended_at: datetime | None
    purge_after: datetime | None
    thread_id: UUID | None
    created_at: datetime


class SignupsExport(ApiModel):
    suggestions_enabled: bool
    suggestions_enabled_at: datetime | None
    signups: list[SignupExport] = Field(description="My own sign-ups (not those to my calls).")
