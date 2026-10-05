# ADR-009: Camera Registry, Multi-Camera Orchestration, and RTSP Ingestion Architecture

## Status
Accepted

## Context
In Step 2E.8, the Anti-Proxy Attendance System requires a production-grade camera management foundation:
1. The backend previously relied on static camera mappings (`CAM_ROOM_101_DOOR -> ROOM_101`). A dynamic, RBAC-protected, and audited Camera Registry is required for managing cameras, classrooms, source types, directional roles, and virtual boundaries.
2. IP and CCTV physical cameras stream video frames via RTSP. Raw RTSP URLs frequently embed sensitive authentication credentials (`rtsp://user:password@host:port/path`). These secrets must never leak into responses, audit logs, or error dumps.
3. Multi-camera deployments require independent per-camera pipelines where cameras may serve specialized directional roles:
   - `ENTRY`: Only permits ingress transits into a classroom; drops reverse egress transits.
   - `EXIT`: Only permits egress transits out of a classroom; drops reverse ingress transits.
   - `BOTH`: Standard bidirectional boundary line.
4. Physical network streaming introduces socket latency, buffer bloat, and transient connection drops. A naive synchronous frame consumer creates multi-second latency buildup or crashes when cameras restart.
5. Operators need live operational visibility (FPS, connection state `CONNECTED`/`DEGRADED`/`DISCONNECTED`, frame drops, last seen) without sending raw video frames to FastAPI.
6. Local development requires zero-hardware simulation capabilities with verified stream recovery upon restart.

## Decision

### 1. Backend Camera Registry & Credential Masking
- Introduced `cameras` MongoDB collection with unique index on `camera_id`.
- Model schema: `camera_id`, `classroom_id`, `role` (`ENTRY`, `EXIT`, `BOTH`), `source_type` (`RTSP`, `WEBRTC`, `PHONE`, `FILE`), `secret_reference`, `enabled`, `boundary_config`, `notes`, `status`, `fps`, `last_seen`.
- **Security Boundary**:
  - Raw `rtsp_url` is stored in the database but stripped from `CameraResponse`.
  - The public representation exposes only `rtsp_url_masked` (`rtsp://user:*****@host:port/path`).
  - Audit logging for `CAMERA_CREATED`, `CAMERA_UPDATED`, `CAMERA_DELETED` explicitly sanitizes credentials prior to writing immutable audit logs.
  - CRUD operations are restricted to `ADMIN` users via `require_admin`.

### 2. Service-Authenticated Operational Health Heartbeat
- Endpoint: `POST /api/v1/cameras/{camera_id}/heartbeat`
- Telemetry: Transmits `state` (`CONNECTED`, `DEGRADED`, `DISCONNECTED`), measured `fps`, and `dropped_frames`.
- **Zero Video Frame Transmission**: Strictly transmits numeric/status telemetry; no frames or images ever touch FastAPI.
- Authentication: Protected by `require_camera_auth` with `validate_camera_binding` enforcement.
- Dashboard query: `GET /api/v1/cameras/{camera_id}/health` and `GET /api/v1/cameras` expose real-time status.

### 3. Decoupled RTSP Video Source & Latest-Frame-Wins Buffer
- Upgraded `RTSPVideoSource` with a dedicated background ingestion thread and bounded queue (`maxsize=2`).
- Drop-oldest semantics (`latest-frame-wins`): When downstream CV inference is busy, obsolete frames in the buffer are discarded, eliminating latency drift.
- Exponential backoff auto-reconnection:
  $$\Delta t = \min(\text{interval} \times \text{factor}^{\text{attempt}}, \text{max\_backoff})$$
- State transitions:
  - `CONNECTED`: Active frame decoding.
  - `DEGRADED`: Packet drops, read timeouts, or reconnection attempts in progress.
  - `DISCONNECTED`: Max retry attempts exhausted or stream released.

### 4. Multi-Camera Orchestration & Directional Role Enforcement
- `LiveCVPipeline` enforces camera roles at the sensory gating boundary:
  - `role="ENTRY"`: Emits `ENTRY` transits; discards reverse `EXIT` trajectories.
  - `role="EXIT"`: Emits `EXIT` transits; discards reverse `ENTRY` trajectories.
  - `role="BOTH"`: Permits bidirectional transits.
- `CameraWorker` encapsulates a dedicated `VideoSource`, `LiveCVPipeline`, and `EventDispatcher` per camera.
- `MultiCameraRunner` manages N concurrent workers, handling configuration parsing, thread lifecycle, and benchmark metrics.

### 5. Local CCTV Simulation & Tool Licensing
- Evaluated external streaming tools:
  - **MediaMTX** (bluenviron/mediamtx): Permissive **MIT License**. High-performance standalone binary or docker image.
  - **FFmpeg**: **LGPL v2.1+ / GPL v2+**. Standard tool for streaming looping MP4 files to MediaMTX via RTSP.
- Created `vision-service/tools/publish_local_rtsp.py` providing automated command generation and validation.

## Consequences

### Positive
- Cameras can be added, updated, and reconfigured dynamically without restarting FastAPI.
- Zero credential leakage across API endpoints, server logs, or audit records.
- Zero latency accumulation on RTSP streams regardless of CV inference duration.
- Multi-camera classroom setups (separate entry and exit doors) merge cleanly into single session attendance records.
- Verified automatic stream recovery after network disruptions or stream restarts.

### Negative & Mitigations
- Multi-camera execution on a single host increases CPU utilization:
  - *Mitigation*: SCRFD-0.5G lightweight detector and track-gated ArcFace ensure 2 cameras process ~20.5 aggregate FPS with per-camera frame rates > 13 FPS on standard CPU.
