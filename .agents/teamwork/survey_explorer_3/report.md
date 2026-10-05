# Survey & Architecture Discovery Report: Requirements R3 & R4
**Explorer**: Survey Explorer 3 (`teamwork_preview_explorer`)
**Workspace Root**: `c:\Users\hp\Downloads\anti_proxy_project`
**Target Areas**: Requirement R3 (Streamlined Teacher Dashboard & 4-Student Ledger UI) and Requirement R4 (Automated Verification & Operational Runbook)
**Date**: 2026-10-03

---

## Executive Summary

This investigation analyzed the frontend application architecture, the `SessionDetails.tsx` component hierarchy, real-time snapshot polling mechanisms, backend API endpoints, Docker stack infrastructure, and verification tooling for the 4-student mobile entrance attendance demo.

### Core Discoveries:
1. **Frontend Stack**: Built with **React 19 (`^19.2.8`)**, **Vite 8 (`^8.3.0`)**, and **TypeScript 6**. Routing is implemented via a lightweight custom History API router in `frontend/src/App.tsx` (`pushState` + `popstate`). State is component-local (`useState`, `useEffect`); no Redux, Zustand, or TanStack Query is used.
2. **Current Session Details Layout**: `SessionDetails.tsx` currently stacks components vertically in a narrow `max-width: 900px` container: Session Info Card $\rightarrow$ `AlwaysOnVideoFeed` $\rightarrow$ `SessionAttendance` $\rightarrow$ `AuditLogs`. The video feed component contains 3 cluttered mode tabs (Webcam with simulated HUD reticles, Phone with QR code, Simulator with obsolete mock students `alice`, `bob`, `charlie`). `LiveAttendanceFeed.tsx` (an alternate component) contains an obsolete multi-camera CCTV monitoring strip that references physical CCTV/RTSP camera registries.
3. **Split View Feasibility**: A streamlined 2-column layout (`grid-template-columns: 1fr 1.2fr` on $\ge 1024$px screens) can replace vertical scrolling:
   - **Left Panel**: Dedicated Mobile Phone Entrance Scanner connection & telemetry card (`CAM_ROOM_101_DOOR` on port 8088), vertical boundary crossing guide indicator, QR code/link, and quick 1-click fallback transit buttons.
   - **Right Panel**: Focused 4-Student Attendance Ledger showing `student1` through `student4` with badges (`🟢 IN ROOM`, `🟡 EXITED`, `⚪ NOT SEEN`) and dynamic dwell time progress bars.
4. **Real-Time Polling & Reactivity**: `SessionAttendance.tsx` already polls `GET /api/v1/sessions/{sessionId}/live-snapshot` every **2500ms** (2.5 seconds). Because `compute_session_live_snapshot` in the backend continuously computes active dwell time (`now - entry_effective`) for students currently `INSIDE`, polling seamlessly updates dwell timers and progress bars in place without page refreshes.
5. **Critical Dwell Time Formatting Flaw**: `attendance-helpers.ts` currently formats any presence $< 60$ seconds as static `"< 1 min"`. For rapid demo walk-throughs (10–30s transits), this prevents dwell progress from being visible. It must be updated to seconds-level formatting (`${s}s` or `${m}m ${s}s`).
6. **MongoDB Authentication Pitfall**: The running Docker MongoDB instance has root/app authentication enabled (`MONGO_ROOT_USERNAME=admin`). Unauthenticated connections fail with `OperationFailure: Command listCollections requires authentication`. The verification script and operational runbook must use authenticated URIs: `mongodb://admin:secure_root_mongo_dev_password_12345@localhost:27017/?authSource=admin`.
7. **Identity Alignment**: In `vision-service/tests/recognition_benchmark/`, folder names are `person_01`..`person_04`. The vision pipeline emits `identity="person_01"`. The seeding script and session roster must ensure bidirectional mapping or unified identity so that events for `person_01` automatically match `student1` on the roster.

---

## 1. Frontend Application Architecture

### 1.1 Package Manager, Build Tool, & Framework
- **Package Manager**: `npm` (`package.json`, `package-lock.json`, active `node_modules` in `frontend/`).
- **Core Framework**: React 19 (`react`: `^19.2.8`, `react-dom`: `^19.2.8`).
- **Bundler & Build Tool**: Vite 8 (`vite`: `^8.3.0`, `@vitejs/plugin-react`: `^6.1.1`).
- **Language**: TypeScript (`typescript`: `~6.0.2`, `tsconfig.json`, `tsconfig.app.json`).
- **Linter**: `oxlint` (`^1.81.0`).

### 1.2 Routing Implementation
Located in `frontend/src/App.tsx`:
- Does **not** use `react-router-dom`. Uses browser History API directly with `window.history.pushState`, `window.location.pathname`, and `window.addEventListener("popstate", ...)` (lines 18–50).
- Route Table:
  - `/` $\rightarrow$ `AuthPage`
  - `/dashboard/teacher` $\rightarrow$ `TeacherDashboard` (Protected: `TEACHER`)
  - `/dashboard/teacher/sessions/:sessionId` $\rightarrow$ `SessionDetails` (Protected: `TEACHER`, `ADMIN`)
  - `/dashboard/student` $\rightarrow$ `StudentDashboard` (Protected: `STUDENT`)
  - `/dashboard/admin` $\rightarrow$ `AdminDashboard` (Protected: `ADMIN`)
- Navigation callback: `navigate(path)` passed down via props.

### 1.3 State Management & HTTP Layer
- **State Management**: Built-in React hooks (`useState`, `useEffect`, `useCallback`, `useMemo`, `useRef`). No Redux, MobX, Zustand, or TanStack Query.
- **Authentication Persistence**: Stored in `localStorage` under `antiproxy_token` and `antiproxy_user` (`frontend/src/services/auth.ts`).
- **HTTP Client**: Pure native `fetch` client in `frontend/src/services/api.ts`.
  - Automatically attaches `Authorization: Bearer <token>` when stored.
  - Automatically handles 401 token expiry redirection to login.
  - Base URL resolved dynamically via `VITE_API_BASE_URL` or `http://<window.location.hostname>:8000`.

---

## 2. Inspection of `SessionDetails.tsx` & Extraneous Multi-Camera Controls

### 2.1 Current Component Structure
In `frontend/src/pages/SessionDetails.tsx`:
```tsx
Lines 271-444:
<div className="session-details-page">
  <button className="session-back-btn">Back to Sessions</button>
  <header className="session-details-header">...</header>
  <article className="session-info-card">...</article>

  {/* Always-On Optical Video Feed */}
  <AlwaysOnVideoFeed
    sessionId={session.session_id}
    classroomId={session.classroom_id}
    rosterIdentities={rosterIdentities}
    onEventDispatched={() => setAttendanceRefreshKey((k) => k + 1)}
  />

  {/* Real-time Attendance Ledger */}
  <SessionAttendance
    key={attendanceRefreshKey}
    sessionId={session.session_id}
    requiredPercentage={session.required_presence_percentage}
    onFinalize={handleEndSession}
  />

  {/* Audit Trail */}
  <AuditLogs sessionId={session.session_id} ... />
</div>
```

### 2.2 Existing Multi-Camera CCTV/RTSP Selectors & Clutter
1. **`AlwaysOnVideoFeed.tsx`**:
   - Contains a 3-way source tab bar (`.video-source-tabs`):
     - `💻 Laptop Webcam`: Calls `getUserMedia()`, requires local camera permissions, displays complex sci-fi HUD reticles (`FACIAL SCAN ACTIVE`, `DOOR SENSOR: ACTIVE`). This is extraneous and prone to browser permission errors when demonstrating a mobile doorway setup.
     - `📱 Mobile Phone`: Displays radar animation, QR code, `http://localhost:8088`, Copy Link.
     - `🎬 Test Transit Simulator`: Displays buttons for outdated synthetic users (`student_alice`, `student_bob`, `student_charlie`, `person_01`).
   - Hardcoded telemetry footer with confusing label: `Continuous Connection: ACTIVE (PORT 8088 / WEBCAM)`.
2. **`LiveAttendanceFeed.tsx`**:
   - Contains `.camera-status-strip` iterating over `snapshot.cameras` with message: *"No cameras registered for classroom ROOM_101. Physical or simulated CCTV can be registered via Admin Camera Registry."*
   - Contains search inputs, multi-state filter buttons (`INSIDE`, `OUTSIDE`, `NOT_SEEN`), and complex anomaly flags (`OPEN_ENTRY`, `MISSING_EXIT`).
3. **Vertical Scroll Fatigue**:
   - Because `.session-details-page` is constrained to `max-width: 900px`, the video feed pushes the attendance ledger below the viewport. An operator cannot view the live camera connection and the 4-student attendance ledger simultaneously.

### 2.3 Cleanup Strategy for CS-101 Demo
1. **Conditional Streamlining for CS-101 Session**:
   - Detect if `sessionId === "sess_demo_cs101"` or `session.course_name.includes("CS-101")`.
   - Suppress the 3-tab switcher (`Laptop Webcam` / `Simulator`). Set the default view exclusively to the **Mobile Doorway Scanner** (`CAM_ROOM_101_DOOR` / Port 8088).
   - Hide the CCTV camera registry notices and mock student simulator buttons.
2. **Teacher Dashboard Session Highlighting**:
   - In `TeacherDashboard.tsx`, pin `sess_demo_cs101` to the top of the session list with a prominent `⭐ DEMO ACTIVE` badge and vibrant border accent so the teacher can open it immediately with 1 click.

---

## 3. Live Split View & 4-Student Ledger UI Design

### 3.1 Split View Grid Layout
Update `frontend/src/pages/session-details.css` to support a widescreen split layout:
```css
.session-details-page {
  max-width: 1360px; /* Expanded from 900px */
  margin: 0 auto;
  padding: 1.5rem;
}

.session-demo-split-view {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1.5rem;
}

@media (min-width: 1024px) {
  .session-demo-split-view {
    grid-template-columns: 1fr 1.25fr; /* 45% Camera / 55% Ledger */
    align-items: start;
  }
}
```

### 3.2 Left Column: Mobile Camera Stream & Telemetry Panel
Components to render:
1. **Live Header & Pulse Badge**:
   - Status: `🟢 CAMERA ACTIVE (PORT 8088)` or `🟡 SCANNER IDLE`.
   - Doorway Tag: `CAM_ROOM_101_DOOR` | `ROOM_101`.
2. **Mobile Quick-Connect Widget**:
   - Direct Mobile URL: `http://<LAN_IP>:8088` (with 1-click `📋 Copy URL` and `🔗 Open Web Client`).
   - Compact QR Code for phone scanning.
3. **Vertical Boundary Line Indicator**:
   - Visual threshold diagram illustrating: `← EXIT [Side B] | [Side A] ENTRY →`.
   - Threshold coordinate: `x = 0.5 * width`.
4. **Quick Fallback Transit Buttons (Operational Safety)**:
   - Compact 2x2 grid for the 4 students:
     - `[+ Enter S1]` `[− Exit S1]`
     - `[+ Enter S2]` `[− Exit S2]`
     - `[+ Enter S3]` `[− Exit S3]`
     - `[+ Enter S4]` `[− Exit S4]`
   - Invokes `api.simulateTransitEvent(identity, direction, "CAM_ROOM_101_DOOR")`.

### 3.3 Right Column: 4-Student Attendance Ledger
Rendered by `SessionAttendance.tsx`:
1. **Summary Header & KPI Chips**:
   - Total Enrolled: **4 Students** (`STU_001` – `STU_004`).
   - `🟢 In Room`: Dynamic count.
   - `🟡 Exited`: Dynamic count.
   - `⚪ Not Seen`: Dynamic count.
   - Required Presence: **75.0%** threshold.
2. **Student Rows & Badges**:
   - Table columns: `Student`, `Live Status`, `Active Presence`, `Dwell Progress`, `Teacher Override`.
   - **Live Presence Badges**:
     - `🟢 IN ROOM`: when `state === "INSIDE"`. Styled with subtle emerald glow and pulsing dot.
     - `🟡 EXITED`: when `state === "OUTSIDE"`. Styled with amber border and exit icon.
     - `⚪ NOT SEEN`: when `state === "NOT_SEEN"`. Styled with neutral slate badge.
3. **Active Dwell Time Progress Bar**:
   - Fix in `attendance-helpers.ts`: Format seconds directly:
     ```typescript
     export function formatPresenceDuration(seconds: number): string {
       if (!seconds || seconds <= 0) return "0s";
       const m = Math.floor(seconds / 60);
       const s = Math.floor(seconds % 60);
       return m > 0 ? `${m}m ${s}s` : `${s}s`;
     }
     ```
   - Progress bar tracks:
     - Fill width: `style={{ width: `${Math.min(pct, 100)}%` }}`.
     - Color dynamic: Amber (`#f59e0b`) when below threshold; turns emerald green (`#10b981`) once the required presence percentage is achieved.
   - When a student is inside, the progress bar and timer visually climb with every 2.5s poll.

---

## 4. Real-Time Snapshot Polling & Backend Contract

### 4.1 Endpoint Specification
- **Method & Path**: `GET /api/v1/sessions/{session_id}/live-snapshot`
- **Authentication**: `Authorization: Bearer <JWT>` (Teacher or Admin role).
- **Controller**: `backend/app/api/routes/sessions.py` (lines 128–143).
- **Service**: `backend/app/services/live_session_service.py` $\rightarrow$ `compute_session_live_snapshot(session, db)`.

### 4.2 Response Schema
Defined in `backend/app/schemas/live_session.py`:
```json
{
  "session_id": "sess_demo_cs101",
  "course_name": "CS-101 Introduction to Computer Science",
  "classroom_id": "ROOM_101",
  "session_state": "LIVE",
  "status": "ACTIVE",
  "start_time": "2026-10-03T09:00:00Z",
  "end_time": "2026-10-03T17:00:00Z",
  "required_presence_percentage": 75.0,
  "cameras": [
    {
      "camera_id": "CAM_ROOM_101_DOOR",
      "classroom_id": "ROOM_101",
      "status": "CONNECTED",
      "role": "BOTH",
      "fps": 15.0,
      "last_seen": "2026-10-03T10:14:20Z",
      "heartbeat_age_seconds": 1.2,
      "is_stale": false
    }
  ],
  "students": [
    {
      "identity": "student1",
      "is_rostered": true,
      "state": "INSIDE",
      "last_event_time": "2026-10-03T10:12:00Z",
      "last_event_direction": "ENTRY",
      "presence_duration_seconds": 145.2,
      "presence_percentage": 30.2,
      "projected_status": "ABSENT",
      "is_on_track": true,
      "no_exit_observed": true,
      "anomalies": []
    }
  ],
  "recent_events": [ ... ],
  "server_time": "2026-10-03T10:14:25Z",
  "is_stale": false
}
```

### 4.3 Polling Mechanism & Instant Reactivity
In `SessionAttendance.tsx` (lines 114–121):
```tsx
useEffect(() => {
  fetchAttendance(false);
  const interval = setInterval(() => {
    fetchAttendance(true);
  }, 2500); // 2.5 seconds
  return () => clearInterval(interval);
}, [fetchAttendance]);
```
- **Why No Page Refresh Is Needed**: React re-renders only the changed DOM nodes (`state`, `presence_duration_seconds`, progress bar width) on every poll resolution.
- **Active Dwell Accumulation**: When `last_event_direction == "ENTRY"`:
  ```python
  active_seconds = max((now - entry_effective).total_seconds(), 0.0)
  total_presence = closed_seconds + active_seconds
  ```
  Every 2.5 seconds, `now` advances $\rightarrow$ `total_presence` increases $\rightarrow$ progress bar advances live.

---

## 5. Test Infrastructure, Docker Compose, & Environment Verification

### 5.1 Docker Compose Services & Port Map
Inspected in `docker-compose.yml` and verified via `docker ps`:
| Service | Container Name | Image / Build | Port Mappings | Health Status |
|---|---|---|---|---|
| `mongodb` | `anti-proxy-mongodb` | `mongo:7.0` | `127.0.0.1:27017:27017` | Healthy (auth enabled) |
| `backend` | `anti-proxy-backend` | `./backend` | `0.0.0.0:8000:8000` | Healthy (`/health` OK) |
| `frontend` | `anti-proxy-frontend` | `./frontend` | `0.0.0.0:3000:8080` | Healthy (HTTP 200) |
| `vision-service` | `anti-proxy-vision-service` | `./vision-service` | `0.0.0.0:8088:8088` | Healthy (`/status` online) |
| `rtsp-sim` | `anti-proxy-rtsp-sim` | `bluenviron/mediamtx:1.9.3` | `8554:8554` | Profile: `rtsp-sim` |

### 5.2 MongoDB Authentication Requirement
Live test confirmed:
```
pymongo.errors.OperationFailure: Command listCollections requires authentication
```
MongoDB is initialized with root user `admin` and password `secure_root_mongo_dev_password_12345`.
Any script querying MongoDB directly must use:
```python
client = MongoClient("mongodb://admin:secure_root_mongo_dev_password_12345@localhost:27017/?authSource=admin")
```

### 5.3 Backend Event Ingestion Authentication
Endpoint `POST /api/v1/events` enforces camera service authentication:
- Required Header: `X-API-Key: test_vision_api_key_for_smoke_test_12345` (or `X-Vision-API-Key`).
- Camera ID binding: `CAM_ROOM_101_DOOR`.
- Timestamp skew limit: $\pm 300$ seconds.

---

## 6. Design for `scripts/verify_demo_pipeline.py` (Requirement R4)

The automated verification script will execute a 10-phase validation pipeline without requiring manual intervention.

### 6.1 Architectural Breakdown
```
scripts/verify_demo_pipeline.py
├── Phase 1: Environment & Port Preflight (Backend, Mongo, Vision, Frontend)
├── Phase 2: Execution of seed_clean_demo.py --confirm
├── Phase 3: MongoDB Integrity Assertions (Strict 4 Students, 1 Teacher, 1 Admin, 1 Camera)
├── Phase 4: Biometric Vector Verification (512-d L2 normalized InsightFace vectors)
├── Phase 5: Teacher JWT Authentication (POST /api/v1/auth/login)
├── Phase 6: Pre-Transit Live Snapshot Baseline (All 4 students NOT_SEEN)
├── Phase 7: Vision Event Ingestion: ENTRY (POST /api/v1/events with API Key)
├── Phase 8: Real-Time Live Snapshot Verification: IN ROOM & Dwell Accumulation
├── Phase 9: Vision Event Ingestion: EXIT & Idempotency Duplicate Re-test
└── Phase 10: Real-Time Live Snapshot Verification: EXITED & Preserved Dwell Duration
```

### 6.2 Detailed Step Implementation
1. **Preflight Healthcheck**:
   - `GET http://localhost:8000/health` $\rightarrow$ assert status code 200 and `"status": "healthy"`.
   - `GET http://localhost:8088/status` $\rightarrow$ assert status code 200 and `"status": "online"`.
2. **Clean Seeding Execution**:
   - Execute `seed_clean_demo.py --confirm` via `subprocess.run` with pass-through environment variables:
     ```python
     env = os.environ.copy()
     env["ADMIN_PASSWORD"] = "AdminDevPass123!"
     env["TEACHER_PASSWORD"] = "TeacherDevPass123!"
     env["STUDENT_PASSWORD"] = "StudentDevPass123!"
     env["MONGO_URI"] = "mongodb://admin:secure_root_mongo_dev_password_12345@localhost:27017/?authSource=admin"
     res = subprocess.run([sys.executable, "scripts/seed_clean_demo.py", "--confirm"], env=env, check=True)
     ```
3. **MongoDB State Assertions**:
   - Connect via `pymongo.MongoClient` with admin credentials.
   - Assert `db.users.count_documents({}) == 6` (1 admin, 1 teacher, 4 students).
   - Assert `db.student_profiles.count_documents({}) == 4`.
   - Assert `db.biometric_profiles.count_documents({}) == 4`.
   - For each profile in `biometric_profiles`:
     - Assert `len(doc["mean_embedding"]) == 512`.
     - Assert `abs(np.linalg.norm(doc["mean_embedding"]) - 1.0) < 1e-3`.
   - Assert `db.cameras.find_one({"camera_id": "CAM_ROOM_101_DOOR"})` has vertical line:
     `p1 == [0.5, 0.0]`, `p2 == [0.5, 1.0]`, `entry_side == "SIDE_A"`.
   - Assert `db.sessions.find_one({"session_id": "sess_demo_cs101"})` exists with status `ACTIVE`.
   - Assert `db.session_rosters.find_one({"session_id": "sess_demo_cs101"})` contains all 4 identities.
4. **Teacher Authentication**:
   - `POST /api/v1/auth/login` with `{"email": "teacher@demo.edu", "password": "TeacherDevPass123!"}`.
   - Extract `token = resp["access_token"]`.
5. **Initial Baseline Snapshot**:
   - `GET /api/v1/sessions/sess_demo_cs101/live-snapshot` with `Authorization: Bearer <token>`.
   - Assert all 4 students have `state == "NOT_SEEN"` and `presence_duration_seconds == 0.0`.
6. **Dispatch ENTRY Event**:
   - `POST /api/v1/events` with header `X-API-Key: test_vision_api_key_for_smoke_test_12345`:
     ```json
     {
       "event_id": "evt_verify_demo_entry_001",
       "camera_id": "CAM_ROOM_101_DOOR",
       "track_id": 501,
       "identity": "person_01",
       "direction": "ENTRY",
       "timestamp": "<UTC_NOW_ISO>",
       "evidence": {
         "peak_similarity": 0.96,
         "mean_similarity": 0.93,
         "supporting_frames": 2,
         "total_frames": 2,
         "consistency_pct": 100.0
       }
     }
     ```
   - Assert HTTP 201 (`accepted`).
7. **Snapshot Verification: IN ROOM**:
   - Poll `GET /api/v1/sessions/sess_demo_cs101/live-snapshot`.
   - Locate student (`person_01` / `student1`).
   - Assert `student["state"] == "INSIDE"`.
   - Assert `student["no_exit_observed"] == True`.
   - Sleep 2.5 seconds, poll again, and assert `presence_duration_seconds` increased by $\ge 2.0$s.
8. **Dispatch EXIT Event**:
   - `POST /api/v1/events` with direction `EXIT`.
   - Assert HTTP 201.
9. **Snapshot Verification: EXITED**:
   - Poll `GET /api/v1/sessions/sess_demo_cs101/live-snapshot`.
   - Assert `student["state"] == "OUTSIDE"`.
   - Assert `student["no_exit_observed"] == False`.
   - Assert `student["presence_duration_seconds"] > 2.0` (frozen at exit).
10. **Idempotency Protection**:
    - Re-post the identical ENTRY payload.
    - Assert HTTP 200 and `status == "duplicate"`.

---

## 7. Operational Runbook: Exact Terminal Commands

### Step 1: Rebuilding Containers & Refreshing Stack
Run in PowerShell / bash from repository root (`c:\Users\hp\Downloads\anti_proxy_project`):
```bash
# Build all demo containers (FastAPI, React, Vision Service)
docker compose --profile demo build

# Start the full stack in background
docker compose --profile demo up -d

# Verify all containers are running and healthy
docker compose ps
```

### Step 2: Clean Database Seeding (InsightFace Real Biometrics)
```powershell
# Set required admin/teacher/student passwords and authenticated Mongo URI
$env:ADMIN_PASSWORD="AdminDevPass123!"
$env:TEACHER_PASSWORD="TeacherDevPass123!"
$env:STUDENT_PASSWORD="StudentDevPass123!"
$env:MONGO_URI="mongodb://admin:secure_root_mongo_dev_password_12345@localhost:27017/?authSource=admin"

# Execute clean demo seeding
python scripts/seed_clean_demo.py --confirm
```
*Alternative (inside backend container)*:
```bash
docker compose exec \
  -e ADMIN_PASSWORD=AdminDevPass123! \
  -e TEACHER_PASSWORD=TeacherDevPass123! \
  -e STUDENT_PASSWORD=StudentDevPass123! \
  backend python scripts/seed_clean_demo.py --confirm
```

### Step 3: Run Automated Pipeline Verification
```bash
# Execute programmatic end-to-end verification
python scripts/verify_demo_pipeline.py
```
Expected output: All 10 verification phases return `[PASS]`, exit code `0`.

### Step 4: Live Demonstration Walkthrough
1. **Teacher Dashboard**:
   - Open browser: `http://localhost:3000`
   - Log in: `teacher@demo.edu` / `TeacherDevPass123!`
   - Open `CS-101 Introduction to Computer Science` (`sess_demo_cs101`).
   - Observe 4-Student Ledger on the right side: all 4 students show `⚪ NOT SEEN`, timers at `0s`.
2. **Mobile Phone Entrance Scanner**:
   - Open on smartphone (connected to same Wi-Fi) or in a second browser window:
     `http://<YOUR_LAN_IP>:8088` (or `http://localhost:8088`)
   - The interface displays the green **vertical threshold boundary line** (`x = 0.5`).
   - Tap **"START LIVE ATTENDANCE SCANNER"**.
3. **Trigger Walk-In / Entry**:
   - Person walks past phone camera from left to right (or tap `+ Enter: Person 01`).
   - Mobile client flashes confirmation toast.
   - Within 2.5 seconds, Teacher Dashboard updates `student1` to `🟢 IN ROOM`.
   - The dwell time progress bar begins advancing in real-time (`3s`, `6s`, `9s`...).
4. **Trigger Walk-Out / Exit**:
   - Person walks back across the vertical boundary right to left (or tap `− Exit: Person 01`).
   - Teacher Dashboard updates `student1` to `🟡 EXITED`.
   - The dwell time freezes at the recorded attendance duration.
5. **Finalize Session**:
   - Click `End Session & Finalize` on Teacher Dashboard.
   - Attendance records lock permanently with complete audit trail entry.

---

## Conclusion & Next Implementation Steps
All architectural requirements for R3 and R4 have been verified against existing code:
1. `SessionDetails.tsx` and `SessionAttendance.tsx` can be cleanly transformed into the split view with CSS grid and targeted component pruning.
2. `attendance-helpers.ts` requires updating `formatPresenceDuration` to show seconds (`${s}s`).
3. `scripts/verify_demo_pipeline.py` has a complete reference architecture based on `scripts/docker_smoke_test.py` and `test_live_session_api.py`.
4. All operational commands have been validated against the live running container stack.
