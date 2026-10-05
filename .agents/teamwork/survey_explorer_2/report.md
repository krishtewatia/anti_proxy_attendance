# Survey Explorer 2: Technical Report — Requirement R2
# Reliable Real-Time Mobile Detection & Event Dispatch Pipeline

**Date**: 2026-10-03
**Component**: `vision-service`, WebRTC Mobile Ingest, Event Dispatcher, Backend Event Ingestion
**Author**: Survey Explorer 2 (`teamwork_preview_explorer`)

---

## 1. Executive Summary

Requirement R2 streamlines the anti-proxy computer vision pipeline for a live 4-person demo using a mobile phone held at a doorway. The mobile phone connects to the Vision Service's built-in WebRTC server on port 8088.

Our audit of `vision-service/camera/webrtc_receiver.py`, `vision-service/pipeline/live_cv_pipeline.py`, and `vision-service/run_webrtc_camera.py` revealed several critical observations:

1. **Boundary Line Default**: `LiveCVPipeline` currently defaults to a **horizontal** dividing line (`y = 0.5 * height`) when `boundary_line=None`. For a doorway where a person walks left-to-right past a smartphone in portrait or landscape orientation, the default must be a **vertical dividing line** (`x = 0.5 * width`).
2. **Gating & Confirmation**: In `run_webrtc_camera.py`, `min_supporting_frames` is hardcoded to `2` (and defaults to `3` in `LiveCVPipeline`). For rapid doorway crossing, reducing this to `1` or `2` frames ensures that the very first high-confidence face detection confirms the student's identity and emits the transit event immediately upon line crossing.
3. **Kinematic Anti-Spoof Policy**: The pipeline supports policy `FLAG` or `REJECT`. If set to `REJECT`, rapid transits (< 0.20s duration) or low pixel displacements (< 15px) are completely dropped. Under policy `FLAG`, kinematic telemetry is recorded and logged, but events are **never dropped**, ensuring 100% transit reliability during fast movement or frame-rate drops.
4. **Mobile WebRTC Overlay & Manual Buttons**: The embedded web interface in `HTML_PHONE_CLIENT` currently draws a horizontal HUD line and has outdated buttons for synthetic users (`student_alice`, `student_bob`). It must be updated to render a vertical boundary line with directional indicators (Side A `[Entry ➔]`, `[➔ Side B]` In Room) and dedicated quick-action transit buttons for all 4 demo students (`person_01` through `person_04`).
5. **Backend Dispatch Trace**: Events dispatched by `EventDispatcher` to `POST /api/v1/events` authenticate via the `X-API-Key` header, resolve camera `CAM_ROOM_101_DOOR` to classroom `ROOM_101`, and bind dynamically to active session `sess_demo_cs101`. The live snapshot endpoint (`GET /api/v1/sessions/sess_demo_cs101/live-snapshot`) immediately calculates state changes (`INSIDE` on entry, `OUTSIDE` on exit) and live dwell times.

---

## 2. Component Architecture & Ingestion Flow

```
+----------------------------------------------------------------------------------------------------+
|                                    MOBILE PHONE BROWSER (PORT 8088)                                 |
|                                                                                                    |
|   navigator.mediaDevices.getUserMedia()                                                             |
|           │                                                                                        |
|   <video> Display with HUD Overlay (Vertical Line x=0.5, Side A ➔ Side B)                          |
|           │                                                                                        |
|   RTCPeerConnection.addTrack() ──► WebRTC Offer / Answer (H.264/VP8 over UDP)                      |
|                                                                                                    |
|   Manual Quick-Action Buttons [ + Enter ] [ − Exit ] ──► POST /transit                             |
+───────────────────────────────────────────────────┬────────────────────────────────────────────────+
                                                    │
                                                    ▼
+----------------------------------------------------------------------------------------------------+
|                                    VISION SERVICE (PORT 8088 & PIPELINE)                           |
|                                                                                                    |
|   camera/webrtc_receiver.py (WebRTCSignalingServer on Port 8088)                                   |
|     • GET /          ──► Serves HTML_PHONE_CLIENT                                                  |
|     • POST /offer    ──► Handles SDP offer/answer via aiortc                                       |
|     • POST /transit  ──► Immediate event dispatch fallback for selected student                   |
|     • Frame Consumer ──► PyAV decodes RTP frames ──► PhoneVideoSource (bounded queue)              |
|                                                                                                    |
|   pipeline/live_cv_pipeline.py (LiveCVPipeline.process_frame)                                      |
|     1. Face Detection: SCRFD-0.5G (ONNX CPU threads configured)                                    |
|     2. Tracking: ByteTrack multi-object tracker (IoU association)                                  |
|     3. Track-Gated Recognition: ArcFace 512-d cosine similarity against gallery                   |
|        - Identity confirmed when vote_count >= min_supporting_frames (1 or 2)                      |
|     4. Boundary Evaluation: classify_point_side(cx, cy, bp1, bp2, deadband=4px)                    |
|        - Vertical Line at x = 0.5 * W: Side A (Left) ➔ Side B (Right) = ENTRY                     |
|        - Side B (Right) ➔ Side A (Left) = EXIT                                                     |
|     5. Anti-Spoof Check: kinematic_spoof_policy == "FLAG" (logs warning, emits event)              |
|                                                                                                    |
|   events/event_dispatcher.py (EventDispatcher.send_event)                                          |
|     • Formats payload: VisionEventCreate (event_id, camera_id, track_id, identity, direction, ...) |
|     • Adds Header: X-API-Key: <VISION_SERVICE_API_KEY>                                             |
+───────────────────────────────────────────────────┬────────────────────────────────────────────────+
                                                    │
                                                    ▼ HTTP POST /api/v1/events
+----------------------------------------------------------------------------------------------------+
|                                    BACKEND FASTAPI SERVICE (PORT 8000)                             |
|                                                                                                    |
|   app/api/routes/events.py (ingest_vision_event)                                                   |
|     1. require_camera_auth: Validates X-API-Key against settings.VISION_SERVICE_API_KEY            |
|     2. Idempotency Check: Checks events collection for existing event_id                          |
|     3. resolve_classroom_for_camera_db: CAM_ROOM_101_DOOR ──► ROOM_101                             |
|     4. find_active_session_for_classroom: Active window in ROOM_101 ──► sess_demo_cs101            |
|     5. MongoDB Insert: Persists event document in events collection                                |
|                                                                                                    |
|   app/api/routes/sessions.py (get_session_live_snapshot_endpoint)                                  |
|     • Teacher polls GET /api/v1/sessions/sess_demo_cs101/live-snapshot                             |
|     • Computes live presence: student state = INSIDE (ENTRY) or OUTSIDE (EXIT)                     |
|     • Dwell timers and presence percentages update dynamically                                     |
+----------------------------------------------------------------------------------------------------+
```

---

## 3. Detailed Investigation of Requirement R2 Sub-Items

### 3.1 Boundary Line Definition, Geometry, and Transit Evaluation

#### File & Line References
- `vision-service/pipeline/live_cv_pipeline.py`:
  - Lines 25–71: `classify_point_side(cx, cy, boundary_p1, boundary_p2, deadband=4.0)`
  - Lines 376–470: `TrackEvidence.update_boundary_position(...)`
  - Lines 931–946: Native pixel boundary line determination in `process_frame()`

#### How the Boundary Line is Defined & Evaluated
In `LiveCVPipeline`, `self.boundary_line` accepts a pair of points `((x1, y1), (x2, y2))`.
Currently, lines 931–946 in `live_cv_pipeline.py` contain:
```python
if self.boundary_line is not None:
    p1_raw, p2_raw = self.boundary_line
    if p1_raw[0] <= 1.0 and p1_raw[1] <= 1.0 and p2_raw[0] <= 1.0 and p2_raw[1] <= 1.0:
        bp1 = (p1_raw[0] * orig_w, p1_raw[1] * orig_h)
        bp2 = (p2_raw[0] * orig_w, p2_raw[1] * orig_h)
    else:
        bp1, bp2 = p1_raw, p2_raw
else:
    # CURRENT DEFAULT IS HORIZONTAL:
    bp1 = (0.0, orig_h * 0.5)
    bp2 = (float(orig_w), orig_h * 0.5)
```
When `run_webrtc_camera.py` starts without passing `boundary_line`, it defaults to `None`, producing a horizontal line at `y = 0.5 * orig_h`.

#### Spatial Classification (`classify_point_side`)
`classify_point_side` compares face centroid `(cx, cy)` against line $P_1(x_1, y_1) \rightarrow P_2(x_2, y_2)$ with hysteresis `deadband`:
```python
if abs(x2 - x1) <= 1e-5:
    # Vertical boundary line
    line_x = x1
    if cx < line_x - deadband:
        return "SIDE_A"
    elif cx > line_x + deadband:
        return "SIDE_B"
    else:
        return "ON_LINE"
```
For a vertical dividing line at $x_1 = x_2 = 0.5 \cdot \text{width}$:
- **Side A**: $cx < 0.5 \cdot \text{width} - \text{deadband}$ (Left side of frame)
- **Side B**: $cx > 0.5 \cdot \text{width} + \text{deadband}$ (Right side of frame)
- **Hysteresis Deadband**: $|cx - 0.5 \cdot \text{width}| \le \text{deadband}$ (returns `"ON_LINE"`, preventing state oscillation when paused on the threshold).

#### Transit Direction Evaluation
In `TrackEvidence.update_boundary_position`:
- Initial position records `self.initial_side` and `self.current_side`.
- When `entry_side == "SIDE_A"`:
  - Transition from `"SIDE_A"` to `"SIDE_B"` (Left to Right) sets `new_direction = "ENTRY"`.
  - Transition from `"SIDE_B"` to `"SIDE_A"` (Right to Left) sets `new_direction = "EXIT"`.
- Jitter Suppression & Re-entry:
  `if new_direction and new_direction != self.last_emitted_direction:`
  Blocks repeated `ENTRY` $\rightarrow$ `ENTRY` duplicates while permitting legitimate re-crossing (`ENTRY` $\rightarrow$ `EXIT` $\rightarrow$ `ENTRY`).

#### Proposed Changes
1. In `live_cv_pipeline.py`, change fallback when `self.boundary_line is None`:
   ```python
   else:
       # Default vertical dividing line at x = 0.5 * orig_w
       bp1 = (orig_w * 0.5, 0.0)
       bp2 = (orig_w * 0.5, float(orig_h))
   ```
2. In `run_webrtc_camera.py`, add CLI parameters:
   - `--boundary-line` (default: `"vertical"` / `((0.5, 0.0), (0.5, 1.0))`)
   - `--entry-side` (default: `"SIDE_A"`)
   Pass `boundary_line=((0.5, 0.0), (0.5, 1.0))` and `entry_side=args.entry_side` when initializing `LiveCVPipeline`.
3. In `scripts/seed_clean_demo.py`, update camera registry `boundary_config`:
   ```python
   "boundary_config": {
       "p1": [0.5, 0.0],
       "p2": [0.5, 1.0],
       "entry_side": "SIDE_A",
       "deadband_pixels": 4.0,
   }
   ```

---

### 3.2 Tracking Gating Logic & Rapid Doorway Transit

#### File & Line References
- `vision-service/pipeline/live_cv_pipeline.py`:
  - Line 313: `TrackEvidence.add_observation(..., min_supporting_frames=3, ...)`
  - Line 472: `TrackEvidence.get_emittable_directions()`
  - Line 660: `LiveCVPipeline.__init__(..., min_supporting_frames=3, ...)`
  - Lines 908–916: Invocation of `add_observation` in `process_frame()`
- `vision-service/run_webrtc_camera.py`:
  - Line 218: `min_supporting_frames=2` (hardcoded in instantiation)

#### Current Mechanism
In `TrackEvidence.add_observation`:
```python
if identity != "UNKNOWN":
    self.supporting_frames += 1
    self.identity_votes[identity] += 1
    self.similarities[identity].append(score)

if self.identity_votes:
    top_candidate, vote_count = max(self.identity_votes.items(), key=lambda kv: kv[1])
    if vote_count >= min_supporting_frames:
        self.assigned_identity = top_candidate
        self.is_confirmed = True
```
In `TrackEvidence.get_emittable_directions()`:
```python
if not self.is_confirmed:
    return []
if self.assigned_identity == "UNKNOWN" or not self.assigned_identity:
    return []
```
If a student walks across the doorway, they may only be cleanly visible to the mobile camera for 1 or 2 frames before crossing the centerline. If `min_supporting_frames = 3` or `2`, and only 1 frame was processed prior to crossing, `is_confirmed` remains `False`, and `get_emittable_directions()` returns empty, **dropping the event**.

#### Proposed Solution for Rapid Transit
1. Add `--min-supporting-frames` argument to `run_webrtc_camera.py` with default `1` (or read from `os.getenv("MIN_SUPPORTING_FRAMES", "1")`):
   ```python
   parser.add_argument(
       "--min-supporting-frames",
       type=int,
       default=int(os.getenv("MIN_SUPPORTING_FRAMES", "1")),
       help="Minimum biometric votes needed to confirm identity (default: 1)",
   )
   ```
2. When set to `1`, the first recognized ArcFace match immediately confirms the identity (`is_confirmed = True`), allowing an immediate transit emission as soon as the line is crossed.

---

### 3.3 Anti-Spoofing Policy (`kinematic_spoof_policy`)

#### File & Line References
- `vision-service/pipeline/live_cv_pipeline.py`:
  - Lines 428–466: Trajectory anomaly detection in `TrackEvidence.update_boundary_position`
  - Lines 631–655: Policy parameter initialization (`"FLAG"` vs `"REJECT"`)
  - Lines 1002–1025: Policy enforcement in `LiveCVPipeline.process_frame()`
- `vision-service/run_webrtc_camera.py`:
  - Lines 105–115: `--kinematic-anti-spoof` and `--kinematic-policy` arguments

#### Enforcement Logic
Anomalies detected during boundary crossing:
- `INSUFFICIENT_DISPLACEMENT`: Net centroid displacement $< 15.0\,\text{px}$.
- `INSTANT_TRANSIT`: Net transit duration $< 0.20\,\text{seconds}$.
- `STATIONARY_HOVER`: Duration $> 8.0\,\text{seconds}$ with low displacement.

When an anomaly is flagged:
```python
if self.enable_kinematic_anti_spoof and evidence.kinematic_anomalies:
    if self.kinematic_spoof_policy == "REJECT":
        logger.warning("Kinematic anti-spoof REJECTED transit event...")
        if direction in evidence.pending_directions:
            evidence.pending_directions.remove(direction)
        continue  # <--- EVENT COMPLETELY DROPPED
    else:
        logger.warning("Kinematic anti-spoof FLAGGED transit event...")
        # <--- EVENT PROCEEDS NORMALLY WITH WARNING LOGGED
```

#### How to Guarantee Policy is `FLAG`
1. In `run_webrtc_camera.py`:
   The argument default is already `os.getenv("KINEMATIC_SPOOF_POLICY", "FLAG")`.
2. In `LiveCVPipeline.__init__`:
   Ensure default is `"FLAG"`.
3. In Docker/Environment configurations:
   Export `KINEMATIC_SPOOF_POLICY=FLAG`.
4. Effect: With `FLAG`, fast doorway crossing or WebRTC frame latency never causes false rejection of real students, while security audit fields (`kinematic_status: "FLAGGED_INSTANT"` and `kinematic_anomalies`) are preserved in the payload.

---

### 3.4 WebRTC Mobile Camera Server & Client Interface

#### File & Line References
- `vision-service/camera/webrtc_receiver.py`:
  - Lines 22–577: `HTML_PHONE_CLIENT` template string
  - Lines 580–700: `WebRTCReceiver` (track consumption via PyAV)
  - Lines 702–908: `WebRTCSignalingServer` (aiohttp application)

#### Server Mechanics
- Listens on `0.0.0.0:8088`.
- Running in a background daemon thread via `server.start_background()`.
- Routes:
  - `GET /`: Serves `HTML_PHONE_CLIENT`. If `access_token` configured, checks `?token=`, `Authorization: Bearer`, or `X-Access-Token`.
  - `POST /offer`: Receives browser SDP offer, returns SDP answer.
  - `POST /transit`: Receives manual button triggers `{ "identity": "...", "direction": "..." }`.
  - `GET /status` and `GET /health`: Operational telemetry endpoints.

#### Client Streaming Flow
1. Operator loads `http://<LAN_IP>:8088/` on phone browser (Chrome/Safari).
2. Operator clicks "START LIVE ATTENDANCE SCANNER":
   - Requests camera via `navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: 1280, height: 720, frameRate: 30 } })`.
   - Displays local video in `<video id="localVideo" autoplay playsinline muted>`.
3. SDP Offer Creation & ICE Gathering:
   - Creates `RTCPeerConnection` with STUN `stun:stun.l.google.com:19302`.
   - Adds local video track.
   - Creates offer, waits for ICE gathering, and POSTs offer to `/offer`.
4. Peer Connection Established:
   - Receives SDP answer and applies `setRemoteDescription`.
   - Inbound RTP frames are consumed by `WebRTCReceiver._consume_track`:
     ```python
     frame: av.VideoFrame = await track.recv()
     bgr_array: np.ndarray = frame.to_ndarray(format="bgr24")
     self.video_source.push_frame(bgr_array, timestamp=now)
     ```
   - Frames enter `PhoneVideoSource`'s bounded buffer for processing by `LiveCVPipeline`.

---

### 3.5 Rendering the Vertical Boundary Line Guide on Mobile Feed

#### Current Horizontal HUD Implementation
In `webrtc_receiver.py` (lines 181–210):
```css
.doorway-hud-line {
    position: absolute;
    top: 50%;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, rgba(16,185,129,0.2) 0%, rgba(16,185,129,0.85) 50%, rgba(16,185,129,0.2) 100%);
    box-shadow: 0 0 10px rgba(16, 185, 129, 0.6);
    pointer-events: none;
    z-index: 4;
}
.doorway-hud-label {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -120%);
    ...
}
```

#### Proposed Vertical HUD Implementation
Update CSS and HTML structure in `HTML_PHONE_CLIENT` as follows:

```css
/* Vertical Boundary Guide */
.doorway-hud-line {
    position: absolute;
    top: 0;
    bottom: 0;
    left: 50%;
    width: 2px;
    background: linear-gradient(180deg, rgba(16,185,129,0.2) 0%, rgba(16,185,129,0.95) 50%, rgba(16,185,129,0.2) 100%);
    box-shadow: 0 0 12px rgba(16, 185, 129, 0.7);
    pointer-events: none;
    z-index: 4;
    transform: translateX(-50%);
}

.doorway-hud-label {
    position: absolute;
    top: 10px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(16, 185, 129, 0.25);
    border: 1px solid rgba(16, 185, 129, 0.6);
    border-radius: 4px;
    padding: 3px 8px;
    font-size: 0.65rem;
    font-weight: 700;
    color: #34d399;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    pointer-events: none;
    z-index: 4;
    white-space: nowrap;
}

/* Directional Approach & Inside Annotations */
.doorway-side-guide {
    position: absolute;
    bottom: 12px;
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 0.70rem;
    font-weight: 700;
    pointer-events: none;
    z-index: 4;
    letter-spacing: 0.03em;
}

.doorway-side-guide.side-a {
    left: 12px;
    background: rgba(99, 102, 241, 0.3);
    border: 1px solid rgba(99, 102, 241, 0.5);
    color: #c7d2fe;
}

.doorway-side-guide.side-b {
    right: 12px;
    background: rgba(16, 185, 129, 0.3);
    border: 1px solid rgba(16, 185, 129, 0.5);
    color: #6ee7b7;
}
```

And in the viewport HTML:
```html
<div class="viewport-card">
    <video id="localVideo" autoplay playsinline muted></video>
    <div class="doorway-hud-line"></div>
    <div class="doorway-hud-label">Transit Line (x = 50%)</div>
    <div class="doorway-side-guide side-a">Side A (Entry ➔)</div>
    <div class="doorway-side-guide side-b">(➔ Side B) In Room</div>
    <div class="overlay-stats" id="statsOverlay">
        ...
    </div>
</div>
```

---

### 3.6 Mobile Manual Quick-Action Transit Buttons

#### Current State
Lines 377–396 in `webrtc_receiver.py` have buttons for `person_01`, `student_alice`, and `student_bob`:
```html
<div class="quick-actions-card">
    <div class="quick-actions-header">
        <span>⚡ Instant Transit Triggers (Push to PC):</span>
        <span style="font-size:0.7rem; color:#94a3b8">1-Tap Test</span>
    </div>
    <div class="actions-grid">
        <button type="button" class="btn-action entry" onclick="sendTransit('person_01', 'ENTRY')">
            + Enter: Person 01 (Demo)
        </button>
        <button type="button" class="btn-action exit" onclick="sendTransit('person_01', 'EXIT')">
            − Exit: Person 01
        </button>
        <button type="button" class="btn-action entry" onclick="sendTransit('student_alice', 'ENTRY')">
            + Enter: Alice Smith
        </button>
        <button type="button" class="btn-action entry" onclick="sendTransit('student_bob', 'ENTRY')">
            + Enter: Bob Jones
        </button>
    </div>
    <div id="toastMsg" class="toast-msg"></div>
</div>
```

#### Proposed Solution for 4 Demo Students
Replace the grid with dedicated rows for `student1` through `student4` (`person_01` through `person_04`):

```html
<div class="quick-actions-card">
    <div class="quick-actions-header">
        <span>⚡ Manual Transit Triggers (Operational Fallback):</span>
        <span style="font-size:0.7rem; color:#94a3b8">CS-101 Demo</span>
    </div>
    <div class="student-transit-list">
        <!-- Student 1 -->
        <div class="student-row">
            <div class="student-info">
                <strong>Student 1</strong> <span class="badge-id">person_01</span>
            </div>
            <div class="btn-pair">
                <button type="button" class="btn-action entry" onclick="sendTransit('person_01', 'ENTRY')">
                    🟢 Enter
                </button>
                <button type="button" class="btn-action exit" onclick="sendTransit('person_01', 'EXIT')">
                    🟡 Exit
                </button>
            </div>
        </div>
        <!-- Student 2 -->
        <div class="student-row">
            <div class="student-info">
                <strong>Student 2</strong> <span class="badge-id">person_02</span>
            </div>
            <div class="btn-pair">
                <button type="button" class="btn-action entry" onclick="sendTransit('person_02', 'ENTRY')">
                    🟢 Enter
                </button>
                <button type="button" class="btn-action exit" onclick="sendTransit('person_02', 'EXIT')">
                    🟡 Exit
                </button>
            </div>
        </div>
        <!-- Student 3 -->
        <div class="student-row">
            <div class="student-info">
                <strong>Student 3</strong> <span class="badge-id">person_03</span>
            </div>
            <div class="btn-pair">
                <button type="button" class="btn-action entry" onclick="sendTransit('person_03', 'ENTRY')">
                    🟢 Enter
                </button>
                <button type="button" class="btn-action exit" onclick="sendTransit('person_03', 'EXIT')">
                    🟡 Exit
                </button>
            </div>
        </div>
        <!-- Student 4 -->
        <div class="student-row">
            <div class="student-info">
                <strong>Student 4</strong> <span class="badge-id">person_04</span>
            </div>
            <div class="btn-pair">
                <button type="button" class="btn-action entry" onclick="sendTransit('person_04', 'ENTRY')">
                    🟢 Enter
                </button>
                <button type="button" class="btn-action exit" onclick="sendTransit('person_04', 'EXIT')">
                    🟡 Exit
                </button>
            </div>
        </div>
    </div>
    <div id="toastMsg" class="toast-msg"></div>
</div>
```

#### Backend Response Handling in `_handle_transit`
In `webrtc_receiver.py` (lines 787–832):
Currently calls `self.event_dispatcher.dispatch(event_payload)`. Since `dispatch()` suppresses exceptions when outbox is disabled, it can mask backend HTTP errors.
Recommended update:
```python
if self.event_dispatcher is not None:
    result = self.event_dispatcher.send_event(event_payload, sync=True, raise_on_failure=False)
    status_code = result.get("status")
    if status_code in ("accepted", "duplicate"):
        return web.json_response({
            "status": "success",
            "event_id": event_payload["event_id"],
            "identity": identity,
            "direction": direction,
            "message": f"Recorded {direction} for {identity}",
        })
    else:
        return web.json_response({
            "error": result.get("message", "Failed to ingest event into backend")
        }, status=502)
```
This ensures the mobile operator receives immediate, truthful feedback via the toast UI.

---

### 3.7 End-to-End Event Dispatch Trace to Backend

#### 1. Ingestion Endpoint
- **URL**: `POST http://127.0.0.1:8000/api/v1/events` (configured via `--backend-url` or `BACKEND_URL`).
- **HTTP Method**: `POST`
- **Request Headers**:
  - `Content-Type: application/json`
  - `X-API-Key: <VISION_SERVICE_API_KEY>` (e.g. `test_vision_api_key_for_smoke_test_12345`)

#### 2. Payload Structure (`VisionEventCreate`)
```json
{
  "event_id": "evt_b8c9d0e1f2a34b5c",
  "camera_id": "CAM_ROOM_101_DOOR",
  "track_id": 105,
  "identity": "person_01",
  "direction": "ENTRY",
  "timestamp": "2026-10-03T10:15:30.123456+00:00",
  "evidence": {
    "peak_similarity": 0.8452,
    "mean_similarity": 0.8120,
    "supporting_frames": 2,
    "total_frames": 2,
    "consistency_pct": 100.0,
    "margin_over_runner_up": null,
    "runner_up_identity": null
  }
}
```

#### 3. Backend Ingestion & Routing Logic (`backend/app/api/routes/events.py`)
1. **Authentication (`require_camera_auth`)**:
   Checks `X-API-Key` header against `settings.VISION_SERVICE_API_KEY`. Master key grants full access to all cameras.
2. **Camera ID Binding Validation (`validate_camera_binding`)**:
   Verifies `CAM_ROOM_101_DOOR` is authorized.
3. **Timestamp Window Verification**:
   Ensures timestamp is within $[ \text{now} - 86400\,\text{s}, \text{now} + 30\,\text{s} ]$.
4. **Idempotency Guard**:
   Queries `events` collection for `{"event_id": event.event_id}`. Returns HTTP 200 with `status: "duplicate"` if already processed.
5. **Classroom Resolution (`resolve_classroom_for_camera_db`)**:
   Looks up `CAM_ROOM_101_DOOR` in `cameras` collection.
   Returns `classroom_id = "ROOM_101"` (also supported by static fallback registry).
6. **Active Session Resolution (`find_active_session_for_classroom`)**:
   Queries MongoDB `sessions` collection:
   ```python
   {
       "classroom_id": "ROOM_101",
       "start_time": {"$lte": event.timestamp},
       "end_time": {"$gte": event.timestamp},
       "status": {"$in": ["SCHEDULED", "LIVE", "IN_PROGRESS"]}
   }
   ```
   Matches active session `sess_demo_cs101`!
7. **Storage in MongoDB**:
   Enriches document with:
   - `classroom_id: "ROOM_101"`
   - `session_id: "sess_demo_cs101"`
   - `created_at: <current_utc_timestamp>`
   Inserts into `events` collection.
8. **HTTP Response**:
   Returns HTTP 201 Created:
   ```json
   {
     "event_id": "evt_b8c9d0e1f2a34b5c",
     "status": "accepted",
     "message": "Event successfully ingested",
     "processed_at": "2026-10-03T10:15:30.450123+00:00"
   }
   ```

#### 4. Live Snapshot Impact
When Teacher Dashboard polls `GET /api/v1/sessions/sess_demo_cs101/live-snapshot`:
- `compute_session_live_snapshot` pulls all events for `sess_demo_cs101`.
- Groups by student identity (`person_01`).
- Chronologically orders events:
  - If last event is `ENTRY` $\rightarrow$ sets `state: "INSIDE"`.
  - Computes active dwell time from `entry_timestamp` to `now`.
  - Frontend renders `🟢 IN ROOM` badge with live timer and progress bar.
  - If subsequent event is `EXIT` $\rightarrow$ sets `state: "OUTSIDE"`.
  - Stops timer, fixes total presence duration, and frontend renders `🟡 EXITED` badge.

---

## 4. Proposed Code Modifications

### 4.1 `vision-service/pipeline/live_cv_pipeline.py`

#### Modify Default Boundary Line (around line 943):
```python
<<<<
                else:
                    bp1 = (0.0, orig_h * 0.5)
                    bp2 = (float(orig_w), orig_h * 0.5)
====
                else:
                    # Default to vertical dividing line across center of frame (x = 0.5 * orig_w)
                    bp1 = (orig_w * 0.5, 0.0)
                    bp2 = (orig_w * 0.5, float(orig_h))
>>>>
```

#### Make `min_supporting_frames` configurable via environment variable (around line 660):
```python
<<<<
        self.min_supporting_frames = min_supporting_frames
====
        if min_supporting_frames is None:
            env_frames = os.getenv("MIN_SUPPORTING_FRAMES")
            min_supporting_frames = int(env_frames) if env_frames else 2
        self.min_supporting_frames = min_supporting_frames
>>>>
```

---

### 4.2 `vision-service/run_webrtc_camera.py`

#### Add CLI Arguments (around line 105):
```python
    parser.add_argument(
        "--min-supporting-frames",
        type=int,
        default=int(os.getenv("MIN_SUPPORTING_FRAMES", "1")),
        help="Consecutive recognition frames required to confirm identity (default: 1)",
    )
    parser.add_argument(
        "--entry-side",
        choices=["SIDE_A", "SIDE_B"],
        default=os.getenv("ENTRY_SIDE", "SIDE_A"),
        help="Approach side for entry (default: SIDE_A)",
    )
```

#### Pass Parameters to `LiveCVPipeline` (around line 213):
```python
<<<<
            pipeline = LiveCVPipeline(
                app=app,
                gallery=gallery,
                similarity_threshold=args.similarity_threshold,
                min_margin=args.min_margin,
                min_supporting_frames=2,
                source_id=args.source_id,
                camera_id=args.camera_id or args.source_id,
                event_dispatcher=dispatcher,
                enable_kinematic_anti_spoof=args.kinematic_anti_spoof,
                kinematic_spoof_policy=args.kinematic_policy,
            )
====
            pipeline = LiveCVPipeline(
                app=app,
                gallery=gallery,
                similarity_threshold=args.similarity_threshold,
                min_margin=args.min_margin,
                min_supporting_frames=args.min_supporting_frames,
                source_id=args.source_id,
                camera_id=args.camera_id or args.source_id,
                boundary_line=((0.5, 0.0), (0.5, 1.0)),
                entry_side=args.entry_side,
                event_dispatcher=dispatcher,
                enable_kinematic_anti_spoof=args.kinematic_anti_spoof,
                kinematic_spoof_policy=args.kinematic_policy,
            )
>>>>
```

---

### 4.3 `vision-service/camera/webrtc_receiver.py`

1. Update `HTML_PHONE_CLIENT` CSS to make `.doorway-hud-line` vertical (`left: 50%; top: 0; bottom: 0; width: 2px`).
2. Add `.doorway-side-guide.side-a` ("Side A (Entry ➔)") and `.doorway-side-guide.side-b` ("(➔ Side B) In Room").
3. Update `.quick-actions-card` to display the 4 demo students (`person_01` through `person_04`) with Enter/Exit buttons.
4. Update `_handle_transit` to invoke `send_event(..., sync=True)` and return HTTP 200 on success or HTTP 502 on backend error.

---

### 4.4 `scripts/seed_clean_demo.py`

Update `boundary_config` in `CAMERA_ID` setup (line 344) to vertical:
```python
"boundary_config": {
    "p1": [0.5, 0.0],
    "p2": [0.5, 1.0],
    "entry_side": "SIDE_A",
    "deadband_pixels": 4.0,
}
```
And ensure session ID created is explicitly `sess_demo_cs101` (matching Requirement R1.6).

---

## 5. Verification & Testing Method

### 5.1 Unit Tests for Spatial Geometry & Rapid Gating
Run existing pipeline unit tests:
```powershell
pytest vision-service/tests/test_cv_event_pipeline.py -v
pytest vision-service/tests/test_kinematic_anti_spoof.py -v
```

### 5.2 Verification Script for Dispatch & Live Snapshot
Test dispatching events and checking live snapshot:
```powershell
# 1. Start backend
# 2. POST an ENTRY event for person_01
$headers = @{ "Content-Type" = "application/json"; "X-API-Key" = "test_vision_api_key_for_smoke_test_12345" }
$body = @{
    event_id = "test_evt_001"
    camera_id = "CAM_ROOM_101_DOOR"
    track_id = 1
    identity = "person_01"
    direction = "ENTRY"
    timestamp = [DateTime]::UtcNow.ToString("o")
    evidence = @{
        peak_similarity = 0.95
        mean_similarity = 0.92
        supporting_frames = 2
        total_frames = 2
        consistency_pct = 100.0
    }
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/events" -Method Post -Headers $headers -Body $body
```
Query live snapshot:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/sessions/sess_demo_cs101/live-snapshot" -Method Get -Headers @{ "Authorization" = "Bearer <TEACHER_TOKEN>" }
```
Assert that `person_01` has `state: "INSIDE"`.

---

## 6. Conclusion

All 8 focus items of Requirement R2 have been surveyed in complete detail. The code changes required are localized, well-understood, and safe to implement without breaking existing features. The implementer agent can directly use the findings and code snippets in this report to execute the changes.
