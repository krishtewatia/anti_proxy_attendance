# Project: Anti-Proxy Real-Time Mobile Attendance Tracking Demo

## Architecture
- **Data Layer (MongoDB)**: Port 27017 (`anti_proxy_attendance`). Authenticated connection (`antiproxy_user` / `admin`). Stores `users`, `student_profiles`, `biometric_profiles`, `session_rosters`, `sessions`, `cameras`, `attendance_events`, `attendance_records`.
- **Backend API (FastAPI)**: Port 8000. Provides authentication (`/api/v1/auth/login`), event ingestion (`/api/v1/events`), and live attendance snapshots (`/api/v1/sessions/{id}/live-snapshot`).
- **Vision Service (FastAPI + WebRTC + OpenCV + ByteTrack + InsightFace)**: Port 8088. Captures smartphone video stream via WebRTC (`HTML_PHONE_CLIENT`), tracks person movements across vertical boundary line, validates identity with buffalo_l embeddings, enforces rapid transit gating and kinematic anti-spoof policy `FLAG`, dispatches verified events to backend. Provides manual transit fallback buttons.
- **Frontend (React 19 + Vite 8 + TypeScript)**: Port 3000. Features teacher dashboard (`SessionDetails.tsx`) with live mobile scanner preview status and 4-student ledger (`🟢 IN ROOM`, `🟡 EXITED`, `⚪ NOT SEEN`) with live-updating dwell time progress bars polled every 2.5s.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | DB Purge & Clean Seeding | Purge mock users (`alice`, `bob`, `charlie`, dummy sessions/cameras) and seed exactly 1 Admin, 1 Teacher, 4 Students | M1 | R1 |
| 2 | Authentic Biometric Embeddings | InsightFace `buffalo_l` 512-d normalized mean vectors from `recognition_benchmark/person_0{1..4}/` | M1 | R1 |
| 3 | Camera & Session Setup | Seed `CAM_ROOM_101_DOOR` (vertical line) and `sess_demo_cs101` active for today with 4 students enrolled | M1 | R1 |
| 4 | Vertical Boundary Crossing | Geometry centerline $x = 0.5 \cdot \text{width}$, left-to-right (Side A -> Side B) = ENTRY, right-to-left = EXIT | M2 | R2 |
| 5 | Rapid Transit Gating | `min_supporting_frames` set to 1 or 2 for immediate identity confirmation on doorway transit | M2 | R2 |
| 6 | Kinematic Anti-Spoof Policy | Policy set to `FLAG` to prevent dropping fast doorway crossings (<0.20s) | M2 | R2 |
| 7 | Mobile WebRTC HUD & Fallback | Vertical line visual guide on phone client (port 8088) and 4-student manual transit fallback buttons | M2 | R2 |
| 8 | Event Dispatch to Backend | Dispatches verified transit events to `POST /api/v1/events` with camera API key | M2 | R2 |
| 9 | Streamlined Teacher Dashboard | Clean 2-column split view (Mobile Scanner on left, 4-student ledger on right), removing CCTV selectors | M3 | R3 |
| 10 | 4-Student Ledger with Dwell Timers | Student cards with `🟢 IN ROOM`, `🟡 EXITED`, `⚪ NOT SEEN` badges and real-time seconds-granularity dwell timers | M3 | R3 |
| 11 | Real-Time Snapshot Polling | Polling `GET /api/v1/sessions/{id}/live-snapshot` every 2.5s to update ledger without page reload | M3 | R3 |
| 12 | Automated Verification Script | `scripts/verify_demo_pipeline.py` verifying seeding, events ingestion, live snapshot transitions, and dwell times | M4 | R4 |
| 13 | Operational Runbook | Step-by-step terminal commands for rebuilding containers, seeding, and executing mobile demo | M4 | R4 |
| 14 | Opaque-Box E2E Testing Suite | Tier 1-4 test suite covering all features, boundary cases, cross-feature flows, and real-world demo scenarios | E2E | Dual Track |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Clean Demo Database Seeding | `scripts/seed_clean_demo.py`, MongoDB purge & authentic InsightFace seeding | none | PLANNED |
| M2 | Reliable Mobile Vision Pipeline | `live_cv_pipeline.py`, `run_webrtc_camera.py`, `webrtc_receiver.py` (vertical line, gating, HUD, buttons) | M1 | PLANNED |
| M3 | Teacher Dashboard & Ledger UI | `SessionDetails.tsx`, `attendance-helpers.ts` (split view, 4-student ledger, dwell format) | M1 | PLANNED |
| M4 | Automated Verification & Runbook | `scripts/verify_demo_pipeline.py` and `RUNBOOK.md` | M1, M2, M3 | PLANNED |
| E2E | E2E Testing Track | Requirement-driven test suite (Tiers 1-4) & `TEST_READY.md` | none | PLANNED |

## Interface Contracts
### `scripts/seed_clean_demo.py` ↔ Backend & Database
- Mongo URI: `mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance` (or root `admin:secure_root_mongo_dev_password_12345`).
- Admin user: `user_admin_001`, `admin@system.local`, role `ADMIN`, bcrypt hash of `AdminDevPass123!`.
- Teacher user: `user_teacher_demo`, `teacher@demo.edu`, role `TEACHER`, bcrypt hash of `TeacherDevPass123!`.
- Students: `student1`..`student4`, `student{i}@demo.edu`, role `STUDENT`, student_ids `STU_001`..`STU_004`, user_ids `user_student_001`..`user_student_004`.
- Biometric profiles: `person_01`..`person_04`, `embedding` list of 512 floats ($\|v\|_2 = 1.0$), `status: ENROLLED`.
- Camera: `CAM_ROOM_101_DOOR`, `classroom_id: ROOM_101`, `boundary_config: {p1: [0.5, 0.0], p2: [0.5, 1.0], entry_side: "SIDE_A"}`.
- Session: `sess_demo_cs101`, `created_by: user_teacher_demo`, `classroom_id: ROOM_101`, `start_time: today 00:00:00Z`, `end_time: today 23:59:59Z`, `status: ACTIVE`.
- Session roster: `session_id: sess_demo_cs101`, `student_ids: ["STU_001", "STU_002", "STU_003", "STU_004"]`.

### Vision Service ↔ Backend Event Ingestion
- Endpoint: `POST http://localhost:8000/api/v1/events`
- Header: `X-API-Key: test_vision_api_key_for_smoke_test_12345`
- Payload:
  ```json
  {
    "event_id": "evt_...",
    "session_id": "sess_demo_cs101",
    "camera_id": "CAM_ROOM_101_DOOR",
    "identity": "person_01",
    "direction": "ENTRY" | "EXIT",
    "timestamp": "ISO-8601 UTC",
    "confidence": 0.95,
    "quality_score": 0.90,
    "source_type": "WEBRTC_PHONE" | "MANUAL_TRIGGER"
  }
  ```
- Expected Response: `201 Created` or `200 OK`.

### Backend ↔ Frontend Live Snapshot
- Endpoint: `GET http://localhost:8000/api/v1/sessions/sess_demo_cs101/live-snapshot`
- Response Schema:
  ```json
  {
    "session_id": "sess_demo_cs101",
    "classroom_id": "ROOM_101",
    "students": [
      {
        "student_id": "STU_001",
        "name": "Student 1",
        "state": "INSIDE" | "OUTSIDE" | "NOT_SEEN",
        "presence_duration_seconds": 12.5,
        "entry_count": 1,
        "exit_count": 0,
        "last_seen": "ISO-8601"
      }
    ],
    "cameras": [...]
  }
  ```

## Code Layout
- `scripts/seed_clean_demo.py`: Database seeding script.
- `scripts/verify_demo_pipeline.py`: End-to-end verification script.
- `RUNBOOK.md`: Operational demo execution guide.
- `vision-service/pipeline/live_cv_pipeline.py`: Computer vision tracking, boundary crossing, anti-spoof.
- `vision-service/run_webrtc_camera.py`: Vision CLI and runner.
- `vision-service/camera/webrtc_receiver.py`: WebRTC signaling server and mobile HTML UI (`HTML_PHONE_CLIENT`).
- `frontend/src/pages/SessionDetails.tsx`: Teacher session view.
- `frontend/src/components/session/attendance-helpers.ts`: Duration formatting.
- `frontend/src/components/session/AlwaysOnVideoFeed.tsx`: Video stream monitor component.
- `frontend/src/components/session/LiveAttendanceFeed.tsx`: Camera status strip.
- `frontend/src/components/session/SessionAttendance.tsx`: Attendance ledger component.
- `tests/e2e/`: Opaque-box E2E test suite.
