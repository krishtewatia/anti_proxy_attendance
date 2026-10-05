# Handoff Report — Requirement R2: Reliable Real-Time Mobile Detection & Event Dispatch Pipeline

**Author**: Survey Explorer 2 (`teamwork_preview_explorer`)
**Target**: Orchestrator / Implementer Agent
**Date**: 2026-10-03
**Status**: Task Complete (Hard Handoff)

---

## 1. Observation

1. **Horizontal Line Default**:
   In `vision-service/pipeline/live_cv_pipeline.py` (lines 943–946):
   ```python
   else:
       bp1 = (0.0, orig_h * 0.5)
       bp2 = (float(orig_w), orig_h * 0.5)
   ```
   When `boundary_line` is not explicitly passed to `LiveCVPipeline`, the boundary line defaults to a horizontal line across the middle of the frame.
   In `vision-service/run_webrtc_camera.py` (lines 213–224), `LiveCVPipeline` is instantiated without passing `boundary_line`.

2. **Vertical Boundary Geometry Support**:
   In `vision-service/pipeline/live_cv_pipeline.py` (lines 63–70):
   ```python
   else:
       # Vertical boundary line
       line_x = x1
       if cx < line_x - deadband:
           return "SIDE_A"
       elif cx > line_x + deadband:
           return "SIDE_B"
       else:
           return "ON_LINE"
   ```
   `classify_point_side` already has native support for vertical boundary lines when `abs(x2 - x1) <= 1e-5`. For $x_1 = x_2 = 0.5 \cdot \text{width}$, points with $cx < 0.5 \cdot \text{width} - \text{deadband}$ evaluate to `SIDE_A` (Left) and $cx > 0.5 \cdot \text{width} + \text{deadband}$ evaluate to `SIDE_B` (Right).
   In lines 409–419, `TrackEvidence.update_boundary_position` maps `SIDE_A -> SIDE_B` to `ENTRY` and `SIDE_B -> SIDE_A` to `EXIT` when `entry_side == "SIDE_A"`.

3. **Gating and Supporting Frames Logic**:
   In `vision-service/pipeline/live_cv_pipeline.py`:
   - Line 333: `if vote_count >= min_supporting_frames:` sets `self.is_confirmed = True`.
   - Lines 477–480: `if not self.is_confirmed: return []` blocks event emission until confirmed.
   - Line 660: `min_supporting_frames` defaults to `3`.
   In `vision-service/run_webrtc_camera.py`:
   - Line 218: `min_supporting_frames=2` is hardcoded. No CLI argument exists to configure it.
   - Lines 447–448 in `live_cv_pipeline.py`: `if self.transit_duration_sec < min_transit_duration_sec: anomalies.append("INSTANT_TRANSIT")` (default threshold: 0.20s).

4. **Kinematic Anti-Spoof Policy**:
   In `vision-service/pipeline/live_cv_pipeline.py` (lines 1002–1025):
   ```python
   if self.enable_kinematic_anti_spoof and evidence.kinematic_anomalies:
       if self.kinematic_spoof_policy == "REJECT":
           ...
           if direction in evidence.pending_directions:
               evidence.pending_directions.remove(direction)
           continue
       else:
           logger.warning(
               "Kinematic anti-spoof FLAGGED transit event for track %d (%s): %s ...",
               ...
           )
   ```
   Under `REJECT`, any anomaly (such as instant transit or small displacement) causes the event to be dropped. Under `FLAG`, a warning is logged, anomaly metadata is preserved in the event dictionary, and the event is emitted.
   In `run_webrtc_camera.py` (lines 111–115), `--kinematic-policy` defaults to `FLAG`.

5. **Mobile WebRTC Interface & Overlay**:
   In `vision-service/camera/webrtc_receiver.py`:
   - Line 709: `WebRTCSignalingServer` binds to port 8088.
   - Lines 181–210: CSS `.doorway-hud-line` has `top: 50%; height: 2px` (horizontal orientation).
   - Lines 383–395: Manual trigger buttons hardcode `person_01`, `student_alice`, and `student_bob`.
   - Lines 815: `_handle_transit` calls `self.event_dispatcher.dispatch(event_payload)`.

6. **Event Dispatch to Backend**:
   - `vision-service/events/event_dispatcher.py` (line 18): `EVENT_ENDPOINT = "/api/v1/events"`. Headers include `X-API-Key: <api_key>`.
   - `backend/app/api/routes/events.py` (lines 43, 56, 107, 109): Validates `X-API-Key` via `require_camera_auth`, checks `validate_camera_binding`, resolves classroom via `resolve_classroom_for_camera_db("CAM_ROOM_101_DOOR") -> "ROOM_101"`, and resolves active session via `find_active_session_for_classroom("ROOM_101", timestamp)`.

---

## 2. Logic Chain

1. **Boundary Alignment**:
   - From Observation 1, `LiveCVPipeline` defaults to a horizontal line across the middle of the screen when no boundary is given.
   - From Observation 2, `classify_point_side` and `update_boundary_position` already contain complete logic for vertical lines and left-to-right (`SIDE_A -> SIDE_B = ENTRY`) / right-to-left (`SIDE_B -> SIDE_A = EXIT`) detection.
   - Therefore, updating the fallback line in `live_cv_pipeline.py` to `bp1 = (orig_w * 0.5, 0.0), bp2 = (orig_w * 0.5, float(orig_h))` and passing `boundary_line=((0.5, 0.0), (0.5, 1.0))` from `run_webrtc_camera.py` will guarantee the vertical line behavior required by R2.1 without altering the underlying geometric classifier.

2. **Rapid Doorway Crossing Guarantee**:
   - From Observation 3, unconfirmed tracks cannot emit events (`get_emittable_directions()` returns empty), and confirmation requires `vote_count >= min_supporting_frames`.
   - Doorway transits across a smartphone camera held at a doorway often only capture 1 or 2 clean face frames before the person crosses the threshold.
   - Therefore, adding `--min-supporting-frames` (defaulting to 1 or 2) in `run_webrtc_camera.py` ensures that a single high-confidence detection immediately confirms identity, preventing missed transit events.
   - Furthermore, from Observation 4, rapid movement triggers `INSTANT_TRANSIT` if duration is under 0.20s. Under policy `REJECT`, such transits are dropped. Setting `kinematic_spoof_policy = "FLAG"` guarantees legitimate fast transits are emitted while logging the anomaly for audit purposes.

3. **Mobile User Experience & Fallback**:
   - From Observation 5, the phone client on port 8088 renders a horizontal HUD line and synthetic users (Alice, Bob) that are scheduled for deletion under Requirement R1.
   - Updating the HUD CSS in `HTML_PHONE_CLIENT` to vertical (`left: 50%; width: 2px; height: 100%`) visually aligns the operator's view with the backend's CV boundary.
   - Replacing the quick-action buttons with the 4 demo students (`person_01` through `person_04`) provides an operational fallback allowing immediate transit logging even if the camera lighting or angle is degraded.

4. **Session Binding Integrity**:
   - From Observation 6, events sent with `camera_id="CAM_ROOM_101_DOOR"` query MongoDB for the active session in `ROOM_101`.
   - Seeding `CAM_ROOM_101_DOOR` in `ROOM_101` and active session `sess_demo_cs101` ensures all vision events (both automated CV and manual mobile triggers) associate with `sess_demo_cs101` and update live attendance state on `GET /api/v1/sessions/sess_demo_cs101/live-snapshot`.

---

## 3. Caveats

1. **Resolution & Orientation Scaling**: When streaming via WebRTC from mobile devices, orientation can be portrait (720x1280) or landscape (1280x720). Normalized coordinates `((0.5, 0.0), (0.5, 1.0))` properly scale regardless of resolution and orientation.
2. **Device Performance**: On low-end host machines without a GPU, running SCRFD detection and ByteTrack at native 30 fps can incur frame buffering. `PhoneVideoSource`'s drop-oldest queue policy drops stale frames to ensure live tracking latency remains low.
3. **No other caveats.**

---

## 4. Conclusion

Requirement R2 is fully analyzed and ready for implementation.
The required changes are localized to:
- `vision-service/pipeline/live_cv_pipeline.py`: Change default boundary to vertical centerline (`x = 0.5 * width`).
- `vision-service/run_webrtc_camera.py`: Add `--min-supporting-frames` (default 1) and `--entry-side` (default `SIDE_A`), passing `boundary_line=((0.5, 0.0), (0.5, 1.0))` to `LiveCVPipeline`.
- `vision-service/camera/webrtc_receiver.py`: Update `HTML_PHONE_CLIENT` HUD overlay to vertical guide line with Side A/Side B labels; update quick-action buttons to `person_01` through `person_04`; update `_handle_transit` to check `send_event` status.
- `scripts/seed_clean_demo.py`: Ensure camera `CAM_ROOM_101_DOOR` has `boundary_config` with `p1: [0.5, 0.0]`, `p2: [0.5, 1.0]`, `entry_side: "SIDE_A"`.

Detailed code changes and architecture are documented in `report.md`.

---

## 5. Verification Method

1. **Unit Testing**:
   Run the boundary geometry and anti-spoof tests:
   ```powershell
   pytest vision-service/tests/test_cv_event_pipeline.py -v
   pytest vision-service/tests/test_kinematic_anti_spoof.py -v
   ```
2. **File Inspection**:
   Inspect `vision-service/pipeline/live_cv_pipeline.py` line 943 to verify fallback boundary line is `(orig_w * 0.5, 0.0)` to `(orig_w * 0.5, float(orig_h))`.
   Inspect `vision-service/camera/webrtc_receiver.py` to verify `.doorway-hud-line` CSS is `left: 50%; width: 2px` and manual buttons reflect `person_01` through `person_04`.
3. **End-to-End Event Dispatch Verification**:
   Send an event via PowerShell to `http://127.0.0.1:8000/api/v1/events` and query `http://127.0.0.1:8000/api/v1/sessions/sess_demo_cs101/live-snapshot` to verify student state transitions to `INSIDE` / `IN ROOM`.
4. **Invalidation Condition**:
   If crossing left-to-right triggers `EXIT` instead of `ENTRY`, check `entry_side` configuration (must be `"SIDE_A"`).
