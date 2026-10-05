"""Unit and integration tests for Student Face Enrollment Hardening (Step 2E.2).

Verifies:
1. RBAC: TEACHER and ADMIN can enroll/re-enroll/delete; STUDENT cannot.
2. Cross-student duplicate detection by similarity threshold (409 Conflict).
3. Re-enrollment and deletion flows.
4. Audit trail logging for FACE_ENROLLED, FACE_REENROLLED, and FACE_DELETED.
5. Security: raw embeddings are never exposed in public profile responses or audit logs.
6. Gallery endpoint restricted to ADMIN only.
"""

from datetime import datetime, timezone
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.core.config import settings
from app.database import get_database, mongodb
from app.database.users import create_user
from app.main import app
from app.security.jwt import create_access_token
from app.security.passwords import hash_password


def generate_unit_vector(dim: int = 512, seed: int = 1) -> list[float]:
    """Generate a deterministic normalized unit vector."""
    import math
    vals = [math.sin(i * seed + 1.0) for i in range(dim)]
    norm = math.sqrt(sum(v * v for v in vals))
    return [v / norm for v in vals]


@pytest.fixture(autouse=True)
def setup_test_db():
    mock_client = AsyncMongoMockClient()
    mongodb._client = mock_client
    db = mock_client[settings.DATABASE_NAME]

    app.dependency_overrides[get_database] = lambda: db
    yield
    app.dependency_overrides.clear()


@pytest.mark.anyio
async def test_enrollment_rbac_enforcement():
    """Verify RBAC: TEACHER/ADMIN can enroll faces; STUDENT is forbidden."""
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await db["biometric_profiles"].delete_many({})

    # 1. Provision accounts
    await create_user(
        user_id="teacher_user",
        email="teacher.enroll@university.edu",
        password_hash=hash_password("TeacherSecure2026!"),
        role="TEACHER",
    )
    await create_user(
        user_id="student_user",
        email="student.enroll@university.edu",
        password_hash=hash_password("StudentSecure2026!"),
        role="STUDENT",
    )
    await create_user(
        user_id="admin_user",
        email="admin.enroll@university.edu",
        password_hash=hash_password("AdminSecure2026!"),
        role="ADMIN",
    )

    token_teacher = create_access_token(user_id="teacher_user", role="TEACHER")
    token_student = create_access_token(user_id="student_user", role="STUDENT")
    token_admin = create_access_token(user_id="admin_user", role="ADMIN")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "identity": "person_01",
            "mean_embedding": generate_unit_vector(seed=10),
            "sample_count": 3,
            "quality_score": 0.92,
        }

        # A. Student attempt must be FORBIDDEN (403)
        res_student = await client.post(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_student}"},
            json=payload,
        )
        assert res_student.status_code == 403
        assert res_student.json()["detail"] == "Insufficient permissions"

        # B. Unauthenticated attempt must be UNAUTHORIZED (401)
        res_anon = await client.post("/api/v1/enrollment", json=payload)
        assert res_anon.status_code == 401

        # C. Teacher attempt must SUCCEED (201)
        res_teacher = await client.post(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_teacher}"},
            json=payload,
        )
        assert res_teacher.status_code == 201
        data = res_teacher.json()
        assert data["identity"] == "person_01"
        assert data["sample_count"] == 3
        assert data["enrolled_by"] == "teacher_user"
        # SECURITY: mean_embedding must NEVER be in response
        assert "mean_embedding" not in data

        # D. Admin attempt for another identity must SUCCEED (201)
        payload2 = {
            "identity": "person_02",
            "mean_embedding": generate_unit_vector(seed=20),
            "sample_count": 4,
            "quality_score": 0.88,
        }
        res_admin = await client.post(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_admin}"},
            json=payload2,
        )
        assert res_admin.status_code == 201
        assert res_admin.json()["identity"] == "person_02"


@pytest.mark.anyio
async def test_cross_student_duplicate_detection():
    """Verify that enrolling an embedding matching an existing student above 0.70 similarity is rejected."""
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await db["biometric_profiles"].delete_many({})

    await create_user(
        user_id="teacher_dup",
        email="teacher.dup@university.edu",
        password_hash=hash_password("TeacherSecure2026!"),
        role="TEACHER",
    )
    token = create_access_token(user_id="teacher_dup", role="TEACHER")
    headers = {"Authorization": f"Bearer {token}"}

    emb_1 = generate_unit_vector(seed=42)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Enroll student 1
        res1 = await client.post(
            "/api/v1/enrollment",
            headers=headers,
            json={
                "identity": "student_alice",
                "mean_embedding": emb_1,
                "sample_count": 3,
                "quality_score": 0.95,
            },
        )
        assert res1.status_code == 201

        # 2. Attempt to enroll student 2 with identical embedding (sim = 1.0)
        res_dup = await client.post(
            "/api/v1/enrollment",
            headers=headers,
            json={
                "identity": "student_bob",
                "mean_embedding": emb_1,
                "sample_count": 3,
                "quality_score": 0.91,
            },
        )
        assert res_dup.status_code == 409
        err_msg = res_dup.json()["detail"]
        assert "DUPLICATE_IDENTITY_DETECTED" in err_msg
        assert "student_alice" in err_msg

        # 3. Attempt to enroll student 3 with a distinct embedding (seed=999) -> must succeed
        emb_distinct = generate_unit_vector(seed=999)
        res_distinct = await client.post(
            "/api/v1/enrollment",
            headers=headers,
            json={
                "identity": "student_charlie",
                "mean_embedding": emb_distinct,
                "sample_count": 3,
                "quality_score": 0.89,
            },
        )
        assert res_distinct.status_code == 201


@pytest.mark.anyio
async def test_reenroll_and_delete_with_audit_trail():
    """Verify re-enrollment, deletion, and complete audit logging."""
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await db["biometric_profiles"].delete_many({})
    await db["audit_events"].delete_many({})

    await create_user(
        user_id="admin_auditor",
        email="admin.audit@university.edu",
        password_hash=hash_password("AdminSecure2026!"),
        role="ADMIN",
    )
    token = create_access_token(user_id="admin_auditor", role="ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Step 1: Initial enrollment
        emb_initial = generate_unit_vector(seed=101)
        res_enroll = await client.post(
            "/api/v1/enrollment",
            headers=headers,
            json={
                "identity": "student_dave",
                "mean_embedding": emb_initial,
                "sample_count": 3,
                "quality_score": 0.85,
            },
        )
        assert res_enroll.status_code == 201

        # Step 2: Re-enroll / update template
        emb_updated = generate_unit_vector(seed=102)
        res_reenroll = await client.put(
            "/api/v1/enrollment/student_dave",
            headers=headers,
            json={
                "identity": "student_dave",
                "mean_embedding": emb_updated,
                "sample_count": 5,
                "quality_score": 0.96,
            },
        )
        assert res_reenroll.status_code == 200
        assert res_reenroll.json()["sample_count"] == 5

        # Step 3: Delete profile
        res_del = await client.delete(
            "/api/v1/enrollment/student_dave",
            headers=headers,
        )
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "success"

        # Deleting again returns 404
        res_del_again = await client.delete(
            "/api/v1/enrollment/student_dave",
            headers=headers,
        )
        assert res_del_again.status_code == 404

        # Step 4: Verify Audit Trail in MongoDB
        audit_events = await db["audit_events"].find(
            {"resource_id": "student_dave"}
        ).sort("timestamp", 1).to_list(length=None)

        actions = [a["action"] for a in audit_events]
        assert actions == ["FACE_ENROLLED", "FACE_REENROLLED", "FACE_DELETED"]

        for evt in audit_events:
            assert evt["resource_type"] == "BIOMETRIC_PROFILE"
            assert evt["actor_user_id"] == "admin_auditor"
            assert evt["actor_role"] == "ADMIN"
            # SECURITY: Embeddings must NOT be in audit metadata
            assert "mean_embedding" not in evt["metadata"]
            assert "embedding" not in evt["metadata"]


@pytest.mark.anyio
async def test_gallery_sync_security():
    """Verify GET /api/v1/enrollment/gallery is restricted to ADMIN and returns correct template count."""
    db = mongodb.get_database()
    await db["users"].delete_many({})
    await db["biometric_profiles"].delete_many({})

    await create_user(
        user_id="teacher_gal",
        email="teacher.gal@university.edu",
        password_hash=hash_password("TeacherSecure2026!"),
        role="TEACHER",
    )
    await create_user(
        user_id="admin_gal",
        email="admin.gal@university.edu",
        password_hash=hash_password("AdminSecure2026!"),
        role="ADMIN",
    )

    token_teacher = create_access_token(user_id="teacher_gal", role="TEACHER")
    token_admin = create_access_token(user_id="admin_gal", role="ADMIN")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Enroll 2 students
        await client.post(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "identity": "person_01",
                "mean_embedding": generate_unit_vector(seed=1),
                "sample_count": 3,
                "quality_score": 0.9,
            },
        )
        await client.post(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_admin}"},
            json={
                "identity": "person_02",
                "mean_embedding": generate_unit_vector(seed=2),
                "sample_count": 4,
                "quality_score": 0.85,
            },
        )

        # 1. Public list endpoint returns 2 items without embeddings
        list_resp = await client.get(
            "/api/v1/enrollment",
            headers={"Authorization": f"Bearer {token_teacher}"},
        )
        assert list_resp.status_code == 200
        profiles = list_resp.json()
        assert len(profiles) == 2
        for p in profiles:
            assert "mean_embedding" not in p
            assert p["identity"] in {"person_01", "person_02"}

        # 2. Gallery sync endpoint: TEACHER is forbidden (403)
        gal_teacher = await client.get(
            "/api/v1/enrollment/gallery",
            headers={"Authorization": f"Bearer {token_teacher}"},
        )
        assert gal_teacher.status_code == 403

        # 3. Gallery sync endpoint: ADMIN succeeds (200) and receives vectors
        gal_admin = await client.get(
            "/api/v1/enrollment/gallery",
            headers={"Authorization": f"Bearer {token_admin}"},
        )
        assert gal_admin.status_code == 200
        gal_data = gal_admin.json()
        assert gal_data["count"] == 2
        assert set(gal_data["gallery"].keys()) == {"person_01", "person_02"}
        assert len(gal_data["gallery"]["person_01"]) == 512
