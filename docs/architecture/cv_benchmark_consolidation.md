# Computer Vision Prototype Benchmark Consolidation & Decision Record

## Executive Summary
This document consolidates empirical findings from Steps 4.10.1 through 4.10.5 of the Anti-Proxy Attendance project. It establishes the baseline computer vision architecture, quantifies pipeline performance on local CPU hardware, documents critical perception behaviors, and defines the explicit perception-to-backend event contract.

> [!IMPORTANT]
> **Prototype Validation Status:**
> These benchmarks validate **technical feasibility and algorithmic flow**, not production accuracy. Tests were conducted on short video clips with a small identity gallery (4 enrolled identities, 2 moving video subjects). This prototype demonstrates that the vision architecture functions end-to-end, but must be benchmarked on crowded classroom footage before production deployment claims can be made.

---

## 1. End-to-End Prototype Architecture

The validated computer vision pipeline operates as follows:

```
  Video Stream (RTSP / MP4)
              │
              ▼
    OpenCV Frame Sampler (5.0 FPS)
              │
              ▼
 InsightFace Face Detector (SCRFD / Buffalo_L)
       │                              │
       ▼                              ▼
  Bounding Boxes + Det Scores     512-d ArcFace Embeddings
       │                              │
       ▼                              │
   ByteTrack Tracker                  │
   (Kalman Filter + 2-Stage IoU)      │
       │                              │
       ▼                              ▼
    Track ID ◄─────────────► Biometric Gallery Matching
              │
              ▼
   Track-Level Evidence Buffer
   (Accumulated votes, similarities, margins)
              │
              ▼
   Virtual Boundary State Machine
   (Signed-distance line crossing)
              │
              ▼
   Structured Vision Event Emission:
   { track_id, identity, event, timestamp }
```

---

## 2. Benchmark Results by Stage

### Step 4.10.1 — Video Ingestion & Frame Sampling
- **Objective**: Verify OpenCV reliability, sequential frame decoding, resolution/FPS extraction, and controlled 5 FPS sampling.
- **Results**:
  - `person_1_vid.mp4`: 576x1024 @ 29.80 FPS, 146 frames total $\rightarrow$ 25 sampled frames (~5.10 effective FPS).
  - `person_2_vid.mp4`: 576x1024 @ 29.88 FPS, 250 frames total $\rightarrow$ 42 sampled frames (~5.02 effective FPS).
  - 100% sequential frame read success with zero dropped frames or file corruption.

### Step 4.10.2 — Frame-Level Recognition (InsightFace / ArcFace)
- **Objective**: Evaluate raw frame-by-frame ArcFace cosine similarities against the 4-person gallery without tracking.
- **Key Finding**: Cosine similarity fluctuates significantly during motion:
  - Subject 2 (`person_2_vid.mp4`): Similarity curve rose from $0.440 \rightarrow 0.521 \rightarrow 0.608 \rightarrow 0.613$ as the subject approached frontal view, then decreased to $0.535 \rightarrow 0.310$ as they exited.
  - Subject 1 (`person_1_vid.mp4`): Scored between $0.365$ and $0.490$ for `person_01` (all other identities scored $\le 0.0$).
- **Implication**: Applying a strict static single-frame threshold (e.g., $\tau = 0.60$) causes frequent false negatives and flickering UNKNOWN classifications during motion.

### Step 4.10.3 — Multi-Frame Tracking (ByteTrack)
- **Objective**: Maintain persistent Track IDs across frames without external C++ or heavy dependencies.
- **Implementation**: Pure NumPy + SciPy ByteTrack using an 8-state Kalman filter and Hungarian assignment via `scipy.optimize.linear_sum_assignment`.
- **Results**:
  - Video 1: Established **Track 6**, active across 5 consecutive sampled frames (Frames 90 to 114, 0.81s span).
  - Video 2: Established **Track 22**, active across 5 consecutive sampled frames (Frames 216 to 240, 0.80s span).
  - Identified track fragmentation prior to the frontal window due to fast approach and small face bounding box displacement at 5 FPS.

### Step 4.10.4 — Recognition + Tracking Fusion
- **Objective**: Accumulate recognition scores over active tracklets to replace single-frame decisions.
- **Results**:

| Video | Track ID | Top Candidate | Peak Similarity | Mean Similarity | Supporting Frames | Separation Margin |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| `person_1_vid.mp4` | **Track 6** | `person_01` | **0.460** | 0.428 | **5 / 5 (100%)** | **+0.362** |
| `person_2_vid.mp4` | **Track 22** | `person_02` | **0.613** | 0.585 | **5 / 5 (100%)** | **+0.461** |

- **Key Takeaway**: Within both primary tracks, **100% of frames unanimously voted for the correct identity**, with massive separation margins ($+0.362$ and $+0.461$) above the closest runner-up gallery identity. Track aggregation successfully resolved identities that failed fixed single-frame thresholds.

### Step 4.10.5 — Directionality & Boundary Crossing
- **Objective**: Detect directional line crossing using signed distance geometry.
- **Results**:
  - `person_1_vid.mp4` (Line $Y=585$px): Track 6 moved from $(290.6, 570.9) \rightarrow (307.1, 603.0)$ $\implies$ **`ENTRY`** emitted at $t = 3.62\text{s}$.
  - `person_2_vid.mp4` (Line $Y=650$px): Track 22 moved from $(304.7, 603.6) \rightarrow (298.7, 723.1)$ $\implies$ **`ENTRY`** emitted at $t = 7.63\text{s}$.
  - Uncrossing tracklets (Track 3, Track 19) remained strictly **`UNRESOLVED`** with zero spurious events emitted.

---

## 3. Hardware Realities & CPU Performance Metrics

Benchmark runs on local CPU (Windows, Intel Core i5/i7 class, CPUExecutionProvider):

| Step | Operation | Throughput (FPS) | Latency per Sampled Frame |
| :--- | :--- | :---: | :---: |
| Step 4.10.1 | Video Ingestion only | ~250+ FPS | < 4 ms |
| Step 4.10.2 | Ingestion + SCRFD Detection + ArcFace Embeddings | ~0.43 – 1.26 FPS | ~800 – 1200 ms |
| Step 4.10.3 | Ingestion + SCRFD Detection + ByteTrack | ~0.42 – 1.26 FPS | ~800 – 1200 ms |
| Step 4.10.4 | Ingestion + SCRFD + ArcFace + ByteTrack + Fusion | ~0.23 – 1.19 FPS | ~850 – 1400 ms |
| Step 4.10.5 | Ingestion + SCRFD + ByteTrack + Line Crossing | ~0.45 – 1.30 FPS | ~750 – 1100 ms |

### Architectural Implication:
1. **CPU Bottleneck**: SCRFD face detection and ArcFace 512-d feature extraction dominate runtime (~95% of execution time).
2. **Sampling Rate**: Sampling at 5 FPS reduces raw video frame processing by 83% (from 30 FPS down to 5 FPS).
3. **Hardware Requirement**: For real-time processing of live RTSP feeds at 5–10 FPS, an edge accelerator (NVIDIA TensorRT, ONNX Runtime GPU, or Apple Silicon CoreML) or dedicated inference container is required. On CPU, processing is asynchronous/batch-ready.

---

## 4. Current Configuration & Tuned Hyperparameters

| Component | Parameter | Calibrated Value | Rationale |
| :--- | :--- | :---: | :--- |
| **Ingestion** | `TARGET_FPS` | 5.0 | Balances tracking continuity with CPU inference budget |
| **Tracker** | `track_thresh` | 0.40 | Threshold to split high- vs. low-confidence face detections |
| **Tracker** | `match_thresh` | 0.80 | Max IoU distance ($1 - \text{IoU}$) allowing association |
| **Tracker** | `track_buffer` | 20 frames | Max lost frames before track deletion (~4s at 5 FPS) |
| **Boundary** | `DEADBAND_PIXELS` | 4.0 px | Hysteresis deadband around line to prevent crossing jitter |
| **Biometrics** | `MIN_MARGIN` | +0.25 | Required separation between candidate and runner-up |
| **Biometrics** | `MIN_VOTES` | 3 frames | Minimum track observations required for confirmed decision |

---

## 5. Known Limitations & Edge Cases

1. **Short Video Duration & Sample Size**:
   - Tested on 2 individual subjects in controlled corridors. Does not represent multi-person simultaneous occlusions or high-density entries.
2. **Face-Only Tracking vs. Body Tracking**:
   - ByteTrack currently tracks face bounding boxes. If a student turns their head or looks down, the face detector drops, causing track fragmentation. Full body/person detection (YOLOv8/ByteTrack) linked with face recognition is the standard industry approach for long-term tracking.
3. **Illumination and Pose Sensitivity**:
   - When facial angles exceed ~45° yaw or pitch, single-frame cosine similarity drops below 0.35.
4. **Boundary Line Placement**:
   - The virtual line must intersect the camera view where faces are clearly visible and roughly perpendicular to the camera axis.

---

## 6. Vision-to-Backend Event Contract

The Vision Service encapsulates all perception and emits structured, timestamped transit events to the backend:

```json
{
  "event_id": "evt_7f8a9b1c2d3e",
  "camera_id": "cam_entrance_01",
  "track_id": 22,
  "identity": "person_02",
  "direction": "ENTRY",
  "timestamp": "2026-09-23T14:30:15.820Z",
  "evidence": {
    "peak_similarity": 0.613,
    "mean_similarity": 0.585,
    "supporting_frames": 5,
    "total_frames": 5,
    "consistency_pct": 100.0,
    "margin_over_runner_up": 0.461
  }
}
```

The Backend attendance service consumes this payload to evaluate session rosters, accumulate presence intervals, and apply anti-proxy policies without knowing internal CV mechanics.
