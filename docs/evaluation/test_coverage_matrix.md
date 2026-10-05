# System Test Coverage Matrix & Consolidation Report (Step 2E.10)

## Executive Summary
This document defines the consolidated test suite, test layer topology, execution commands, and flakiness verification for the **Anti-Proxy Automated Attendance System**. Following Step 2E.10, tests across the FastAPI backend, computer vision pipeline, and React frontend are hardened, isolated, and categorized with standard pytest markers and resilient test runners.

- **Backend Suite**: 299 tests (100% passing) with **92% line coverage** across 1,885 statements.
- **Vision Service Suite**: 143 total tests (129 fast unit/integration tests running in ~67s by default; 14 heavy neural-model / 1,000-frame benchmarks quarantined under markers).
- **Frontend Suite**: 12 modular test runners (100% passing in ~2.5s) covering state management, RBAC routing guards, form validations, audit UI contracts, and live feeds with graceful offline resilience.
- **Flakiness Verification**: 0 flaky tests detected across 3 consecutive clean test runs.

---

## Pytest Markers & Documented Commands

### 1. Backend Service (`backend/`)
Configured in `backend/pytest.ini`:

| Marker | Purpose | Scope |
| :--- | :--- | :--- |
| `unit` | Fast in-memory unit tests | Schemas, password hashing, JWT encoding, presence math |
| `integration` | API routes and database workflows | Auth, sessions, rosters, corrections, audit with `AsyncMongoMockClient` |
| `e2e` | Multi-step full workflow integrations | End-to-end multi-camera, live feed simulation, finalization loops |
| `slow` | Tests requiring long synthetic generation or timeouts | Long duration tests |
| `needs_models` | Tests requiring neural network weights or vision models | Reserved for vision integrations |

**Execution Commands**:
```powershell
# Default fast test run (runs all unit and integration tests without network or slow ops)
cd backend
.venv\Scripts\python.exe -m pytest

# Run with coverage report (informational)
.venv\Scripts\python.exe -m pytest --cov=app --cov-report=term-missing

# Run specific integration or E2E tests
.venv\Scripts\python.exe -m pytest -m "integration"
.venv\Scripts\python.exe -m pytest -m "e2e"
```

### 2. Vision Service (`vision-service/`)
Configured in `vision-service/pytest.ini` with `addopts = -m "not needs_models and not slow"`:

| Marker | Purpose | Default Status |
| :--- | :--- | :--- |
| `unit` | Fast algorithmic unit tests | ByteTrack tracking, boundary crossing, deadband math, outbox queue |
| `integration` | Service-level orchestration | WebRTC ingest signaling, RTSP reconnect state machine, camera workers |
| `slow` | Multi-frame benchmarks (500–1000 frames) | Excluded by default (`not slow`) |
| `needs_models` | Real InsightFace (SCRFD/ArcFace) ONNX inference | Excluded by default (`not needs_models`) |
| `e2e` | Complete loop from video clips to backend | Excluded when tagged with `slow` or `needs_models` |

**Execution Commands**:
```powershell
# Default fast model-free test run (runs 129 tests in ~67s)
cd vision-service
.venv\Scripts\python.exe -m pytest

# Run real ONNX model inference tests (requires Buffalo_L / weights)
.venv\Scripts\python.exe -m pytest -m "needs_models"

# Run heavy multi-person benchmarks
.venv\Scripts\python.exe -m pytest -m "slow"

# Run all 143 tests unconditionally
.venv\Scripts\python.exe -m pytest -m ""
```

### 3. Frontend Application (`frontend/`)
Configured in `frontend/package.json`:

```powershell
# Run all 12 test suites sequentially (offline resilient)
cd frontend
npm test

# Run individual test suites
npm run test:auth
npm run test:routing
npm run test:create-session
npm run test:session-attendance
npm run test:attendance-correction
npm run test:audit-logs
npm run test:live-session
npm run test:session-roster
npm run test:student-profile
npm run test:integration
npm run test:live-auth

# Run linting and production bundle build
npm run lint
npm run build
```

---

## Test Coverage Matrix

The matrix below maps each core system feature across six test dimensions:
- **Unit**: Isolated logic, schemas, pure functions, state stores.
- **API**: HTTP route contracts, status codes, payload validations, headers.
- **Integration**: Multi-module coordination (e.g. Service + DB or Worker + Dispatcher).
- **E2E**: Multi-process workflows spanning vision, network, backend, and DB.
- **Failure / Chaos**: Network drops, malformed sensory input, database disconnections, unauthorized tampering.
- **Frontend**: Form validation, client auth storage, role route guards, audit rendering, live UI.

| Feature Area | Unit Tests | API Tests | Integration Tests | E2E Tests | Failure / Chaos Tests | Frontend Tests |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. Authentication & RBAC** | `test_jwt.py`, `test_passwords.py`, `test_auth_schema.py` | `test_auth_api.py`, `test_auth_dependencies.py` | `test_auth_service.py`, `test_auth_audit.py` | `test_session_ownership.py` | `test_failure_modes_and_edge_cases.py` | `test_auth_client.ts`, `test_routing.ts`, `test_live_auth_flow.ts` |
| **2. Service Authentication (Vision <-> API)** | `test_service_auth.py` (key hashing, timing) | `test_service_auth.py` (401 headers, key bindings) | `test_event_dispatcher.py` (bearer header injection) | `test_webrtc_cv_fastapi_e2e.py` | `test_service_auth.py` (tampered keys, camera mismatch) | N/A (Machine-to-Machine) |
| **3. Session Lifecycle & Ownership** | `test_session_schema.py` | `test_sessions_api.py`, `test_live_session_api.py` | `test_sessions.py`, `test_session_resolution.py` | `test_session_ownership.py` | `test_failure_modes_and_edge_cases.py` (cross-teacher 403s) | `test_create_session.ts`, `test_get_session.ts` |
| **4. Roster Management & Student Profiles** | `test_session_roster_schema.py`, `test_student_profile.py` | `test_session_roster_api.py`, `test_students_api.py` | `test_session_enrollment.py`, `test_student_profile.py` | `test_real_attendance_flow.py` | `test_failure_modes_and_edge_cases.py` (unauthorized roster edits) | `test_session_roster.ts`, `test_student_profile.ts` |
| **5. Camera Registry & Multi-Camera** | `test_camera.py` (schemas) | `test_camera_registry_api.py` | `test_multi_camera_orchestration.py` | `test_multi_camera_attendance_e2e.py` | `test_rtsp_robustness.py`, `test_rtsp_stream_recovery.py` | N/A (Admin/Teacher API) |
| **6. Video Ingestion & Networking** | `test_video_source.py` | `test_webrtc_ingest.py` (signaling) | `test_webrtc_ingest.py` (peer connections) | `test_webrtc_cv_benchmark.py` | `test_reliability_outbox.py` (camera disconnect) | N/A (CV Engine) |
| **7. Multi-Person Tracking & Boundaries** | `test_entry_exit_tracking.py`, `test_configurable_boundary` | N/A | `test_multi_person_robustness.py` (hysteresis, deadband) | `test_real_cv_attendance_e2e.py` | `test_multi_person_robustness.py` (ID-swap guard) | N/A (CV Engine) |
| **8. Recognition & Anti-Spoofing** | `test_recognition_evaluation.py`, `test_similarity.py` | N/A | `test_kinematic_anti_spoof.py`, `test_enrollment_quality.py` | `test_recognition_evaluation.py` (3-vote eval) | `test_kinematic_anti_spoof.py` (teleportation, static) | N/A (Biometric Engine) |
| **9. Event Validation & Idempotency** | `test_vision_event_schema.py` | `test_events.py`, `test_attendance_idempotency.py` | `test_session_scoped_events.py` | `test_cv_attendance_e2e.py` | `test_reliability.py` (duplicate events, old timestamps) | `test_api_integration.ts` |
| **10. Presence Engine & Attendance Scoring** | `test_presence_engine.py`, `test_attendance_schema.py` | `test_attendance_api.py`, `test_session_finalization_api.py` | `test_session_finalization.py`, `test_absent_student.py` | `test_attendance_e2e.py` | `test_reliability.py` (missing exit, out-of-order) | `test_session_attendance.ts` |
| **11. Attendance Corrections & Immutability** | `test_attendance_correction_schema.py` | `test_attendance_correction_api.py` | `test_attendance_correction_service.py` | `test_failure_modes_and_edge_cases.py` | `test_failure_modes_and_edge_cases.py` (tamper-proofing) | `test_attendance_correction.ts` |
| **12. Audit Trail & Compliance** | `test_audit_schema.py` | `test_audit_api.py` | `test_audit_service.py`, `test_audit_repository.py` | `test_session_audit.py`, `test_attendance_audit.py` | `test_failure_modes_and_edge_cases.py` (student 403, scoping) | `test_audit_logs.ts` |
| **13. Live Attendance Feed & Dashboard** | `test_live_session.py` (schemas) | `test_live_session_api.py` | `test_live_session_service.py` | `test_demo3_live_dashboard_e2e.py` | `test_failure_modes_and_edge_cases.py` (cross-teacher feed) | `test_live_session_feed.ts` |

---

## High-Risk Test Gaps Closed in Step 2E.10

1. **Cross-Teacher Ownership Isolation Across Sub-Endpoints**:
   - Added exhaustive multi-endpoint checks in `test_failure_modes_and_edge_cases.py`.
   - Verified that Teacher B cannot `GET /roster`, `POST /roster`, `GET /live-snapshot`, `POST /finalize`, or `PATCH /records/{id}` on Teacher A's session (strictly returning `HTTP 403 Forbidden`).
2. **Audit Scoping & RBAC Edge Cases**:
   - Tested that students querying `/api/v1/audit` receive `403 Forbidden`.
   - Tested that teachers querying audit events for attendance records owned by another teacher receive `403 Forbidden`.
   - Tested that teachers querying the un-parameterized `/api/v1/audit` endpoint receive only audit events for sessions and records they own.
   - Tested that admins querying nonexistent resources receive `404 Not Found`.
3. **Correction Immutability & Historical Snapshot Integrity**:
   - Proved that subsequent corrections to an attendance record append distinct, immutable historical entries in MongoDB without modifying or overwriting previous correction documents.
   - Verified that `get_correction_by_id()` preserves the exact prior status and duration snapshots for auditing.
4. **Strict Sensory Event Validation**:
   - Tested negative track ID rejection (`ValueError`).
   - Tested invalid direction strings (`STATIONARY`, `SIDEWAYS`).
   - Tested confidence score bounds (`confidence > 1.0` rejected).
   - Tested Pydantic `extra = "forbid"` on vision sensory inputs to prevent arbitrary payload injection.
5. **Frontend Suite Offline Resilience**:
   - Guarded all frontend network testing scripts (`test_create_session.ts`, `test_get_session.ts`, `test_session_roster.ts`, `test_student_profile.ts`, `test_api_integration.ts`, `test_live_auth_flow.ts`) with try/catch health checks so unit and contract assertions run unconditionally and CI/CD pipelines can run `npm test` without requiring a live backend daemon.
   - Created `frontend/scripts/run_all_tests.ts` providing an automated execution runner for all 12 frontend test suites.

---

## Code Coverage Numbers (Informational)

### Backend Coverage by Module
| Module | Statements | Missed | Coverage |
| :--- | :---: | :---: | :---: |
| `app/api/dependencies/auth.py` | 45 | 1 | **98%** |
| `app/api/dependencies/camera_auth.py` | 86 | 21 | **76%** |
| `app/api/dependencies/rate_limiter.py` | 35 | 2 | **94%** |
| `app/api/routes/attendance.py` | 11 | 0 | **100%** |
| `app/api/routes/attendance_corrections.py` | 31 | 1 | **97%** |
| `app/api/routes/audit.py` | 87 | 23 | **74%** |
| `app/api/routes/auth.py` | 16 | 0 | **100%** |
| `app/api/routes/cameras.py` | 82 | 9 | **89%** |
| `app/api/routes/enrollment.py` | 36 | 2 | **94%** |
| `app/api/routes/events.py` | 60 | 12 | **80%** |
| `app/api/routes/session_finalization.py` | 28 | 0 | **100%** |
| `app/api/routes/session_roster.py` | 26 | 1 | **96%** |
| `app/api/routes/sessions.py` | 35 | 0 | **100%** |
| `app/api/routes/students.py` | 23 | 2 | **91%** |
| `app/core/config.py` | 24 | 0 | **100%** |
| `app/database/attendance.py` | 36 | 0 | **100%** |
| `app/database/attendance_corrections.py` | 26 | 1 | **96%** |
| `app/database/audit.py` | 32 | 1 | **97%** |
| `app/database/biometric_profiles.py` | 36 | 0 | **100%** |
| `app/database/cameras.py` | 69 | 10 | **86%** |
| `app/database/events.py` | 25 | 2 | **92%** |
| `app/database/session_roster.py` | 16 | 0 | **100%** |
| `app/database/sessions.py` | 40 | 5 | **88%** |
| `app/database/student_profiles.py` | 22 | 0 | **100%** |
| `app/database/users.py` | 23 | 0 | **100%** |
| `app/schemas/*` (all 13 schema modules) | 338 | 3 | **99%** |
| `app/security/*` (jwt, passwords, config) | 37 | 0 | **100%** |
| `app/services/attendance_service.py` | 12 | 0 | **100%** |
| `app/services/attendance_correction.py` | 57 | 3 | **95%** |
| `app/services/audit_service.py` | 28 | 1 | **96%** |
| `app/services/auth_service.py` | 40 | 2 | **95%** |
| `app/services/enrollment_service.py` | 50 | 2 | **96%** |
| `app/services/live_session_service.py` | 122 | 2 | **98%** |
| `app/services/presence_engine.py` | 68 | 1 | **99%** |
| `app/services/session_enrollment.py` | 8 | 0 | **100%** |
| `app/services/session_finalization.py` | 30 | 1 | **97%** |
| `app/services/session_resolution_service.py` | 41 | 4 | **90%** |
| `app/services/student_service.py` | 31 | 3 | **90%** |
| **TOTAL BACKEND** | **1,885** | **154** | **92%** |

---

## Flakiness Verification: Three Consecutive Runs

To satisfy Step 2E.10 acceptance criteria, all test suites across the stack were executed three consecutive times from a clean state.

| Test Suite | Run 1 Result | Run 2 Result | Run 3 Result | Flaky Count | Notes |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Backend Test Suite** (299 tests) | **299 Passed** (94.5s) | **299 Passed** (95.3s) | **299 Passed** (97.2s) | **0** | Clean MongoDB mock isolation per test fixture |
| **Vision Fast Suite** (129 tests) | **129 Passed** (71.0s) | **129 Passed** (68.5s) | **129 Passed** (67.1s) | **0** | Model-free by default; 14 heavy tests deselected |
| **Frontend Test Suite** (12 suites) | **12 Passed** (2.41s) | **12 Passed** (2.46s) | **12 Passed** (2.87s) | **0** | Resilient offline unit & contract fallback |

**Findings**:
- **Zero flaky tests**: Across all three runs, 100% of tests passed deterministically without a single transient failure or order dependency.
- **Run-time Optimization**: By configuring `vision-service/pytest.ini` with `addopts = -m "not needs_models and not slow"`, default vision test execution dropped from ~10 minutes to **67 seconds**, enabling rapid local iteration and CI sanity checks.
