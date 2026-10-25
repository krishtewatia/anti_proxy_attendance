"""Account and face-template review states.

A registration is PENDING until an administrator approves it. A pending
teacher cannot log in; a pending student can, but is not eligible for
attendance (no roster, no recognition) until approved. A face template is ACTIVE once an
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


def can_sign_in(user: dict[str, Any] | None) -> bool:
    """Approved accounts sign in; so does a student whose approval is pending.

    For a student, approval only decides eligibility for attendance: until
    then they are on no roster and their face is not recognised, but they can
    sign in, set up their classes and photos, and see their own dashboard. A
    teacher still cannot sign in before approval.
    """
    if is_approved(user):
        return True
    return bool(user) and user.get("role") == "STUDENT" and account_status(user) == ACCOUNT_PENDING


def template_is_active(profile: dict[str, Any] | None) -> bool:
    """True for a face template that may be used for recognition."""
    return bool(profile) and (profile.get("review_status") or TEMPLATE_ACTIVE) == TEMPLATE_ACTIVE
