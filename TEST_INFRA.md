# Test Infrastructure Specification: E2E Testing Track

**Project**: Anti-Proxy Real-Time Mobile Attendance Tracking System
**Document**: `TEST_INFRA.md`
**Track**: End-to-End Opaque-Box Verification Track (`tests/e2e/`)
**Specification Baseline**: `ORIGINAL_REQUEST.md`, `PROJECT.md`

---

## 1. Test Philosophy

The Anti-Proxy Attendance System relies on perception pipelines, real-time computer vision, directional boundary geometry, authenticated microservice communication, and persistent biometric state. To guarantee production readiness, the E2E testing framework follows strict **opaque-box, requirement-driven verification**:

1. **Requirement-Driven Derivation**:
   Every test case directly traces back to requirements defined in `ORIGINAL_REQUEST.md` (R1 through R4) and the Feature Inventory in `PROJECT.md`.
2. **Opaque-Box Observability**:
   Tests interact exclusively with observable external system boundaries:
   - Public HTTP REST API endpoints on `http://localhost:8000` (`/api/v1/auth/login`, `/api/v1/events`, `/api/v1/sessions/{id}/live-snapshot`, `/api/v1/attendance/{id}`).
   - Persistent database documents in MongoDB (`anti_proxy_attendance`).
   - Standard HTTP response codes, headers (`X-API-Key`, `Authorization: Bearer`), and structured JSON payloads.
3. **No Facade Tests & No Mock Cheating**:
   Tests must exercise real operational logic. Facade tests that trivially assert `True` or match fragile internal implementations without verifying interface contracts are strictly prohibited.
4. **Adversarial Boundary Validation**:
   Tests actively attack API boundaries with malformed inputs, missing authentication headers, invalid directional states, corrupted tracklets, and payload overages to confirm fail-closed security.
5. **Deterministic State Isolation**:
   Each test tier sets up its own isolated context or operates idempotently on verified state, ensuring clean execution whether run individually or as part of a full regression suite.

---

## 2. Feature Inventory Mapping

| # | Feature (from `PROJECT.md`) | Description | Target Tier | E2E Test Module |
|---|-----------------------------|-------------|-------------|-----------------|
| 1 | DB Purge & Clean Seeding | Purge mock users (`alice`, `bob`, `charlie`) and seed exactly 1 Admin, 1 Teacher, 4 Students | **Tier 1** | `test_tier1_clean_seeding.py` |
| 2 | Authentic Biometric Embeddings | InsightFace `buffalo_l` 512-d normalized mean vectors for `person_01`..`person_04` | **Tier 1** | `test_tier1_clean_seeding.py` |
| 3 | Camera & Session Setup | Doorway camera `CAM_ROOM_101_DOOR` and active session `sess_demo_cs101` in `ROOM_101` | **Tier 1** | `test_tier1_clean_seeding.py` |
| 4 | Vertical Boundary Crossing | Geometry line $x = 0.5 \cdot \text{width}$, Side A $\to$ Side B (`ENTRY`), Side B $\to$ Side A (`EXIT`) | **Tier 3, Tier 4** | `test_tier3_events_and_snapshots.py`, `test_tier4_demo_lifecycle.py` |
| 5 | Rapid Transit Gating | Immediate identity confirmation and event emission on doorway transit | **Tier 3** | `test_tier3_events_and_snapshots.py` |
| 6 | Kinematic Anti-Spoof Policy | Policy set to `FLAG` preventing drop of fast doorway crossings | **Tier 2, Tier 3** | `test_tier2_api_boundary_security.py` |
| 7 | Mobile WebRTC HUD & Fallback | Manual transit fallback buttons and boundary guidance | **Tier 3** | `test_tier3_events_and_snapshots.py` |
| 8 | Event Dispatch to Backend | Dispatches verified transit events to `POST /api/v1/events` with camera API key | **Tier 2, Tier 3** | `test_tier2_api_boundary_security.py`, `test_tier3_events_and_snapshots.py` |
| 9 | Streamlined Teacher Dashboard | Teacher session inspection and attendance roster observation | **Tier 3, Tier 4** | `test_tier3_events_and_snapshots.py`, `test_tier4_demo_lifecycle.py` |
| 10 | 4-Student Ledger with Dwell Timers | Student status cards (`INSIDE`, `OUTSIDE`, `NOT_SEEN`) with dwell timers | **Tier 3, Tier 4** | `test_tier3_events_and_snapshots.py`, `test_tier4_demo_lifecycle.py` |
| 11 | Real-Time Snapshot Polling | Polling `GET /api/v1/sessions/{id}/live-snapshot` reflecting backend transit changes | **Tier 3, Tier 4** | `test_tier3_events_and_snapshots.py`, `test_tier4_demo_lifecycle.py` |
| 12 | Automated Verification Script | Programmatic verification of seeding, events ingestion, and state transitions | **Tier 4** | `test_tier4_demo_lifecycle.py` |
| 13 | Operational Runbook | Exact commands and runtime orchestration for 4-person demo | **All Tiers** | `run_tests.py` |
| 14 | Opaque-Box E2E Testing Suite | Multi-tier test suite covering all features, boundary cases, and demo scenarios | **All Tiers** | `tests/e2e/` |

---

## 3. Test Architecture & Runner Invocation

```
                           +-------------------------------------+
                           |            Test Runners             |
                           |  pytest tests/e2e/                  |
                           |  python tests/e2e/run_tests.py      |
                           +------------------+------------------+
                                              |
               +------------------------------+-------------------------------+
               |                              |                               |
               v                              v                               v
    +--------------------+       +-------------------------+       +---------------------+
    |  Tier 1: Seeding   |       |    Tier 2: Boundary     |       |   Tier 3 & Tier 4   |
    |  & Biometrics      |       |    & API Security       |       |   Events & Demo     |
    +---------+----------+       +------------+------------+       +----------+----------+
              |                               |                               |
              v                               v                               v
    +--------------------+       +-------------------------+       +---------------------+
    | MongoDB (27017)    |       | FastAPI Backend (8000)  |       | FastAPI (8000) +    |
    | - users            |       | - POST /api/v1/events   |       | MongoDB (27017)     |
    | - biometric_prof.  |       | - GET  /sessions/live   |       | - Events Ingestion  |
    | - cameras, sessions|       | - 401, 403, 413, 422    |       | - Live Snapshot     |
    +--------------------+       +-------------------------+       +---------------------+
```

### 3.1 Network & Service Prerequisites
- **FastAPI Backend**: `http://localhost:8000` (live HTTP daemon or in-process ASGI fallback).
- **MongoDB**: `localhost:27017` authenticated via:
  `mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance`
- **Vision Service**: `http://localhost:8088` (status check).

### 3.2 Execution Modes & Invocation Commands
The test suite is executable via two primary commands from the project root:

1. **Standard Pytest Runner**:
   ```powershell
   # Run the entire E2E test suite
   pytest tests/e2e/ -v

   # Run a specific tier
   pytest tests/e2e/test_tier1_clean_seeding.py -v
   pytest tests/e2e/test_tier2_api_boundary_security.py -v
   pytest tests/e2e/test_tier3_events_and_snapshots.py -v
   pytest tests/e2e/test_tier4_demo_lifecycle.py -v
   ```

2. **Standalone Runner (`run_tests.py`)**:
   ```powershell
   # Run all 4 tiers with formatted ANSI reporting and diagnostics
   python tests/e2e/run_tests.py

   # Run specific tier
   python tests/e2e/run_tests.py --tier 1
   python tests/e2e/run_tests.py --tier 2
   python tests/e2e/run_tests.py --tier 3
   python tests/e2e/run_tests.py --tier 4
   ```

### 3.3 Pass / Fail Semantics
- **Zero Regression Policy**: An exit code of `0` requires 100% test passage across all assertions. Any failure returns exit code `1`.
- **Strict Response Assertions**: HTTP status codes, headers, and response schemas are strictly verified against Pydantic models.
- **Fail-Closed Security**: Missing or invalid security tokens must return HTTP 401 or 403; 2xx responses under invalid credentials fail immediately.

---

## 4. 4-Tier Test Design

### Tier 1: Clean Seeding & Biometric Validation (`test_tier1_clean_seeding.py`)
- **Scope**: Verifies Requirement R1 and Milestone M1 deliverables in database persistence.
- **Test Scenarios**:
  1. `test_clean_seeding_collection_counts`:
     - Asserts synthetic mock accounts (`alice`, `bob`, `charlie`, dummy teachers) are completely purged.
     - Confirms exact collection counts:
       - `users`: exactly 6 (1 Admin, 1 Teacher, 4 Students).
       - `student_profiles`: exactly 4 (`STU_001` through `STU_004`).
       - `biometric_profiles`: exactly 4 (`person_01` through `person_04`).
       - `cameras`: exactly 1 (`CAM_ROOM_101_DOOR`).
       - `sessions`: exactly 1 active demo session (`sess_demo_cs101`).
       - `session_rosters`: exactly 1 active roster enrolling all 4 demo students.
  2. `test_camera_doorway_vertical_configuration`:
     - Asserts `CAM_ROOM_101_DOOR` is registered in `ROOM_101` with status `CONNECTED`.
     - Validates boundary coordinates: vertical dividing line `p1: [0.5, 0.0]`, `p2: [0.5, 1.0]`, and `entry_side: "SIDE_A"`.
  3. `test_authentic_512d_biometric_embeddings`:
     - Inspects all 4 biometric profiles in `biometric_profiles`.
     - Asserts dimension is exactly 512 floats (`len(mean_embedding) == 512`).
     - Asserts L2 normalization: $\|v\|_2 = 1.0 \pm 10^{-4}$.
     - Asserts vector variance: $\text{std}(v) > 0.01$ (confirms genuine neural network features, rejecting mathematical mock formulas).
     - Asserts identity uniqueness: pairwise cosine similarity between different students is $< 0.80$.
  4. `test_user_credentials_authentication`:
     - Admin authentication: `POST /api/v1/auth/login` with `admin@system.local` / `AdminDevPass123!` returns `200 OK` and valid JWT token with role `ADMIN`.
     - Teacher authentication: `POST /api/v1/auth/login` with `teacher@demo.edu` / `TeacherDevPass123!` returns `200 OK` and valid JWT token with role `TEACHER`.
     - Student authentication: `POST /api/v1/auth/login` with `student1@demo.edu` / `StudentDevPass123!` returns `200 OK` and valid JWT token with role `STUDENT`.
     - Rejection of invalid credentials: bad password returns `401 Unauthorized`.

### Tier 2: API Boundary & Security Validation (`test_tier2_api_boundary_security.py`)
- **Scope**: Verifies API security, payload sanitization, and defensive gating.
- **Test Scenarios**:
  1. `test_events_missing_api_key_rejected`:
     - `POST /api/v1/events` without `X-API-Key` header returns `HTTP 401 Unauthorized`.
  2. `test_events_invalid_api_key_rejected`:
     - `POST /api/v1/events` with `X-API-Key: invalid-vision-key-secret-999` returns `HTTP 401 Unauthorized`.
  3. `test_events_invalid_direction_rejected`:
     - `POST /api/v1/events` with `direction: "SIDEWAYS"` or `direction: "UNKNOWN"` returns `HTTP 422 Unprocessable Entity`.
  4. `test_events_empty_identity_rejected`:
     - `POST /api/v1/events` with `identity: ""` returns `HTTP 422 Unprocessable Entity`.
  5. `test_events_out_of_bounds_similarity_rejected`:
     - `POST /api/v1/events` with `peak_similarity: 2.5` ($> 1.0$) or negative frames returns `HTTP 422`.
  6. `test_events_excessive_payload_size_rejected`:
     - `POST /api/v1/events` with payload $> 65536$ bytes returns `HTTP 413 Request Entity Too Large`.
  7. `test_live_snapshot_unauthenticated_rejected`:
     - `GET /api/v1/sessions/sess_demo_cs101/live-snapshot` without Bearer token returns `HTTP 401 Unauthorized`.
  8. `test_live_snapshot_student_role_forbidden`:
     - `GET /api/v1/sessions/sess_demo_cs101/live-snapshot` with student Bearer token returns `HTTP 403 Forbidden`.
  9. `test_live_snapshot_unowned_session_forbidden`:
     - Teacher accessing another teacher's session returns `HTTP 403 Forbidden`.
  10. `test_live_snapshot_nonexistent_session_not_found`:
      - `GET /api/v1/sessions/sess_does_not_exist/live-snapshot` returns `HTTP 404 Not Found`.

### Tier 3: Event Ingestion & Live Snapshot State Transitions (`test_tier3_events_and_snapshots.py`)
- **Scope**: Verifies real-time event ingestion and live snapshot telemetry.
- **Test Scenarios**:
  1. `test_event_ingestion_acceptance_and_idempotency`:
     - Ingest valid `ENTRY` transit event for `person_01` via `POST /api/v1/events`.
     - Returns `HTTP 201 Created` with `status: "accepted"`.
     - Re-submitting the exact same `event_id` returns `HTTP 200 OK` with `status: "duplicate"`.
  2. `test_live_snapshot_initial_state_not_seen`:
     - Prior to transit events, enrolled students report `state: "NOT_SEEN"` and `presence_duration_seconds: 0.0`.
  3. `test_live_snapshot_transition_to_inside`:
     - Upon `ENTRY` event ingestion, student state transitions from `NOT_SEEN` $\to$ `INSIDE`.
     - Asserts `last_event_direction: "ENTRY"`, `no_exit_observed: True`.
     - Recent events feed in snapshot contains the ingested entry event.
  4. `test_live_snapshot_transition_to_outside`:
     - Upon subsequent `EXIT` event ingestion for `person_01`, state transitions from `INSIDE` $\to$ `OUTSIDE`.
     - Asserts `last_event_direction: "EXIT"`, `no_exit_observed: False`.
     - Presence duration reflects the closed interval between entry and exit.
  5. `test_unseen_students_isolation`:
     - Non-transiting students (`person_02`, `person_03`, `person_04`) remain strictly `NOT_SEEN` with 0.0 seconds.

### Tier 4: Full Demo Lifecycle Simulation (`test_tier4_demo_lifecycle.py`)
- **Scope**: Rehearses the complete end-to-end 4-student demo scenario.
- **Test Scenarios**:
  1. `test_full_demo_4student_lifecycle`:
     - **Pre-condition**: Teacher logs in, retrieves CS-101 session details.
     - **T0**: Initial snapshot check: all 4 students (`student1`..`student4`) enrolled and `NOT_SEEN`.
     - **T1**: Student 1 enters doorway (`ENTRY` event emitted, transitions to `INSIDE`).
     - **T2**: Student 2 enters doorway (`ENTRY` event emitted, transitions to `INSIDE`).
     - **T3**: Student 3 enters doorway (`ENTRY` event emitted, transitions to `INSIDE`).
     - **T4**: Student 4 does NOT enter (remains `NOT_SEEN`).
     - **T5 (Dwell Accumulation)**: Polling snapshot confirms continuous presence accumulation for Students 1, 2, and 3.
     - **T6**: Student 2 exits doorway (`EXIT` event emitted, transitions to `OUTSIDE` with closed dwell time).
     - **T7 (Ledger Calculation & Finalization)**:
       - Teacher finalizes session via `POST /api/v1/sessions/{session_id}/finalize`.
       - Roster ledger verified:
         - Student 1 (`person_01`): Present, accumulated duration recorded.
         - Student 2 (`person_02`): Present or partial duration with closed entry/exit interval.
         - Student 3 (`person_03`): Present, accumulated duration recorded.
         - Student 4 (`person_04`): Absent, 0.0 seconds duration, status `ABSENT`.
       - Audit log records `ATTENDANCE_FINALIZED`.

---

## 5. Verification & Diagnostics Tooling

The E2E test runner outputs structured diagnostic summaries detailing:
- Total assertions executed.
- Elapsed duration per tier.
- Database collection state verification.
- HTTP status code and latency distributions.
- Traceback details for any contract regressions.
