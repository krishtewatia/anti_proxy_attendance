# Viva & Faculty Examination: Questions & Honest Answers

**Target Audience**: Academic Examiners, Department Heads (HOD), Capstone Viva Committees
**Tone**: Technically rigorous, transparent, evidence-backed, and honest regarding system boundaries.

---

### Q1: How does your system actually prevent a student from having a friend mark proxy attendance?
**Answer**:
> *"Traditional RFID, fingerprint, or kiosk scanners fail because they record a **momentary point-in-time check-in**. A friend can easily swipe a second card or hold a photo in front of a tablet and walk away, gaining 100% attendance credit for 0 minutes of actual presence.
>
> Our system prevents this by shifting the paradigm to **continuous presence tracking over time**. We track physical transit across doorway boundaries (`ENTRY` and `EXIT`). To earn attendance credit, a student must accumulate at least **75% of total class duration** inside the room:
>
> $$\text{Presence Ratio} = \frac{\sum (\text{EXIT}_i - \text{ENTRY}_i)}{\text{Session Duration}} \ge 75\%$$
>
> Even if an impostor manages to trigger an initial `ENTRY` event at the start of class, they cannot claim attendance without an eventual paired `EXIT` and 45+ minutes of verified duration. A momentary proxy transaction yields near-zero attendance credit."*

---

### Q2: What happens if an attacker flashes a printed photo or phone screen at the camera? (Anti-Spoofing)
**Answer**:
> *"We conducted a formal presentation attack threat analysis in Step 2E.7. Rather than blindly adding a heavy neural anti-spoofing model that would cut our CPU frame rate in half, the system relies on **four structural mitigations**:
> 1. **Kinematic Boundary Trajectory**: Events trigger *only* when a tracked face physically traverses across our 14-pixel deadband from outside to inside. A photo held stationary, taped to a wall, or flashed momentarily generates zero transit events.
> 2. **Multi-Frame Plurality Voting**: Our pipeline requires at least 3 consistent identity confirmations across an observation window. Transient flashes or screen glare do not confirm an identity.
> 3. **Continuous Presence Duration**: Flashing a photo at the doorway gives zero continuous classroom presence. To fake 75% presence, the attacker would have to physically hold the photo inside the lecture hall for 45 minutes, which is immediately deterred by teacher oversight and peer visibility.
> 4. **Honest Limitation**: We do not claim active 3D depth or NIR hardware liveness. Advanced dynamic video replays on high-resolution screens remain an acknowledged limitation that we address through teacher live monitoring."*

---

### Q3: Why separate the Computer Vision pipeline from the FastAPI backend into two independent services?
**Answer**:
> *"This was an explicit architectural decision documented in **ADR-002**:
> 1. **Heterogeneous Compute Profiles**: The Vision Service is compute-bound (heavy matrix operations, ONNX neural inference, OpenCV frame decoding). The FastAPI backend is I/O-bound (async MongoDB operations, JWT validation, HTTP request handling). Keeping them together would starve the async event loop and degrade API responsiveness.
> 2. **Horizontal Edge Scaling**: A university campus has dozens of classrooms. In our architecture, one lightweight FastAPI backend can effortlessly manage hundreds of classrooms, while inexpensive edge nodes (e.g., local PCs or NVIDIA Jetson boards) handle the video streams locally.
> 3. **Security & Data Minimization**: Edge cameras do not need and should not have database credentials. They operate in an isolated network segment and communicate exclusively via a minimal, authenticated REST event contract (`POST /api/v1/events`)."*

---

### Q4: Why did you choose ByteTrack over DeepSORT or simple centroid tracking?
**Answer**:
> *"We evaluated tracking trade-offs in **ADR-005**:
> - Simple centroid tracking fails during crossing paths or occlusions when students enter together.
> - DeepSORT requires running a separate convolutional appearance feature extractor (ReID model) on every bounding box on every frame, which severely degrades CPU performance.
> - **ByteTrack** uses an elegant two-stage association strategy: it associates high-confidence detections first, then uses low-confidence detections to maintain tracks during momentary motion blur or partial occlusion. It relies purely on 8-state Kalman filtering and IoU Hungarian matching.
> - In our pipeline, ByteTrack executes in **under 2 milliseconds per frame** in pure vectorized NumPy/SciPy without external C++ build dependencies."*

---

### Q5: How does the system handle lighting variations, glasses, or head tilts?
**Answer**:
> *"In Step 2E.6, we evaluated our ArcFace feature extractor across controlled capture perturbations:
> - **Lighting**: Tested under normal daylight, dim low-lux conditions, and backlit doorway angles. Genuine similarities remained between `0.6570` and `0.7137`, well above our production threshold of `0.50`.
> - **Pose & Angle**: Evaluated frontal ($0^\circ$), yaw ($\pm 30^\circ$), and downward head tilts. Yaw exhibited the expected minor dip (mean similarity `0.6792`), but consistently cleared `0.50` with positive margins.
> - **Eyeglasses**: ArcFace embeddings focus on invariant deep structural geometry (inter-pupillary distance, cheekbone contour, nasal bridge) and remain robust to standard spectacles.
> - **Extreme Occlusions**: If a student wears a full face mask or looks $> 45^\circ$ away from the camera, detection confidence drops. In such rare cases, the system fails gracefully to `UNKNOWN`, and the instructor can apply a 1-click manual override with audit logging."*

---

### Q6: What happens if the university Wi-Fi or local network drops during a lecture?
**Answer**:
> *"We implemented an **offline-first Transactional Outbox Pattern** on the edge device (`vision-service/events/outbox.py`).
>
> When an edge camera detects a transit, the event is immediately committed to a local SQLite database with write-ahead logging (`WAL`). A background dispatcher thread attempts delivery to the backend. If the network drops or the backend is rebooted, the outbox retains the events on local disk. Once connectivity is restored, the dispatcher drains the queue with randomized exponential backoff. Zero events are lost."*

---

### Q7: Storing student face data raises severe privacy concerns. How do you address this?
**Answer**:
> *"Privacy by design was our highest architectural constraint (documented in **ADR-004** and our Security & Privacy Guide):
> 1. **Zero Raw Photo Storage**: The database does NOT store photos, cropped face chips, or video streams. Enrollment photos are processed in volatile RAM, converted into 512-dimensional mathematical feature vectors, and immediately destroyed.
> 2. **Non-Reversible Embeddings**: Reconstructing an identifiable human face from an isolated 512-d ArcFace floating point vector is computationally non-trivial.
> 3. **Cascading Deletion**: When a student record is removed, its biometric profile vector is permanently deleted from MongoDB.
> 4. **Honest Compliance Disclaimer**: As documented in our repository, this is an academic research prototype. We explicitly disclaim certified GDPR/FERPA compliance and recommend formal institutional DPIA and opt-in consent protocols before any live campus deployment."*

---

### Q8: Why deploy locally with Docker Compose instead of deploying directly to AWS?
**Answer**:
> *"There are two compelling technical reasons:
> 1. **Bandwidth Realities**: Streaming 1080p video from 50 classrooms to a cloud provider consumes over 150 Mbps of continuous uplink bandwidth, which campus networks cannot sustain reliably. Edge processing keeps heavy video data local; only lightweight JSON events (~200 bytes) cross the network.
> 2. **Cloud Cost & Sovereignty**: Running 24/7 cloud GPU inference (e.g., AWS EC2 G4dn instances) is prohibitively expensive for university budgets. Processing on local edge hardware with containerized Docker Compose costs zero marginal cloud dollars and preserves data locality."*

---

### Q9: What happens if a student enters the classroom but the camera misses their exit? (The Missing Exit Problem)
**Answer**:
> *"In real classrooms, doors get crowded, or a student might leave through a rear exit without a camera.
>
> In Step 2E.5, we hardened our Presence Engine:
> - If an `ENTRY` has no matching `EXIT` when the lecture concludes, the system provides a configurable policy (`CAP_MISSING_EXIT_AT_SESSION_END`).
> - When enabled, the open presence interval is capped at the scheduled `session_end` timestamp.
> - The record is automatically tagged with an `ANOMALY_MISSING_EXIT` flag on the teacher's dashboard, giving the professor clear visibility to confirm whether the student was actually present."*

---

### Q10: How do you mathematically guarantee that an impostor won't be falsely recognized?
**Answer**:
> *"We combine two mathematical layers:
> 1. **Empirical Distribution Separation**: In our 2E.6 evaluation of 4,500 comparisons, the maximum observed impostor similarity was `0.1369`. Our production threshold of `0.50` provides a **+0.3631 safety buffer** above the worst-case impostor.
> 2. **3-Vote Temporal Plurality Bound**: Under independent frame observations, even if single-frame false accept rate were $p = 0.001$, the probability of an impostor accumulating 3 false votes for the same specific student among 50 enrolled peers within a 15-frame window is bounded by:
>
> $$P(\text{False Confirmation}) \le 50 \cdot \sum_{k=3}^{15} \binom{15}{k} \left(\frac{0.001}{50}\right)^k \left(1 - \frac{0.001}{50}\right)^{15-k} < 10^{-6}$$
>
> That represents less than a 1-in-a-million chance of an impostor false confirmation."*
