from typing import Annotated

from fastapi import APIRouter, Query

from backend.api.deps import DB, HealthDataConsentUser, SignedInUser, User
from backend.api.errors import responses
from backend.api.services import follows
from backend.schemas.follows import (
    MAX_NOTIFICATIONS_PAGE,
    Follow,
    FollowFromProfileResult,
    FollowList,
    FollowRequest,
    MarkRead,
    NotificationList,
    UnreadCount,
)

router = APIRouter()

# Following is processing of health data (health_data consent). Reading and deleting one's own
# follows and notifications never needs a consent; withdrawing it deletes both.


@router.get(
    "/me/follows",
    response_model=FollowList,
    responses=responses(401, 403),
    operation_id="listFollows",
    tags=["follows"],
)
async def list_follows(db: DB, user: User) -> FollowList:
    """The diseases the user follows, each saying whether updates can exist for it."""
    return await follows.list_follows(db, user)


@router.put(
    "/me/follows",
    response_model=Follow,
    responses=responses(401, 403, 404, 409, 422),
    operation_id="followDisease",
    tags=["follows"],
)
async def follow_disease(body: FollowRequest, db: DB, user: HealthDataConsentUser) -> Follow:
    """Follow a disease of the atlas (idempotent; needs the health_data consent). 404 unless the
    ID is a disease in the atlas, 409 when 50 diseases are already followed."""
    return await follows.follow(db, user, body.node_id)


@router.delete(
    "/me/follows",
    status_code=204,
    responses=responses(401, 422),
    operation_id="unfollowDisease",
    tags=["follows"],
)
async def unfollow_disease(body: FollowRequest, db: DB, user: SignedInUser) -> None:
    """Stop following a disease (idempotent) and delete its notifications."""
    await follows.unfollow(db, user, body.node_id)


@router.post(
    "/me/follows/from-profile",
    response_model=FollowFromProfileResult,
    responses=responses(401, 403),
    operation_id="followProfileDiseases",
    tags=["follows"],
)
async def follow_profile_diseases(db: DB, user: HealthDataConsentUser) -> FollowFromProfileResult:
    """Follow the confirmed diagnoses of the health profile that are diseases in the atlas
    (needs the health_data consent). Returns what was added."""
    return await follows.follow_from_profile(db, user)


@router.get(
    "/notifications",
    response_model=NotificationList,
    responses=responses(401, 403, 422),
    operation_id="listNotifications",
    tags=["notifications"],
)
async def list_notifications(
    db: DB,
    user: User,
    limit: Annotated[int, Query(ge=1, le=MAX_NOTIFICATIONS_PAGE)] = 50,
) -> NotificationList:
    """The user's notifications, newest first, with labels resolved from the current atlas.
    Picks up new atlas changes for followed diseases; notifications older than 90 days are
    deleted."""
    return await follows.list_notifications(db, user, limit)


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCount,
    responses=responses(401, 403),
    operation_id="getUnreadNotificationCount",
    tags=["notifications"],
)
async def get_unread_notification_count(db: DB, user: User) -> UnreadCount:
    """Unread notifications. Cheap enough to poll once a minute: new atlas changes are checked
    at most once per data load."""
    return await follows.unread_count(db, user)


@router.post(
    "/notifications/read",
    response_model=UnreadCount,
    responses=responses(401, 403, 422),
    operation_id="markNotificationsRead",
    tags=["notifications"],
)
async def mark_notifications_read(body: MarkRead, db: DB, user: User) -> UnreadCount:
    """Mark the given notifications (or all with `all: true`) as read; returns the new count."""
    return await follows.mark_read(db, user, body)
