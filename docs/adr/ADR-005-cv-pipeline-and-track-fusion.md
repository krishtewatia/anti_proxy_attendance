# ADR-005: Computer Vision Pipeline & Track-Level Evidence Fusion

## Status
Accepted

## Context
Initial still-image benchmarks achieved high cosine similarities ($\ge 0.80$) for stationary, frontal faces. However, empirical testing on moving video footage (Steps 4.10.1 through 4.10.5) revealed that a person walking through a camera field produces a dynamic curve of similarity scores (e.g. rising from $0.44 \rightarrow 0.61 \rightarrow 0.31$) due to variable pose, motion blur, and distance.

Relying on a static single-frame threshold (e.g., $\tau = 0.60$) caused intermittent false negatives and flickering `UNKNOWN` classifications during movement. Furthermore, the system must detect whether a student is entering or exiting a room without embedding attendance business rules into the perception layer.

## Decision
We adopt a multi-frame track-level fusion architecture for the Vision Service:

1. **Controlled Ingestion**: Ingest video and sample frames at a controlled rate of **5.0 FPS**, reducing inference load by ~83% compared to full 30 FPS processing while preserving spatial tracking continuity.
2. **Perception**: Extract face bounding boxes and 512-dimensional ArcFace embeddings using InsightFace (`buffalo_l` / SCRFD).
3. **Multi-Object Tracking**: Deploy a self-contained **ByteTrack** implementation (8-state Kalman filter and Hungarian assignment via `scipy.optimize.linear_sum_assignment`) with zero external C++ dependencies.
4. **Track-Level Evidence Fusion**: Replace single-frame threshold decisions with evidence accumulation over Track IDs:
   - Calculate voting consistency (% of track frames agreeing on top candidate).
   - Require a minimum separation margin ($+0.25$) over the second-best gallery identity.
   - Use peak and mean track similarities to confirm biometric identity.
5. **Spatial Boundary Logic**: Evaluate track centroid trajectories against a configurable virtual line using signed-distance geometry to emit discrete directional events:
   - $\text{SIDE\_A} \rightarrow \text{SIDE\_B} \implies \mathbf{ENTRY}$
   - $\text{SIDE\_B} \rightarrow \text{SIDE\_A} \implies \mathbf{EXIT}$
   - Non-crossing trajectories $\implies \mathbf{UNRESOLVED}$
6. **Perception-to-Backend Event Contract**: Emit standardized JSON events containing `{track_id, identity, direction, timestamp, evidence}` to the backend service.

## Consequences
- **Positive:**
  - **Eliminates threshold fragility**: Correct identities are resolved with 100% track consistency and margins exceeding $+0.36$, even when individual frame scores dip below traditional static thresholds.
  - **Zero extra tracking dependencies**: Avoids Windows C++ compilation issues (`lap`/`cython-bbox`) while maintaining standard ByteTrack mathematical properties.
  - **Strict decoupling**: Attendance policies, course rosters, and audit trails remain isolated in the backend service.
- **Trade-offs & Mitigations:**
  - **CPU Inference Latency**: Full detection + embedding on CPU runs at ~0.5–1.2 FPS. Production deployment on live RTSP feeds requires ONNX Runtime GPU / TensorRT acceleration or asynchronous worker pools.
  - **Face-Only Tracking**: If a subject turns completely away from the camera, the face bounding box is temporarily lost. Mitigated by ByteTrack's 20-frame lost buffer and future extension to person-body tracking.
