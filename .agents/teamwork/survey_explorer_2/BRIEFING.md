# BRIEFING — 2026-10-03T10:20:00Z

## Mission
Investigate Requirement R2: Reliable Real-Time Mobile Detection & Event Dispatch Pipeline for WebRTC mobile camera demo.

## 🔒 My Identity
- Archetype: explorer
- Roles: survey, codebase investigation, architectural synthesis
- Working directory: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_2
- Original parent: 992bab0c-c8bc-4ae6-9c50-07f56d0d064a
- Milestone: Requirement R2 Survey & Plan

## 🔒 Key Constraints
- Read-only investigation — do NOT implement
- Scope: R2 (webrtc_receiver, live_cv_pipeline, run_webrtc_camera, boundary line crossing, min_supporting_frames, kinematic_spoof_policy, mobile WebRTC client/server, manual transit buttons, backend event dispatch)
- Output findings to `report.md` and `handoff.md`
- Send completion message to parent orchestrator

## Current Parent
- Conversation ID: 992bab0c-c8bc-4ae6-9c50-07f56d0d064a
- Updated: not yet

## Investigation State
- **Explored paths**:
  - `vision-service/camera/webrtc_receiver.py`
  - `vision-service/pipeline/live_cv_pipeline.py`
  - `vision-service/run_webrtc_camera.py`
  - `vision-service/events/event_dispatcher.py`
  - `backend/app/api/routes/events.py`
  - `backend/app/services/session_resolution_service.py`
  - `backend/app/services/live_session_service.py`
  - `backend/app/schemas/vision_event.py`
  - `backend/app/schemas/camera.py`
  - `scripts/seed_clean_demo.py`
- **Key findings**:
  1. Default boundary line in `live_cv_pipeline.py` currently falls back to horizontal (`orig_h * 0.5`). Must be updated to vertical dividing line (`x = 0.5 * orig_w` or normalized `((0.5, 0.0), (0.5, 1.0))`). `classify_point_side` already supports vertical lines: `cx < line_x - deadband` is SIDE_A, `cx > line_x + deadband` is SIDE_B. With `entry_side == "SIDE_A"`, left-to-right is ENTRY and right-to-left is EXIT.
  2. `min_supporting_frames` is hardcoded to 2 in `run_webrtc_camera.py` and defaults to 3 in `live_cv_pipeline.py`. Rapid transit gating also checks `min_transit_duration_sec` and `min_track_displacement_px`. Reducing `min_supporting_frames` to 1 or 2 confirms identity immediately on first detection.
  3. `kinematic_spoof_policy` is configured via CLI/env and evaluated in `process_frame`. Policy `REJECT` drops events; policy `FLAG` logs warning with telemetry anomalies attached and still emits the event. Setting policy to `FLAG` prevents drops during rapid transit or mobile jitter.
  4. `HTML_PHONE_CLIENT` in `webrtc_receiver.py` renders mobile WebRTC camera UI served on port 8088. HUD overlay has horizontal CSS line (`top: 50%; height: 2px`). Needs vertical CSS line (`left: 50%; width: 2px; height: 100%`) plus directional guides.
  5. Mobile manual quick action buttons currently hardcode `person_01`, `student_alice`, `student_bob`. Needs buttons for the 4 demo students (`person_01` through `person_04`).
  6. Event dispatch flow from vision service to backend verified end-to-end: `EventDispatcher` POSTs `VisionEventCreate` to `POST /api/v1/events` with header `X-API-Key`. Backend resolves `CAM_ROOM_101_DOOR` -> `ROOM_101` -> `sess_demo_cs101` and persists document into MongoDB `events`.
- **Unexplored areas**: None. All 8 focus items completely investigated.

## Key Decisions Made
- Prepare comprehensive code snippets (before/after) in `report.md` for the implementer agent.

## Artifact Index
- DISPATCH.md — Initial dispatch instructions
- BRIEFING.md — Persistent context & memory
- progress.md — Liveness heartbeat
- report.md — Comprehensive findings for R2
- handoff.md — 5-component handoff report
