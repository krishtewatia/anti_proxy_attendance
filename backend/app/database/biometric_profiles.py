from datetime import datetime, timezone
from typing import Any

from app.database.mongodb import get_database

BIOMETRIC_PROFILES_COLLECTION = "biometric_profiles"


async def upsert_biometric_profile(
    *,
    identity: str,
    mean_embedding: list[float],
    sample_count: int,
    quality_score: float,
    enrolled_by: str,
    review_status: str = "ACTIVE",
) -> tuple[dict[str, Any], bool]:
    """Insert or update a student biometric profile.

    Returns (document, is_new).
    """
    db = get_database()
    collection = db[BIOMETRIC_PROFILES_COLLECTION]
    now = datetime.now(timezone.utc)

    existing = await collection.find_one({"identity": identity})
    if existing:
        await collection.update_one(
            {"identity": identity},
            {
                "$set": {
                    "mean_embedding": mean_embedding,
                    "sample_count": sample_count,
                    "quality_score": quality_score,
                    "enrolled_by": enrolled_by,
                    "review_status": review_status,
                    "updated_at": now,
                }
            },
        )
        updated = await collection.find_one({"identity": identity})
        return updated, False

    doc = {
        "identity": identity,
        "mean_embedding": mean_embedding,
        "sample_count": sample_count,
        "quality_score": quality_score,
        "enrolled_by": enrolled_by,
        # PENDING_REVIEW templates are never served to the vision service.
        "review_status": review_status,
        "created_at": now,
        "updated_at": now,
    }
    await collection.insert_one(doc)
    return doc, True


async def get_biometric_profile(identity: str) -> dict[str, Any] | None:
    """Retrieve biometric profile by identity."""
    db = get_database()
    collection = db[BIOMETRIC_PROFILES_COLLECTION]
    return await collection.find_one({"identity": identity})


async def delete_biometric_profile(identity: str) -> bool:
    """Delete a biometric profile by identity."""
    db = get_database()
    collection = db[BIOMETRIC_PROFILES_COLLECTION]
    res = await collection.delete_one({"identity": identity})
    return res.deleted_count > 0


async def list_all_biometric_profiles() -> list[dict[str, Any]]:
    """Retrieve all biometric profile metadata (without exposing embeddings)."""
    db = get_database()
    collection = db[BIOMETRIC_PROFILES_COLLECTION]
    cursor = collection.find({}, {"mean_embedding": 0}).sort("identity", 1)
    return await cursor.to_list(length=None)


async def get_all_embeddings() -> dict[str, list[float]]:
    """Retrieve mapping of identity to mean embedding for duplicate checking and gallery sync."""
    db = get_database()
    collection = db[BIOMETRIC_PROFILES_COLLECTION]
    cursor = collection.find({}, {"identity": 1, "mean_embedding": 1})
    docs = await cursor.to_list(length=None)
    return {d["identity"]: d["mean_embedding"] for d in docs if "mean_embedding" in d}
