# Computer Vision Pipeline & Configuration Guide

> [!NOTE]
> **Historical context.** This document was written when a phone could stream to the vision service over WebRTC on port 8088. That path has been removed (see [ADR-010](../adr/ADR-010-drop-webrtc-phone-ingest.md)). Frames now go from the browser to the backend, the vision service is internal only, and doorway mode is offline-tested with no live ingest. Passages below that describe WebRTC, the phone camera page or port 8088 as a public endpoint no longer apply.

## 1. Perception Architecture Overview

The Vision Service implements a modular, high-throughput edge perception pipeline (`vision-service/pipeline/live_cv_pipeline.py`) designed to run on local CPU or edge accelerators. The pipeline processes video frames at a calibrated sampling rate (5–10 FPS), detects human faces, tracks individuals across frames, verifies identity against an enrolled biometric gallery, and resolves directional transit across a virtual doorway threshold.

```mermaid
flowchart LR
    FRAME["Input Frame<br>(BGR 640x480+)"] --> DET["SCRFD Face Detector<br>(Confidence >= 0.50)"]
    DET -->|"Boxes & Landmarks"| TRK["ByteTrack<br>(8-State Kalman)"]
    DET -->|"Aligned Face Crops"| REC["ArcFace Embedding<br>(512-d Unit Vector)"]
    TRK & REC --> BUFFER["Track Evidence Buffer<br>(Window = 15 Frames)"]
    BUFFER -->|"Vote Plurality >= 3<br>Sim >= 0.50, Margin >= 0.15"| CONFIRM["Identity Confirmed"]
    CONFIRM & TRK --> BOUND["Boundary State Machine<br>(Signed Distance Line Crossing)"]
    BOUND -->|"Crosses 14px Deadband"| EVENT["Vision Transit Event<br>(ENTRY / EXIT)"]
```

---

## 2. Core Perception Modules

### 2.1 Face Detection: InsightFace SCRFD
- **Model**: `SCRFD_10G_KPS` (part of InsightFace `buffalo_l` pack).
- **Resolution**: Scaled to standard evaluation size $640 \times 640$.
- **Key Features**: Efficient multi-scale anchor generation with feature pyramid networks. Outputs accurate bounding boxes $[x_1, y_1, x_2, y_2]$, confidence scores, and 5 facial keypoints (eyes, nose, mouth corners).
- **Execution Provider**: Default `CPUExecutionProvider` via ONNX Runtime; supports `CUDAExecutionProvider` or `CoreMLExecutionProvider`.

### 2.2 Feature Extraction: ArcFace
- **Model**: ResNet-based Deep Residual Network trained with Additive Angular Margin Loss (ArcFace).
- **Output**: 512-dimensional continuous floating-point vector.
- **Normalization**: Vectors are normalized to unit Euclidean length ($\|v\|_2 = 1$). Cosine similarity between two vectors $u$ and $v$ simplifies to their dot product:
  $$\text{sim}(u, v) = u \cdot v = \sum_{i=1}^{512} u_i v_i$$

### 2.3 Motion Tracking: ByteTrack
Tracking is performed using a pure NumPy/SciPy implementation of ByteTrack ([`vision-service/tracking/bytetrack.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tracking/bytetrack.py)):
- **Motion Model**: 8-dimensional Kalman filter state vector:
  $$x = [c_x, c_y, a, h, \dot{c}_x, \dot{c}_y, \dot{a}, \dot{h}]^T$$
  where $(c_x, c_y)$ is the bounding box center, $a = w/h$ is the aspect ratio, $h$ is height, and dotted variables represent velocities.
- **Two-Stage Association**:
  1. *First Stage*: Associates high-confidence detections ($\ge 0.40$) with existing tracks using Intersection over Union (IoU) distance and Hungarian assignment.
  2. *Second Stage*: Associates remaining unconfirmed detections with lower-confidence detections to recover tracks during momentary motion blur or partial occlusion.
- **Track Buffer**: Lost tracks are retained for up to 20 frames before being pruned, ensuring continuity if a student briefly turns their head.

---

## 3. Spatial Boundary Crossing & Hysteresis

### 3.1 Mathematical Formulation
The doorway boundary is defined as an oriented directed line segment between two calibrated pixel coordinates $P_1(x_1, y_1)$ and $P_2(x_2, y_2)$.

For a tracked person's centroid $(x_0, y_0)$, the signed perpendicular distance $d$ to the line is computed as:
$$d(x_0, y_0) = \frac{(x_2 - x_1)(y_0 - y_1) - (x_0 - x_1)(y_2 - y_1)}{\sqrt{(x_2 - x_1)^2 + (y_2 - y_1)^2}}$$

The sign of $d$ indicates which side of the boundary line the person occupies:
- $d < 0$: Positioned in `SIDE_A` (e.g., Outside Corridor).
- $d > 0$: Positioned in `SIDE_B` (e.g., Inside Classroom).

```
   SIDE_A (Outside)          DEADBAND (14 px)          SIDE_B (Inside)
                         |  -7px   Line   +7px  |
  Track Centroid (t0) -> |          │           |
                         |          │           | -> Track Centroid (t1)
                         |==========╪===========|
                         |<----- 14 px wide --->|
                         |  Hysteresis Deadband |
```

### 3.2 14-Pixel Deadband Hysteresis
To prevent spurious event chatter when an individual lingers or hesitates on the threshold, a **14-pixel deadband** is enforced around the line ($d \in [-7.0, +7.0]$):
- An `ENTRY` is emitted **only** when a track transitions from $d < -7.0$ through the deadband to $d > +7.0$.
- An `EXIT` is emitted **only** when a track transitions from $d > +7.0$ through the deadband to $d < -7.0$.
- Movement entirely within $[-7.0, +7.0]$ produces zero events.

---

## 4. Multi-Frame Temporal Evidence Fusion

A track is **never** confirmed on a single face observation. Instead, `LiveCVPipeline` accumulates classification evidence across consecutive frames within an observation window of 15 frames:

### 4.1 Plurality Voting Rule
1. **Cosine Similarity Threshold**: The observation must exceed $\theta \ge 0.50$ against an enrolled gallery embedding.
2. **Relative Separation Margin**: The top candidate must exceed the runner-up candidate by at least $\Delta \ge 0.15$:
   $$\text{top\_sim} - \text{runner\_up\_sim} \ge 0.15$$
3. **Minimum Supporting Frames**: The track must accumulate $\ge 3$ consistent votes for the same enrolled identity.

### 4.2 Gallery Management & Dynamic Reload
- At startup, the pipeline loads enrolled student embeddings into an in-memory normalized NumPy matrix ($N \times 512$).
- Matrix dot-product vectorization executes gallery matching in $< 1\text{ ms}$ for galleries of up to 5,000 students.
- When new students enroll via the administrative portal, the pipeline exposes a dynamic `reload_gallery()` method that refreshes embeddings without restarting the video stream.

---

## 5. Hyperparameter Reference Table

| Parameter | Environment Variable | Default Value | Calibrated Range | Description & Rationale |
| :--- | :--- | :---: | :---: | :--- |
| **Similarity Threshold** | `RECOGNITION_SIMILARITY_THRESHOLD` | `0.50` | `0.45 – 0.60` | Minimum ArcFace cosine score to consider an identity match. Calibrated from 2E.6 evaluation to eliminate false accepts. |
| **Separation Margin** | `RECOGNITION_MIN_MARGIN` | `0.15` | `0.10 – 0.25` | Minimum difference between top and second-best candidate scores to reject ambiguous lookalikes. |
| **Minimum Votes** | `RECOGNITION_MIN_VOTES` | `3` | `2 – 5` | Number of consistent frames required before confirming track identity. |
| **Observation Window** | `TRACK_EVIDENCE_WINDOW` | `15` | `10 – 30` | Number of past frames retained in rolling track evidence history. |
| **Deadband Width** | `DEADBAND_PIXELS` | `14.0` | `10.0 – 20.0` | Width of the spatial hysteresis zone surrounding the boundary line in pixels. |
| **Detection Score** | `DETECTION_CONF_THRESH` | `0.50` | `0.40 – 0.70` | Confidence cutoff for SCRFD face bounding boxes. |
| **Target FPS** | `CV_TARGET_FPS` | `5.0` | `5.0 – 15.0` | Target frame sampling rate for balanced CPU inference latency. |
| **Track Retention** | `TRACK_BUFFER_FRAMES` | `20` | `15 – 45` | Number of consecutive missing frames before ByteTrack drops a track. |

---

## 6. Camera Source Configuration

The pipeline supports three interchangeable video sources via `vision-service/camera/factory.py`:

```bash
# 1. Run with WebRTC Mobile Phone Stream (Port 8088):
python run_webrtc_camera.py --source webrtc --port 8088 --camera-id CAM_ROOM_101_DOOR

# 2. Run with RTSP CCTV Stream:
python run_webrtc_camera.py --source rtsp --rtsp-url "rtsp://admin:pass@192.168.1.50:554/live" --camera-id CAM_ROOM_101_DOOR

# 3. Run with Recorded Video File:
python run_webrtc_camera.py --source file --video-path tests/video_test/person_1_vid.mp4 --camera-id CAM_ROOM_101_DOOR
```
