"""Followed diseases and in-app notifications (private to the account).

Follows are health data held under the `health_data` consent. Notifications carry no stored
text: labels are resolved from the current graph when they are read.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field, model_validator

from backend.schemas.common import ApiModel
from backend.schemas.enums import NodeType

MAX_FOLLOWS = 50
MONDO_PATTERN = r"^MONDO:\d{7}$"
MAX_NOTIFICATIONS_PAGE = 200
MAX_READ_IDS = 200


class FollowRequest(ApiModel):
    """The disease to follow or unfollow. In the body, not the URL: which diseases a user follows
    is health data and must not appear in URLs or access logs."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(pattern=MONDO_PATTERN, description="Atlas disease ID (MONDO:0000000).")


class Follow(ApiModel):
    node_id: str = Field(description="The followed disease (MONDO ID).")
    label: str | None = Field(description="Disease label; null if no longer in the atlas.")
    in_atlas: bool = Field(description="The disease is in the current atlas.")
    updates_available: bool = Field(
        description="Papers, trials, grants and patient groups (and so updates) exist only for "
        "the atlas's focus diseases. False for core diseases and for diseases no longer in the "
        "atlas: following still works, but no notifications are expected."
    )
    created_at: datetime
    since_version: str | None = Field(
        description="Atlas data version live when the follow started; changes from later "
        "loads produce notifications."
    )


class FollowList(ApiModel):
    items: list[Follow] = Field(description="Newest first.")
    limit: int = Field(description="Maximum number of follows per account.")


class FollowFromProfileResult(ApiModel):
    added: list[Follow] = Field(description="Follows created by this call (newest first).")
    already_following: list[str] = Field(description="Profile diseases that were already followed.")
    not_in_atlas: list[str] = Field(
        description="Confirmed profile diagnoses that are not diseases in the atlas (IDs).",
    )
    limit_reached: bool = Field(
        description="Some diseases were not followed because the limit of 50 was reached."
    )


class FollowExport(ApiModel):
    node_id: str
    created_at: datetime
    since_version: str | None = None


class NotificationKind(StrEnum):
    added = "added"  # a paper, trial, grant or patient group newly linked to the disease
    now_recruiting = "now_recruiting"  # a trial whose status changed to recruiting
    call_match = "call_match"  # a published call that matches the profile (suggestions on)


class Notification(ApiModel):
    """One update about a followed disease. Render papers as "added to the atlas" with their
    year, never as "just published"."""

    id: UUID
    kind: NotificationKind = Field(
        description="added: a paper, trial, grant or patient group newly linked to the disease "
        "in the atlas; now_recruiting: a trial whose status changed to recruiting; call_match: "
        "a published call matches your profile (suggestions switched on; link to the call)."
    )
    disease_id: str | None = Field(
        description="The followed disease (call_match: the matching disease, if any)."
    )
    disease_label: str | None = Field(description="Null if no longer in the atlas.")
    item_id: str = Field(
        description="Node ID of the new item; link to its node page. call_match: the call id."
    )
    call_id: UUID | None = Field(None, description="call_match only: the call to open.")
    item_type: NodeType | None = Field(
        description="paper, trial, grant or patient_org; null if no longer in the atlas."
    )
    item_label: str | None = Field(
        description="Null if no longer in the atlas. call_match: the call's title."
    )
    registry_id: str | None = Field(description="Trials: the registry ID (NCT...).")
    year: int | None = Field(
        description="Papers: publication year. Say 'added to the atlas (2025)', not 'published'.",
    )
    gone: bool = Field(
        description="The item or the disease has left the atlas since (call_match: the call is no "
        "longer published and open); render without a link."
    )
    data_version: str | None = Field(description="Atlas data version that added it.")
    created_at: datetime
    read_at: datetime | None


class NotificationList(ApiModel):
    items: list[Notification] = Field(description="Newest first.")
    unread_count: int


class UnreadCount(ApiModel):
    count: int = Field(description="Unread notifications.")


class MarkRead(ApiModel):
    """Either `ids` or `all: true`."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(default_factory=list, max_length=MAX_READ_IDS)
    all: bool = Field(False, description="Mark every notification as read.")

    @model_validator(mode="after")
    def _one_of(self) -> "MarkRead":
        if bool(self.ids) == self.all:
            raise ValueError("send either ids or all: true")
        return self


class NotificationExport(ApiModel):
    id: UUID
    kind: str
    ref_id: str
    subject_node_id: str | None = None
    data_version: str | None = None
    created_at: datetime
    read_at: datetime | None = None
