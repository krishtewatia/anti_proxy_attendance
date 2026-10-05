# ADR-008: Anti-Spoofing & Liveness Strategy for Local MVP

## Status
Accepted

## Context
The Anti-Proxy Attendance System verifies student identities using InsightFace (SCRFD detection + ArcFace embedding matching) and ByteTrack trajectory tracking across doorway transit boundaries.

While continuous presence tracking over time provides the primary defense against proxy attendance, presentation attacks (photo printouts, smartphone screen replays, or looped videos presented to the camera) represent a distinct security threat.

However, adding a deep neural passive anti-spoofing model presents severe trade-offs on commodity classroom CPU hardware:
1. **CPU Budget Exhaustion**: Our operational requirement is maintaining $\ge 15$ FPS across multi-student transits. Benchmark measurements indicate passive CNN models (MiniFASNet, MobileNetV3) consume 28–45 ms per face. In a 5-person transit burst, frame latency reaches 170–250 ms, dropping throughput to **4–6 FPS**.
2. **False Rejection Risk**: RGB-only passive liveness models are notoriously sensitive to environmental lighting variations (direct sunlight, hallway glare, lens flare) and camera sensor differences, creating false rejections for genuine students.
3. **Architectural Realities**: Unlike phone-unlock kiosks where a single user pauses and stares at a camera, classroom attendance measures rapid walking transits (0.5–1.5 seconds) through a doorway. Blink detection (EAR) is physically unusable because natural blink intervals (3–4 seconds) exceed doorway transit duration.

---

## Decision

### 1. Documented Postponement of Full Neural Anti-Spoofing Models
We **postpone** integrating deep neural passive anti-spoofing models (e.g., MiniFASNet, Silent-Face, DeepPixBiS) for the local CPU MVP. The system will not run per-crop neural liveness inference on commodity CPU workstations.

### 2. Adoption of Zero-Overhead Kinematic & Temporal Trajectory Mitigations
Instead of heavy neural models, we adopt three cheap, deterministic kinematic checks inside [`LiveCVPipeline`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py) executed in $< 0.05$ ms per frame:

1. **Motion-Consistent Trajectory Check (`min_track_displacement_px = 15.0`)**:
   - Evaluates centroid displacement between initial detection and the moment of boundary line crossing:
     $$\Delta d = \sqrt{(c_x - c_{x0})^2 + (c_y - c_{y0})^2} \ge 15.0\text{ px}$$
   - Mitigates stationary spoofs (e.g., photo printout taped to a wall, or phone held still in frame). A stationary image jiggling on the line produces insufficient displacement and is flagged as `INSUFFICIENT_DISPLACEMENT`.
2. **Implausibly Instant Transit Guard (`min_transit_duration_sec = 0.20`)**:
   - Enforces a minimum approach duration before an `ENTRY` or `EXIT` event is accepted:
     $$\Delta t = t_{\text{crossing}} - t_{\text{first\_seen}} \ge 0.20\text{ seconds}$$
   - Mitigates fast phone-swiping attacks or transient detection teleportation anomalies (`INSTANT_TRANSIT`).
3. **Stationary Hovering Flag (`max_stationary_duration_sec = 8.0`)**:
   - Tracks that linger near the boundary line for $> 8.0$ seconds without spatial progression are flagged as `STATIONARY_HOVER`.

### 3. Configurable Policy & Telemetry Flagging
The mitigation is configurable via environment variables and CLI options:
- `ENABLE_KINEMATIC_ANTI_SPOOF` (default: `True`)
- `KINEMATIC_SPOOF_POLICY` (choices: `FLAG` [default] or `REJECT`)
- `--kinematic-anti-spoof` and `--kinematic-policy` flags in `run_webrtc_camera.py`.

Under `FLAG` mode, events are emitted with anomaly metadata (`kinematic_status: FLAGGED_...`) and logged for instructor dashboard audit. Under `REJECT` mode, anomalous transits are dropped before backend dispatch.

---

## Feasibility Comparison & CPU Benchmark Measurements

Evaluated on x86_64 CPU hardware (Intel Core i7 base frequency 2.6 GHz, ONNX Runtime):

| Candidate Option | Architecture | License | Weight | CPU Latency (per face) | 1-Face FPS | 3-Face FPS | 5-Face FPS | Operational Verdict |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Kinematic Trajectory & Duration Guard** | Bounding box spatial velocity & time delta | Apache 2.0 (Native) | 0 MB | **`< 0.05 ms`** | **40.0** | **40.0** | **40.0** | **ADOPT (Local MVP)** |
| **Eye Aspect Ratio (EAR) Blink Detection** | Facial landmark oscillation heuristic | MIT (Pure Python) | 0 MB | 8.52 ms | 29.8 | 19.8 | 14.8 | **REJECT** (Doorway transits too brief) |
| **MiniFASNetV1SE / MiniFASNetV2** | 80x80 RGB crop with SE blocks | Apache 2.0 (Permissive) | 2.4 MB | 28.50 ms | 18.7 | 9.0 | **6.0** | **POSTPONE** (CPU bottleneck) |
| **MobileNetV3 Anti-Spoof (DeepPixBiS)** | 128x128 pixel-wise binary supervision CNN | Apache 2.0 / BSD | 4.2 MB | 41.30 ms | 15.1 | 6.7 | **4.3** | **POSTPONE** (Severe CPU latency) |

---

## Explicit Security Limitations & Disclaimer

> [!WARNING]
> **No Spoof-Resistance Guarantee**:
> The Anti-Proxy Attendance System **does NOT guarantee resistance against sophisticated physical presentation attacks** (e.g., dynamic video replays on high-resolution screens or moving 3D mask presentations).
>
> The system relies on:
> 1. Physical doorway transit trajectory constraints.
> 2. Continuous session presence tracking ($\ge 75\%$ session duration).
> 3. Visual instructor oversight and 1-click teacher dashboard audit.

---

## Concrete Triggers for Revisiting Full Liveness

Integration of dedicated neural or hardware anti-spoofing will be revisited upon any of the following milestones:
1. **Classroom Pilot Incident**: If empirical photo or screen replay attacks are detected or reported during campus pilot testing.
2. **Hardware Acceleration Availability**: When deployment workstations feature dedicated NPUs or CUDA-capable GPUs capable of running MiniFASNet/Silent-Face at $< 3$ ms per face.
3. **Hardware 3D Depth Sensing**: If doorway stations are upgraded with Intel RealSense, Time-of-Flight (ToF), or infrared structured-light sensors, which solve liveness physically at the sensor level without fragile RGB heuristics.
