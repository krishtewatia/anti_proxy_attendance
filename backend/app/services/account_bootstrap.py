"""Start-up account housekeeping.

* Migration: records written before account approval existed get their
  status written explicitly (APPROVED / ACTIVE), so nothing stops working.
* First administrator: when no administrator exists and the two bootstrap
  variables are set, one is created. There is no default password.
"""

from __future__ import annotations

import logging
import os
from uuid import uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core.account_status import ACCOUNT_APPROVED, TEMPLATE_ACTIVE
from app.database.users import create_user
from app.security.passwords import hash_password
from app.services.audit_service import record_audit_event

logger = logging.getLogger(__name__)

BOOTSTRAP_EMAIL_VAR = "BOOTSTRAP_ADMIN_EMAIL"
# The name of an environment variable, not a password.
BOOTSTRAP_PASSWORD_VAR = "BOOTSTRAP_ADMIN_PASSWORD"  # nosec B105
BOOTSTRAP_PASSWORD_MIN_LENGTH = 12


async def migrate_account_status(db: AsyncIOMotorDatabase) -> dict[str, int]:
    """Write the status onto accounts and templates that predate approval. Safe to repeat."""
    users = await db["users"].update_many(
        {"status": {"$exists": False}}, {"$set": {"status": ACCOUNT_APPROVED}}
    )
    templates = await db["biometric_profiles"].update_many(
        {"review_status": {"$exists": False}}, {"$set": {"review_status": TEMPLATE_ACTIVE}}
    )
    result = {"users": users.modified_count, "templates": templates.modified_count}
    if any(result.values()):
        logger.info(
            "Account status migration: %d account(s) marked APPROVED, %d template(s) marked ACTIVE",
            result["users"],
            result["templates"],
        )
    return result


async def bootstrap_first_admin(db: AsyncIOMotorDatabase) -> str:
    """Create the first administrator from the environment, if there is none.

    Returns what happened: ``created``, ``exists``, ``not_configured`` or
    ``invalid``. An existing administrator is never changed.
    """
    email = os.getenv(BOOTSTRAP_EMAIL_VAR, "").strip().lower()
    password = os.getenv(BOOTSTRAP_PASSWORD_VAR, "")
    configured = bool(email or password)
    admin_exists = await db["users"].count_documents({"role": "ADMIN"}) > 0

    if admin_exists:
        if configured:
            logger.warning(
                "%s / %s are still set although an administrator already exists. "
                "They are ignored; remove them from the environment.",
                BOOTSTRAP_EMAIL_VAR,
                BOOTSTRAP_PASSWORD_VAR,
            )
        return "exists"

    if not configured:
        logger.warning(
            "No administrator account exists. Set %s and %s to create the first one at start-up.",
            BOOTSTRAP_EMAIL_VAR,
            BOOTSTRAP_PASSWORD_VAR,
        )
        return "not_configured"

    # Never fall back to a default: both values must be supplied and usable.
    if "@" not in email or len(password) < BOOTSTRAP_PASSWORD_MIN_LENGTH:
        logger.error(
            "The first administrator was not created: %s must be an email address and %s "
            "must be at least %d characters.",
            BOOTSTRAP_EMAIL_VAR,
            BOOTSTRAP_PASSWORD_VAR,
            BOOTSTRAP_PASSWORD_MIN_LENGTH,
        )
        return "invalid"

    user_id = f"user_{uuid4().hex}"
    await create_user(
        user_id=user_id,
        email=email,
        password_hash=hash_password(password),
        role="ADMIN",
        status=ACCOUNT_APPROVED,
    )
    # The password came from the environment, so it must be replaced at first login.
    await db["users"].update_one({"user_id": user_id}, {"$set": {"must_change_password": True}})
    await record_audit_event(
        actor_user_id="system",
        actor_role="SYSTEM",
        action="ADMIN_BOOTSTRAPPED",
        resource_type="USER",
        resource_id=user_id,
        metadata={"source": "environment"},
    )
    logger.warning(
        "Created the first administrator account from %s. Remove %s and %s from the environment now.",
        BOOTSTRAP_EMAIL_VAR,
        BOOTSTRAP_EMAIL_VAR,
        BOOTSTRAP_PASSWORD_VAR,
    )
    return "created"
