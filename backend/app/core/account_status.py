"""Account and face-template review states.

A registration is PENDING until an administrator approves it. Only APPROVED
accounts can log in or hold a valid token. A face template is ACTIVE once an
administrator has approved the account (or the photo change) it came from;
only ACTIVE templates of APPROVED students are served to the vision service.

Records written before these fields existed have no value, which is read as
APPROVED / ACTIVE so existing accounts keep working. The startup migration
then writes the value explicitly.
"""

from __future__ import annotations

from typing import Any

ACCOUNT_PENDING = "PENDING"
ACCOUNT_APPROVED = "APPROVED"
ACCOUNT_STATUSES = (ACCOUNT_PENDING, ACCOUNT_APPROVED)

TEMPLATE_ACTIVE = "ACTIVE"
TEMPLATE_PENDING_REVIEW = "PENDING_REVIEW"

# A registration nobody acted on is removed after this many days.
PENDING_REGISTRATION_MAX_AGE_DAYS = 14


def account_status(user: dict[str, Any] | None) -> str:
    """The status of a user document; a missing value means APPROVED."""
    if not user:
        return ACCOUNT_PENDING
    return user.get("status") or ACCOUNT_APPROVED


def is_approved(user: dict[str, Any] | None) -> bool:
    return bool(user) and account_status(user) == ACCOUNT_APPROVED


def template_is_active(profile: dict[str, Any] | None) -> bool:
    """True for a face template that may be used for recognition."""
    return bool(profile) and (profile.get("review_status") or TEMPLATE_ACTIVE) == TEMPLATE_ACTIVE
