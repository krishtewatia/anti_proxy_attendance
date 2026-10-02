from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from app.core.config import settings
from app.database.mongodb import get_database

USERS_COLLECTION = "users"


class DuplicateUserRecordError(Exception):
    """Raised when a user record violates a unique constraint in the repository."""


async def create_user(
    *,
    user_id: str,
    email: str,
    password_hash: str,
    role: str,
) -> dict:
    db = get_database()
    collection = db[USERS_COLLECTION]

    document = {
        "user_id": user_id,
        "email": email.lower(),
        "password_hash": password_hash,
        "role": role,
        "is_active": True,
        "created_at": datetime.now(timezone.utc),
    }

    try:
        await collection.insert_one(document)
    except DuplicateKeyError as exc:
        raise DuplicateUserRecordError("User with this email already exists") from exc

    return document


async def get_user_by_email(email: str) -> dict | None:
    db = get_database()
    collection = db[USERS_COLLECTION]

    return await collection.find_one(
        {"email": email.lower()}
    )


async def get_user_by_id(user_id: str) -> dict | None:
    db = get_database()
    collection = db[USERS_COLLECTION]

    return await collection.find_one(
        {"user_id": user_id}
    )
