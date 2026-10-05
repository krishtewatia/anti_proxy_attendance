# BRIEFING — 2026-10-03T10:15:00Z

## Mission
Investigate Requirement R1 (Clean Demo Database Seeding & Biometrics) and related database/auth architecture across services to design specs for scripts/seed_clean_demo.py.

## 🔒 My Identity
- Archetype: teamwork_preview_explorer
- Roles: explorer, synthesizer
- Working directory: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_1
- Original parent: 992bab0c-c8bc-4ae6-9c50-07f56d0d064a
- Milestone: survey_phase

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Output comprehensive findings in c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_1\report.md
- Output handoff report in c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_1\handoff.md
- Message parent orchestrator when complete

## Current Parent
- Conversation ID: 992bab0c-c8bc-4ae6-9c50-07f56d0d064a
- Updated: 2026-10-03T10:15:00Z

## Investigation State
- **Explored paths**:
  - `docker-compose.yml`, `docker/init-mongo.js`, `.env`
  - `backend/app/core/config.py`, `backend/app/database/mongodb.py`
  - `backend/app/database/` (`users.py`, `student_profiles.py`, `biometric_profiles.py`, `session_rosters.py`, `sessions.py`, `cameras.py`, `events.py`)
  - `backend/app/schemas/` (`auth.py`, `student.py`, `biometric.py`, `session.py`, `session_roster.py`, `camera.py`, `live_session.py`, `vision_event.py`)
  - `backend/app/security/passwords.py`, `backend/app/api/dependencies/auth.py`, `backend/app/api/dependencies/camera_auth.py`
  - `backend/app/api/routes/` (`auth.py`, `students.py`, `sessions.py`, `enrollment.py`, `events.py`)
  - `backend/app/services/` (`auth_service.py`, `live_session_service.py`, `session_resolution_service.py`)
  - `vision-service/tests/recognition_benchmark/person_0{1..4}/`
  - `vision-service/pipeline/live_cv_pipeline.py`, `vision-service/run_webrtc_camera.py`, `vision-service/enroll_cli.py`, `vision-service/enrollment/engine.py`
  - `scripts/seed_demo.py`, `scripts/docker_smoke_test.py`
- **Key findings**:
  - Live MongoDB is running on `127.0.0.1:27017` with user `antiproxy_user` and password `secure_app_mongo_dev_password_12345`.
  - Current DB is contaminated with 161 users, 76 sessions, 38 rosters, 22 student profiles, and mock math embeddings.
  - Password auth uses bcrypt. Live tested `admin@system.local` / `AdminDevPass123!` and `teacher@demo.edu` / `TeacherDevPass123!` with HTTP 200 return.
  - Recognition benchmark contains 14 high-res JPEGs for person_01 (3), person_02 (5), person_03 (3), person_04 (3).
  - Executed InsightFace `buffalo_l` and extracted authentic 512-d unit vectors ($\|v\| = 1.0$), captured in `benchmark_embeddings.json`.
  - Camera requires vertical boundary line `p1: [0.5, 0.0]`, `p2: [0.5, 1.0]`, `entry_side: "SIDE_A"` for left-to-right ENTRY.
  - Session ownership constraint: `sessions.created_by` MUST equal the teacher's `user_id` to prevent 403 Forbidden on Teacher Dashboard and live-snapshot endpoints.
- **Unexplored areas**: None for R1 scope.

## Key Decisions Made
- Formulated comprehensive multi-tier strategy for `scripts/seed_clean_demo.py` (local InsightFace -> docker exec -> verified static embeddings).
- Authored detailed investigation report in `report.md`.

## Artifact Index
- DISPATCH.md — Log of dispatch messages
- BRIEFING.md — Persistent memory
- progress.md — Liveness heartbeat
- benchmark_embeddings.json — Genuine 512-d embeddings extracted from benchmark images
- report.md — Comprehensive findings and specifications for R1
- handoff.md — Standard handoff report
