from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

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
    status: str = "APPROVED",
) -> dict:
    db = get_database()
    collection = db[USERS_COLLECTION]

    document = {
        "user_id": user_id,
        "email": email.lower(),
        "password_hash": password_hash,
        "role": role,
        # PENDING for public registrations until an administrator approves them.
        "status": status,
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

    return await collection.find_one({"email": email.lower()})


async def get_user_by_id(user_id: str) -> dict | None:
    db = get_database()
    collection = db[USERS_COLLECTION]

    return await collection.find_one({"user_id": user_id})


async def get_all_users(role: str | None = None) -> list[dict]:
    """Retrieve all user profiles excluding password hashes (Admin query)."""
    db = get_database()
    collection = db[USERS_COLLECTION]

    query = {}
    if role:
        query["role"] = role.upper()

    cursor = collection.find(query, {"password_hash": 0}).sort("created_at", -1)
    return await cursor.to_list(length=None)


async def delete_user_by_id(user_id: str) -> bool:
    """Delete a user account by user_id."""
    db = get_database()
    collection = db[USERS_COLLECTION]
    res = await collection.delete_one({"user_id": user_id})
    return res.deleted_count > 0
