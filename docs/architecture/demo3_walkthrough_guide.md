# Demo 3: Live Attendance Dashboard & System Status Runbook

## Overview
Demo 3 demonstrates real-time optical attendance tracking in a browser-based dashboard. A teacher starts a classroom session, connects a camera (WebRTC phone camera or RTSP stream), students transit across the boundary into and out of the classroom, and the live dashboard updates automatically without manual page reloading.

---

## 1. Transport Architectural Decision: Polling vs. SSE

### Chosen Approach: Short-Interval Polling (3.5s with Exponential Backoff & Page Visibility)

### Decision Rationale:
1. **Stateless Resiliency**: Real-time optical presence calculation requires merging continuous time ($t_{\text{now}} - t_{\text{entry}}$) with discrete boundary events. A snapshot endpoint calculates exact interval bounds, camera telemetry, and active presence deterministically on every fetch.
2. **Resource Efficiency (Page Visibility API)**: By hooking `document.visibilityState`, polling automatically pauses whenever the browser tab is minimized or hidden. When the teacher returns to the tab, an immediate fetch is triggered.
3. **Fault Tolerance & Auto-Backoff**: In the event of network jitter, server reloads, or proxy latency, polling automatically backs off exponentially (3.5s $\to$ 5.2s $\to$ 7.8s $\to \dots \to$ 30s) instead of maintaining brittle, half-open TCP socket state common with Server-Sent Events (SSE) or WebSockets.
4. **Auto-Termination**: When session state transitions to `COMPLETED` / `ENDED`, auto-polling halts automatically, saving network bandwidth and CPU cycles.

---

## 2. Step-by-Step Demo 3 Procedure

### Step 1: Start the Backend Stack
Ensure MongoDB is running locally on port 27017, then launch FastAPI:
```powershell
# From repository root
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 2: Start the Frontend Application
```powershell
# In a separate terminal
cd frontend
npm run dev
```
Open your browser to `http://localhost:5173`.

### Step 3: Login as Teacher & Create an Attendance Session
1. Navigate to the Teacher Login page and authenticate (e.g., `teacher1@school.edu` / `pass123`).
2. On the **Teacher Dashboard**, click **"Create Session"**.
3. Configure the session parameters:
   - **Course Name**: `CS401: Cloud Computing`
   - **Classroom**: `ROOM_101`
   - **Start Time**: Current time (or 5 minutes earlier)
   - **End Time**: 1 hour in the future
   - **Required Presence**: `75%`
4. Click **"Save Session"** and open the newly created session's **Session Details** page.
5. In the **Student Roster Management** card, enroll students:
   - `person_01`, `person_02`, `person_04`.

### Step 4: Connect the Camera Feed (WebRTC Phone or RTSP Stream)
Start the camera ingest worker:
```powershell
# WebRTC Phone Camera Option:
cd vision-service
.\.venv\Scripts\Activate.ps1
python run_webrtc_camera.py --classroom ROOM_101 --camera-id CAM_ROOM_101_PHONE

# Or Local RTSP CCTV Simulation Option:
python tools/publish_local_rtsp.py --video-path clips/classroom_door.mp4 --stream-path cam_room101
```

### Step 5: Observe Real-Time Dashboard Updates
On the **Session Details** page, observe the **Live Attendance & Presence Feed** panel:
1. **Camera Health Strip**:
   - The status pill displays `CAM_ROOM_101_PHONE` in glowing emerald: `CONNECTED`, `15.0 FPS`, heartbeat updated `< 3s ago`.
2. **Student Live Badges**:
   - Initial state: `person_01`, `person_02`, `person_04` display `NOT SEEN` with `0s` presence.
3. **Student Ingress (ENTRY)**:
   - When `person_01` crosses into the room, their badge immediately transitions to **`INSIDE`** with a glowing green dot.
   - Accumulated presence begins counting up in real-time (`1m 12s`, `1m 16s`, etc.).
   - An **`IN ROOM`** observability tag is applied.
   - The **Recent Optical Transit Events** ticker logs: `ENTRY • person_01 • 96% conf • Just now`.
4. **Student Egress (EXIT)**:
   - When `person_01` exits the room, their badge transitions to **`OUTSIDE`** (amber).
   - Presence duration locks to the accumulated duration of the visit.
   - If accumulated duration exceeds required percentage (or remains on track), projected status displays `PRESENT` or `ON TRACK`.
5. **Camera Disconnect / Stale Warning**:
   - If the camera stream is stopped or connection drops for $> 15$ seconds, a prominent amber/red alert banner appears:
     > *"Camera telemetry offline or stale. Vision service heartbeats have not been received in the last 15 seconds."*
   - Camera pill transitions to `STALE` with elapsed heartbeat age.
6. **Session Finalization**:
   - Click **"Finalize Attendance"** in the Attendance card.
   - The Live Feed automatically transitions badge to **`Session Ended`** and halts auto-polling.
   - Final official records and manual correction tools are displayed below.

---

## 3. Security & Isolation Guarantees
- **Teacher Ownership Isolation**: `GET /api/v1/sessions/{id}/live-snapshot` enforces strict ownership via `get_owned_session`. Requests from other teachers immediately fail with `403 Forbidden`.
- **Zero Raw Media Exposure**: No video frames, face crops, or biometric embeddings are transmitted or stored in FastAPI. Payloads strictly contain aggregated numerical durations, student identities, and optical transit directions.
