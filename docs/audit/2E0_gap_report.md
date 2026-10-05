# Step 2E.0: Repo-Truth Audit and Gap Report

**Audit Date:** October 2, 2026
**Auditor:** Antigravity Agentic Pair Programmer
**Repository Root:** `C:\Users\hp\Downloads\anti_proxy_project`
**Target Scope:** Verification of Step 2D.5 completion, reconciliation of Notion documentation vs. code reality, deep-dive defect inspection, security scan, and Phase 2E roadmap recalibration.

---

## 1. Executive Summary & Explicit Verdict

| Dimension | Claimed State (Notion / Prior Notes) | Verified Repo Reality | Status |
| :--- | :--- | :--- | :--- |
| **Backend Test Count** | 47 tests (Notion) / 257 tests (Owner) | **257 passed** (0 failed, 2 warnings) across 46 files | **Verified** (Discrepancy Explained) |
| **Vision Test Count** | 21 tests (Notion) | **50 passed** (0 failed, 5 warnings) across 6 files | **Verified** (Discrepancy Explained) |
| **Frontend Test Count** | Untested / Live Auth Client | **0 unit tests**; 11 live Node integration scripts; `npm run build` passes | **Verified** |
| **Real-Face E2E Verdict** | "100% complete and verified live loop" | **SYNTHETIC ONLY** (Real-face E2E is NOT proven) | **CRITICAL GAP** |
| **Attendance Status Enum** | `PRESENT`, `INSUFFICIENT`, `ABSENT`, `REVIEW` | `PRESENT`, `ABSENT` only | **CONTRADICTION** |
| **Event Dispatcher** | "Async Queue + Exponential Backoff" | Synchronous `requests.Session()`, 0 retries, no queue | **CONTRADICTION** |
| **Camera Authenticity** | "Checks camera authenticity" | Unauthenticated open endpoint; accepts any `camera_id` | **SECURITY GAP** |
| **Dashboard Presence Feed** | "Real-time presence feed" | Static REST fetch on mount + manual refresh button | **CONTRADICTION** |

### Explicit Verdict on End-to-End Perception Proof
> [!CAUTION]
> **VERDICT: SYNTHETIC / MOCKED ONLY.**
> Automated end-to-end verification of real human facial recognition through the complete pipeline into MongoDB attendance records **has not been proven**.
>
> In the primary E2E integration test ([`test_webrtc_cv_fastapi_e2e.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_webrtc_cv_fastapi_e2e.py#L182-L201)):
> 1. `mock_app = MagicMock(spec=FaceAnalysis)`: Both SCRFD detection and ArcFace recognition are completely mocked via `unittest.mock.MagicMock`.
> 2. `test_img = np.zeros((720, 640, 3), dtype=np.uint8)`: Incoming video frames are synthetic black matrices with zero texture.
> 3. Bounding boxes (`box1`, `box2`, `box3`, `box4`) are hardcoded coordinate arrays fed directly to the tracker.
> 4. Biometric embeddings are random numbers (`np.random.randn(512)`).
>
> While isolated benchmark scripts exist ([`multi_person_benchmark.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/multi_person_benchmark.py) and [`test_webrtc_cv_benchmark.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_webrtc_cv_benchmark.py)), they run offline or composite face crops onto canvas. A true live camera or video stream with real human faces driving the end-to-end loop into FastAPI and MongoDB attendance has never been run in automated tests.

---

## 2. Test Suite Audit & Discrepancy Resolution

### Exact Test Execution Counts

```powershell
# 1. Backend Pytest Execution
& backend\.venv\Scripts\python.exe -m pytest backend/tests -v
# Output: 257 passed, 2 warnings in 106.46s

# 2. Vision Pytest Execution (via Vision Virtual Environment with sys.path)
& vision-service\.venv\Scripts\python.exe -c "import sys; sys.path.append(r'C:\Users\hp\AppData\Local\Programs\Python\Python314\Lib\site-packages'); import pytest; sys.exit(pytest.main(['vision-service/tests', '-v']))"
# Output: 50 passed, 5 warnings in 525.88s

# 3. Frontend Production Build & Lint
npm run build --prefix frontend
# Output: ✓ 50 modules transformed, built in 401ms (0 errors)
npm run lint --prefix frontend
# Output: 0 errors, 17 warnings
```

### Explaining the Discrepancies

#### A. Backend: 47 Tests vs. 257 Tests
Notion claimed: *"Step 2D.5 is complete (47 backend + 21 vision tests)"*.
The project owner reported: *257 backend tests*.

**Resolution:** Both numbers represent real test counts, but at different granularities:
- The **47 tests** in Notion represent **strictly the Perception Ingestion, Session Resolution, and Presence Engine subsystem** created during the 2D.5 milestone across 6 files:
  1. [`backend/tests/test_events.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_events.py): 9 tests
  2. [`backend/tests/test_event_repository.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_event_repository.py): 1 test
  3. [`backend/tests/test_vision_event_schema.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_vision_event_schema.py): 4 tests
  4. [`backend/tests/test_session_resolution.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_session_resolution.py): 10 tests
  5. [`backend/tests/test_session_scoped_events.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_session_scoped_events.py): 8 tests
  6. [`backend/tests/test_presence_engine.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_presence_engine.py): 15 tests
  **Subsystem Sum: 9 + 1 + 4 + 10 + 8 + 15 = EXACTLY 47 tests.**
- The **257 tests** represent the **full backend test suite** spanning 46 test files, including:
  - Auth, Passwords, JWT, and RBAC: 46 tests
  - Sessions, Rosters, and Ownership: 42 tests
  - Student Profile Binding: 13 tests
  - Attendance Finalization & Retrieval: 17 tests
  - Attendance Correction Service & API: 37 tests
  - Audit Trail Service, Schemas, & API: 47 tests
  - Real CV Flow & Integration: 8 tests
  - Health & Schemas: 47 tests (above)

#### B. Vision: 21 Tests vs. 50 Tests
Notion claimed: *"21 vision tests"*.

**Resolution:**
- The **21 tests** in Notion refer strictly to the **Step 2D.5 Boundary, Dispatcher, and E2E loop suite**:
  1. [`vision-service/tests/test_cv_event_pipeline.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_cv_event_pipeline.py): 6 tests
  2. [`vision-service/tests/test_event_dispatcher.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_event_dispatcher.py): 14 tests
  3. [`vision-service/tests/test_webrtc_cv_fastapi_e2e.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_webrtc_cv_fastapi_e2e.py): 1 test
  **Subsystem Sum: 6 + 14 + 1 = EXACTLY 21 tests.**
- The **50 tests** represent the **complete pytest test suite** in `vision-service/tests`, which also includes:
  - Video Source Polymorphism & Buffering (`test_video_source.py`): 18 tests
  - WebRTC Ingestion & Reconnect (`test_webrtc_ingest.py`): 5 tests
  - Multi-Person Optimization Benchmarks (`test_webrtc_cv_benchmark.py`): 5 tests (each runs multiple real CPU trials)
- **Environment Anomaly:** `pytest` is NOT installed in `vision-service/.venv` (`pip list` shows `insightface`, `onnxruntime`, `aiortc`, `opencv-python`, but no `pytest`). It relies on the global or backend pytest runner with module path inclusion.
- **Script Anomaly:** 4 test files (`test_face_inference.py`, `test_insightface.py`, `test_similarity.py`, `test_entry_exit_tracking.py`) contain `def main()` scripts instead of pytest test functions, and are not collected by pytest.

#### C. Frontend Testing Reality
- **Unit / Component Tests:** None exist. No Vitest, Jest, or React Testing Library installed in [`frontend/package.json`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/package.json).
- **Integration Test Scripts:** 11 Node TypeScript scripts exist under `frontend/scripts/test_*.ts`. They run using `node --experimental-strip-types` and execute live HTTP requests against `http://localhost:8000`.

---

## 3. Step 2D.5 Hop-by-Hop Trace

Tracing the data path from video frame ingestion to frontend UI display:

```
[1. Frame] -> [2. Detect] -> [3. Track] -> [4. Recognize] -> [5. 3 Votes]
    -> [6. Boundary] -> [7. Safety Gate] -> [8. Dispatcher] -> [9. /events]
    -> [10. Enrichment] -> [11. Mongo] -> [12. Presence Engine] -> [13. Finalization]
    -> [14. API] -> [15. UI]
```

| Hop | Component & File | Real Implementation | Status in Code | Status in 2D.5 E2E Test |
| :--- | :--- | :--- | :--- | :--- |
| **1. Frame** | [`camera/phone_source.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/camera/phone_source.py) | `PhoneVideoSource` receives WebRTC frames via bounded queue buffer (max 30 frames, drop oldest). | **Wired** | **Synthetic** (`np.zeros((720, 640, 3))`) |
| **2. Detect** | [`pipeline/live_cv_pipeline.py#L485`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L485) | `SCRFD-0.5G` ONNX inference at 640x360 resolution (`intra=4`, `inter=2`). | **Wired** | **Mocked** (`det_mock.detect.return_value = (box, None)`) |
| **3. Track** | [`tracking/bytetrack.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tracking/bytetrack.py) | `BYTETracker` Kalman filtering + Hungarian matching on detection bounding boxes. | **Wired** | **Wired** (runs real ByteTrack on synthetic boxes) |
| **4. Recognize** | [`pipeline/live_cv_pipeline.py#L566`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L566) | ArcFace 512-d embedding extraction + gallery cosine similarity matching. | **Wired** | **Mocked** (`rec_mock.get` sets random vector) |
| **5. 3 Votes** | [`pipeline/live_cv_pipeline.py#L243`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L243) | `TrackEvidence.add_observation` evaluates plurality winner until `vote_count >= min_supporting_frames` (bypasses ArcFace once confirmed). | **Wired** | **Wired** (configured to 2 votes in test) |
| **6. Boundary** | [`pipeline/live_cv_pipeline.py#L22`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L22) | `classify_point_side` checks centroid `(cx, cy)` relative to directed 2D line segment with ±4.0px deadband. | **Wired** | **Wired** |
| **7. Safety Gate** | [`pipeline/live_cv_pipeline.py#L324`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L324) | `get_emittable_directions`: Blocks `is_confirmed == False` and `assigned_identity == "UNKNOWN"`. | **Wired** | **Wired** |
| **8. Dispatcher** | [`events/event_dispatcher.py#L140`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/events/event_dispatcher.py#L140) | `EventDispatcher.send_event`: Validates payload, deduplicates locally, executes synchronous `requests.Session().post()`. | **Wired** | **Wired** (HTTP POST to test backend on port 8123) |
| **9. /events** | [`backend/app/api/routes/events.py#L26`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/routes/events.py#L26) | `ingest_vision_event`: Validates `VisionEventCreate`, checks DB idempotency on `event_id`. | **Wired** | **Wired** |
| **10. Enrichment** | [`backend/app/services/session_resolution_service.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/session_resolution_service.py) | Resolves `classroom_id = resolve_classroom_for_camera(camera_id)` and attaches active `session_id`. | **Wired** | **Wired** (mapped `CAM_ROOM_101_DOOR` to `ROOM_101`) |
| **11. Mongo** | [`backend/app/database/mongodb.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/database/mongodb.py) | Motor async insert into `attendance_events` collection with `unique_event_id_idx`. | **Wired** | **Wired** (via in-memory `AsyncMongoMockClient`) |
| **12. Presence Engine** | [`backend/app/services/presence_engine.py#L25`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/presence_engine.py#L25) | Sorts events, pairs chronological ENTRY/EXIT intervals, sums net duration, clamps to session window. | **Wired** | **Wired** |
| **13. Finalization** | [`backend/app/services/session_finalization.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/session_finalization.py) | `POST /api/v1/sessions/{id}/finalize`: Runs presence engine for roster students, evaluates threshold, upserts `AttendanceRecord`. | **Wired** | **Wired** |
| **14. API** | [`backend/app/api/routes/attendance.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/routes/attendance.py) | `GET /api/v1/attendance/{id}` returns attendance records with statuses and intervals. | **Wired** | **Wired** |
| **15. UI** | [`frontend/src/pages/SessionDetails.tsx`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/src/pages/SessionDetails.tsx) | `SessionAttendance.tsx` displays records and manual correction modal. | **Wired** | **Disconnected from E2E test** (No frontend test in 2D.5) |

---

## 4. Architectural Contradictions Resolved

### 1. Attendance Status Enum: `PRESENT/ABSENT` vs. `PRESENT/INSUFFICIENT/ABSENT/REVIEW`
- **Notion Claim:** The system classifies students into 4 states: `PRESENT`, `INSUFFICIENT`, `ABSENT`, `REVIEW`.
- **Repo Reality:** The codebase **strictly defines only 2 statuses**: `PRESENT` and `ABSENT`.
  - Backend schema ([`backend/app/schemas/attendance.py#L27`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/schemas/attendance.py#L27)): `status: Literal["PRESENT", "ABSENT"]`
  - Presence engine ([`backend/app/services/presence_engine.py#L139`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/presence_engine.py#L139)): `AttendanceStatus = Literal["PRESENT", "ABSENT"]`
  - Attendance correction ([`backend/app/schemas/attendance_correction.py#L7`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/schemas/attendance_correction.py#L7)): `AttendanceStatus = Literal["PRESENT", "ABSENT"]`
  - Frontend TypeScript types ([`frontend/src/types/attendance.ts#L1`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/src/types/attendance.ts#L1)): `export type AttendanceStatus = 'PRESENT' | 'ABSENT';`
- **Origin of Contradiction:** `INSUFFICIENT` and `REVIEW` appear only in [`docs/adr/ADR-003-attendance-calculation.md`](file:///c:/Users/hp/Downloads/anti_proxy_project/docs/adr/ADR-003-attendance-calculation.md#L27). When the presence engine was implemented, anyone below the required percentage threshold was coded as `ABSENT`, and ADR-003 / Notion were never updated to reflect this simplification.

### 2. Event Dispatcher: Synchronous `requests.Session` vs. "Async Queue + Backoff"
- **Notion Claim:** *"EventDispatcher (Async Queue + Backoff)"* with queue bounds and non-blocking asynchronous worker.
- **Repo Reality:** [`vision-service/events/event_dispatcher.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/events/event_dispatcher.py#L77-L195) is **100% synchronous and blocking**:
  ```python
  self.session = session or requests.Session()
  ...
  response = self.session.post(url, json=payload, timeout=self.timeout)
  ```
  - **No Queue:** Events are dispatched directly in-line inside the video frame processing loop ([`live_cv_pipeline.py#L663`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L663)).
  - **No Retry / Backoff:** If the HTTP request fails or times out, it either immediately raises `EventDispatchError` or returns an error dictionary (`status: "error"`).
  - **No Queue Bounds:** Since there is no queue, there are no queue bounds or saturation drops.
  - **Performance Hazard:** If backend latency spikes to 200 ms, video frame processing blocks for 200 ms, causing buffer saturation and frame drops in `PhoneVideoSource`.

### 3. Camera Authenticity on `/api/v1/events`
- **Notion Claim:** *"checks camera authenticity"*.
- **Repo Reality:** Endpoint [`backend/app/api/routes/events.py#L26`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/routes/events.py#L26) has **zero authentication dependencies**:
  ```python
  @router.post("", response_model=VisionEventResponse, status_code=status.HTTP_201_CREATED)
  async def ingest_vision_event(
      event: VisionEventCreate,
      response: Response,
      db: AsyncIOMotorDatabase = Depends(get_database),
  ):
  ```
  - Any client that can reach port 8000 can send arbitrary JSON payloads.
  - Camera lookup ([`backend/app/services/session_resolution_service.py#L40`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/session_resolution_service.py#L40)) checks an in-memory dictionary of 4 cameras (`_CAMERA_REGISTRY`) and falls back to string parsing (`CAM_ROOM_101` -> `ROOM_101`) or returns the camera ID as-is.
  - An attacker can inject fake `ENTRY` and `EXIT` events for any student without needing credentials or camera verification.

### 4. Dashboard Presence Feed: Static REST vs. "Real-Time Feed"
- **Notion Claim:** Dashboard features a *"real-time presence feed"*, yet elsewhere notes WebSocket/SSE is not done.
- **Repo Reality:** [`frontend/src/components/session/SessionAttendance.tsx#L59`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/src/components/session/SessionAttendance.tsx#L59) performs a **single static HTTP GET** on component mount:
  ```typescript
  useEffect(() => {
    fetchAttendance(false);
  }, [fetchAttendance]);
  ```
  - There are NO WebSockets (`ws://`), NO Server-Sent Events (`EventSource`), and NO background `setInterval` polling loops.
  - Real-time updates only occur if a teacher manually clicks the "Refresh" button.

---

## 5. TrackEvidence & Pipeline Defect Inspection (Item 4)

Detailed code inspection of [`vision-service/pipeline/live_cv_pipeline.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py):

### Defect 4A: Same Track Repeated Direction Suppression (Re-entry Bug)
- **Question:** Can a single track ID emit `ENTRY`, `EXIT`, `ENTRY` (student steps in, steps out to take a phone call, and re-enters)?
- **Code Evidence:**
  [`live_cv_pipeline.py#L222`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L222):
  ```python
  emitted_directions: set[str] = field(default_factory=set)
  ```
  [`live_cv_pipeline.py#L318-L321`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L318-L321):
  ```python
  if new_direction and new_direction not in self.emitted_directions:
      if new_direction not in self.pending_directions:
          self.pending_directions.append(new_direction)
  ```
  [`live_cv_pipeline.py#L667`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L667):
  ```python
  evidence.emitted_directions.add(direction)
  ```
  [`events/event_dispatcher.py#L174-L186`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/events/event_dispatcher.py#L174-L186):
  ```python
  track_key = (camera_id, track_id, direction)
  if self.dedup_by_track and track_key in self._dispatched_track_events:
      return {"event_id": event_id, "status": "duplicate", ...}
  ```
- **Finding:** **REPEATED DIRECTIONS ARE PERMANENTLY SUPPRESSED.**
  Once a track emits `ENTRY`, `"ENTRY"` is added to `emitted_directions`. When the person leaves, it emits `EXIT`, adding `"EXIT"`. If the person re-enters on the same track ID, `new_direction not in self.emitted_directions` evaluates to **FALSE**. The second `ENTRY` is permanently dropped by both `live_cv_pipeline.py` and `EventDispatcher`.
- **Severity:** HIGH. If a student leaves and re-enters without ByteTrack dropping the track ID, the second entry is lost.

### Defect 4B: Inability to Re-Verify Confirmed Tracks (Identity Lock-In)
- **Question:** Can confirmed tracks ever be re-verified with ArcFace?
- **Code Evidence:**
  [`live_cv_pipeline.py#L566-L590`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L566-L590):
  ```python
  if not evidence.is_confirmed:
      # Execute ArcFace embedding extraction & similarity matching
      ...
  else:
      # Track is ALREADY CONFIRMED: Skip ArcFace entirely!
      evidence.update_position(bbox=..., timestamp=...)
  ```
- **Finding:** **CONFIRMED TRACKS ARE NEVER RE-VERIFIED.**
  Once a track receives 3 votes (or reaches max attempts), `is_confirmed` is set to `True`. ArcFace is completely bypassed for the remainder of that track's lifetime.
- **Risk:** If ByteTrack experiences an ID switch during an occlusion (e.g. Student A walks behind Student B and ByteTrack swaps tracks), Student B will inherit Student A's identity indefinitely with zero opportunity for correction.

### Defect 4C: Spatial Deadband Inadequacy (±4.0px at 640x360)
- **Question:** Is a `±4.0px` deadband adequate at 640x360 resolution?
- **Code Evidence:**
  [`live_cv_pipeline.py#L27-L47`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L27-L47):
  ```python
  def classify_point_side(cx, cy, boundary_p1, boundary_p2, deadband=4.0):
      ...
      if cy < line_y - deadband:
          return "SIDE_A"
      elif cy > line_y + deadband:
          return "SIDE_B"
      else:
          return "ON_LINE"
  ```
- **Finding:** **±4.0px IS MATHEMATICALLY INADEQUATE FOR REAL VIDEO.**
  1. At 640x360, a face bounding box is roughly 40x40 to 80x80 pixels.
  2. Bounding box centroid jitter between consecutive frames on stationary subjects routinely ranges between 2 to 6 pixels due to SCRFD detector variance.
  3. A deadband of ±4.0px (8px total width) is barely 2.2% of the vertical canvas height. A student hesitating near the boundary will oscillate across the deadband.
  4. Conversely, a student walking briskly towards the camera covers 15–30 pixels per frame, jumping clean over the 8px deadband in a single frame.
  5. The deadband should be adaptive (e.g. 15–20% of bounding box height, ~12–16px) with an explicit hysteresis state machine rather than instantaneous point evaluation.

---

## 6. Missing EXIT Behavior & Presence Engine Flaw

- **Code Inspection:** [`backend/app/services/presence_engine.py#L43-L74`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/presence_engine.py#L43-L74):
  ```python
  intervals: list[PresenceInterval] = []
  open_entry: datetime | None = None

  for event in sorted_events:
      direction = event["direction"]
      timestamp = event["timestamp"]

      if direction == "ENTRY":
          if open_entry is None:
              open_entry = timestamp
      elif direction == "EXIT":
          if open_entry is not None:
              intervals.append(PresenceInterval(entry_time=open_entry, exit_time=timestamp))
              open_entry = None

  # Notice: open_entry is NEVER closed at end of loop!
  return PresenceResult(intervals=intervals, total_presence_seconds=sum(...))
  ```
- **Verified Behavior in Test:** [`backend/tests/test_session_scoped_events.py#L250-L283`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_session_scoped_events.py#L250-L283):
  ```python
  async def test_entry_without_exit_preserved():
      """ENTRY without subsequent EXIT is preserved with zero closed intervals."""
      ...
      assert rec["presence_duration_seconds"] == 0.0
      assert rec["presence_percentage"] == 0.0
      assert rec["status"] == "ABSENT"
      assert rec["presence_intervals"] == []
  ```
- **Finding:** **UNCLOSED ENTRIES RESULT IN 0% PRESENCE AND ABSENT STATUS.**
  If a student enters class at 10:05 and remains until session end (with no camera EXIT event recorded), `open_entry` is simply dropped. The student receives `0.0 seconds` presence and is finalized as `ABSENT`.
- **Contradiction with Notion:** Notion claimed: *"Handles missing EXIT events at session finalization by capping at session end time."* The code does NOT cap at session end time; it discards the open entry completely.

---

## 7. Comprehensive Capabilities Matrix

Classified with verified file and test evidence across all 22 required areas:

| Area | Status | File Evidence | Test Evidence | Gap Description |
| :--- | :--- | :--- | :--- | :--- |
| **1. Biometric Enrollment** | **MISSING** | `vision-service/pipeline/live_cv_pipeline.py#L80` | None (static disk read) | Biometric embeddings are loaded from static disk directory (`load_gallery`). No API, no vector DB, no student self-enrollment. |
| **2. Enrollment Quality Gates** | **MISSING** | None | None | No checks for blur, illumination, head pose, or minimum bounding box size. |
| **3. Multi-Image Enrollment** | **PARTIAL** | `vision-service/pipeline/live_cv_pipeline.py#L107` | `test_insightface.py` | `load_gallery` averages embeddings if multiple images exist in a directory on disk. No multi-shot capture UI or quality weighting. |
| **4. Duplicate / Re-enroll / Delete** | **MISSING** | None | None | No duplicate face detection across students, no re-enrollment flow, no deletion endpoint. |
| **5. Service Auth on `/events`** | **MISSING** | `backend/app/api/routes/events.py#L26` | None | Open endpoint. No API key, bearer token, HMAC, or mTLS. |
| **6. Secrets / Environment** | **PARTIAL** | `backend/app/security/config.py#L6`, `.env.example` | `test_jwt.py` | Loads `backend/.env` for `JWT_SECRET_KEY`. No centralized secrets management or vault. Root `.env.example` lacks vision/camera configs. |
| **7. CORS Security** | **PARTIAL / INSECURE** | `backend/app/main.py#L49-L55` | None | Uses `allow_origins=["*"]` with `allow_credentials=True`. This is invalid per CORS spec and allows unauthorized cross-origin requests. |
| **8. Retry & Outbox** | **MISSING** | `vision-service/events/event_dispatcher.py` | `test_event_dispatcher.py#L47` | Synchronous HTTP calls. Errors immediately fail. No disk outbox, SQLite buffer, or exponential retry. |
| **9. Idempotency Index** | **DONE** | `backend/app/database/mongodb.py#L45` | `backend/tests/test_attendance_idempotency.py` | Unique index `unique_event_id_idx` on `event_id` enforced in MongoDB and handled with `DuplicateKeyError`. |
| **10. Restart Recovery** | **PARTIAL** | `backend/app/database/mongodb.py` | None | Backend recovers state from MongoDB. Vision service pipeline state (`tracks`, deduplication sets) is in-memory and lost on restart. |
| **11. Missing EXIT Handling** | **PARTIAL / FLAWED** | `backend/app/services/presence_engine.py#L50` | `test_session_scoped_events.py#L250` | Discards unclosed `open_entry`. Results in 0% presence and `ABSENT` rather than clamping to session end time. |
| **12. Camera Registry & Health** | **PARTIAL** | `backend/app/services/session_resolution_service.py#L9` | `test_session_resolution.py` | Hardcoded in-memory dictionary of 4 cameras. No DB collection, no camera health check, no heartbeat. |
| **13. RTSP Usability** | **PARTIAL** | `vision-service/camera/rtsp_source.py` | `test_video_source.py#L32` | Basic OpenCV `cv2.VideoCapture` wrapper. Lacks low-latency FFmpeg parameters, TCP/UDP fallback, and authentication credentials. |
| **14. Multi-Camera & Roles** | **PARTIAL** | `backend/app/services/session_resolution_service.py` | `test_session_resolution.py#L40` | Multiple cameras can map to one classroom, but camera roles (`ENTRY_ONLY`, `EXIT_ONLY`, `BIDIRECTIONAL`) do not exist. |
| **15. Boundary Configuration** | **PARTIAL** | `vision-service/pipeline/live_cv_pipeline.py#L390` | `test_cv_event_pipeline.py#L2` | Math exists, but coordinates are hardcoded in Python instantiation. No UI or API to calibrate boundary per camera. |
| **16. Live Dashboard Updates** | **MISSING** | `frontend/src/pages/TeacherDashboard.tsx` | None | No WebSockets, SSE, or auto-polling. Pure static REST on mount + manual refresh button. |
| **17. Liveness Detection** | **MISSING** | None | None | No anti-spoofing model, blink detection, texture analysis, or depth checks. Vulnerable to photos/screens. |
| **18. Accuracy Eval Tooling** | **PARTIAL** | `vision-service/tests/recognition_benchmark.py` | `test_webrtc_cv_benchmark.py` | Offline benchmark scripts run against 4 test subjects. No standardized ROC/FAR/FRR evaluation suite. |
| **19. Docker & Compose** | **PARTIAL** | `docker-compose.yml`, `backend/Dockerfile` | None | `docker-compose.yml` only contains backend. No MongoDB service, no vision-service, no frontend container. |
| **20. CI & Pre-Commit** | **PARTIAL** | `.github/workflows/.gitkeep`, `.pre-commit-config.yaml` | None | `.github/workflows` is empty (no CI). Pre-commit has only generic whitespace/format hooks; no linters or typecheckers. |
| **21. Security Scanners** | **MISSING** | None | None | Bandit, Semgrep, Gitleaks, pip-audit, and Trivy are not configured in repo or CI. |
| **22. Biometric Retention** | **MISSING** | `docs/adr/ADR-004-biometric-storage.md` | None | Stated as policy in ADR-004, but zero implementation exists. Test face images are permanently committed in git. |

---

## 8. Security Audit Findings

### A. Committed Secrets Check
- Ran regex scan across `git ls-files` and commit history for `.env`, private keys (`.pem`, `.key`), tokens, and hardcoded credentials.
- **Finding:** No active production secrets or private keys were committed to git.
- `.env` is properly ignored in `.gitignore`. Local `backend/.env` contains development keys only.

### B. Committed Media, Models, & Weights
- **Model Checkpoints:** No `.onnx`, `.pt`, or `.weights` binaries committed in git.
- **Committed Media (Privacy Concern):**
  - 3 video files committed: [`multi_person_simultaneous.mp4`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/video_test/multi_person_simultaneous.mp4), [`person_1_vid.mp4`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/video_test/person_1_vid.mp4), [`person_2_vid.mp4`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/video_test/person_2_vid.mp4).
  - Multiple raw facial photographs committed under [`vision-service/tests/recognition_benchmark/person_0*/*.jpg`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/recognition_benchmark/).
  - Violates data minimization principles stated in ADR-004. These should be moved to git-lfs or generated test fixtures.

### C. Open Endpoints & Service Authentication
- [`POST /api/v1/events`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/routes/events.py#L26): Completely unprotected. Allows unauthenticated event spoofing and denial of service.

### D. CORS Misconfiguration
- [`backend/app/main.py#L51-L52`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/main.py#L51-L52):
  ```python
  allow_origins=["*"],
  allow_credentials=True,
  ```
  `allow_origins=["*"]` combined with `allow_credentials=True` violates security standards and is rejected by modern browsers executing credentialed requests.

### E. Sensitive Logging Audit
- Inspected all `logger.*` statements across backend and vision services.
- **Finding:** Clean. No passwords, JWT secrets, raw embeddings, or tokens are logged. Only exception traces and track IDs are emitted.

---

## 9. Recommended Adjustments to Steps 2E.1 – 2E.14

Based on repo truth, the Phase 2E roadmap can be significantly optimized. Redundant work can be eliminated while high-risk gaps are prioritized:

| Step | Original Scope | Repo Reality & Recommended Adjustment | Priority & Action |
| :--- | :--- | :--- | :--- |
| **2E.1** | Service Auth on `/events` | Completely missing. Implement a lightweight pre-shared camera token header (`X-Camera-Token`) verified via FastAPI dependency. | **CRITICAL — Do immediately.** |
| **2E.2** | Event Dispatcher Robustness | Currently synchronous `requests.Session`. Implement an in-memory queue + background worker thread with simple exponential backoff. Skip distributed queues (Kafka/RabbitMQ). | **HIGH — Shrink to in-memory queue.** |
| **2E.3** | Student Face Enrollment | Missing. Implement backend embedding storage (MongoDB vector field) + student profile photo upload endpoint with basic quality check (SCRFD face count == 1). | **HIGH — Implement minimum viable enrollment.** |
| **2E.4** | Fix TrackEvidence Defect | Suppresses re-entry and never re-verifies. Fix `emitted_directions` to track current state (`last_emitted_direction`), widen deadband to 14px, and add periodic re-verification. | **HIGH — Fix 3 code defects.** |
| **2E.5** | Fix Missing EXIT Handling | Discards open entries (student marked ABSENT). Update `presence_engine.py` to clamp open entry to `session_end` when finalization occurs. | **HIGH — Fix presence engine bug.** |
| **2E.6** | Camera Registry & Health | In-memory dict only. Add a simple MongoDB `cameras` collection + camera heartbeat update on event receipt. | **MEDIUM — Shrink to basic DB model.** |
| **2E.7** | Multi-Camera & Roles | Mapping exists; roles missing. Add `role: "ENTRY" \| "EXIT" \| "BIDIRECTIONAL"` to camera config. | **MEDIUM — Simple enum check.** |
| **2E.8** | Live UI Presence Feed | No live updates exist. Implement Server-Sent Events (SSE) or simple 2-second polling in React. Skip bidirectional WebSockets. | **MEDIUM — Shrink to SSE / short poll.** |
| **2E.9** | Liveness Detection | 100% missing. Add a lightweight blink/motion heuristic across the 3 confirmation frames to block static photo attacks. | **MEDIUM — Lightweight heuristic only.** |
| **2E.10** | Real-Face E2E Integration | Existing test was 100% mocked. Create a test that runs real video ([`person_1_vid.mp4`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/video_test/person_1_vid.mp4)) through live SCRFD+ArcFace into backend and verifies attendance. | **CRITICAL — Prove real-face loop.** |
| **2E.11** | Full Docker Compose | Missing Mongo, Vision, Frontend. Write multi-stage Dockerfiles and complete `docker-compose.yml` for 1-command startup. | **HIGH — Required for demo.** |
| **2E.12** | GitHub Actions CI | Empty workflow directory. Add single `.github/workflows/ci.yml` running backend tests, vision tests, and frontend build. | **HIGH — Required for DevSecOps.** |
| **2E.13** | Security Scanners in CI | Missing. Add Bandit and Gitleaks steps to GitHub Actions pipeline. Defer complex Trivy/Semgrep configs. | **MEDIUM — Add Bandit + Gitleaks.** |
| **2E.14** | Biometric Retention & Audit | Documented in ADR-004 but un-coded. Add a scheduled purge job or TTL index for raw upload photos. | **LOW — Add automated TTL index.** |

---

## 10. Audit Conclusion & Next Immediate Step

Step 2D.5 established a functioning algorithmic core on synthetic data, but left critical security holes (unprotected `/events`), state machine bugs (re-entry suppression, open entry dropped as ABSENT), and an unproven real-face end-to-end loop.

**Recommended Next Step:** Proceed to **Step 2E.1** (Camera Service Authentication on `/api/v1/events` and CORS hardening) followed by **Step 2E.4 & 2E.5** (TrackEvidence state machine & missing EXIT presence fixes).
