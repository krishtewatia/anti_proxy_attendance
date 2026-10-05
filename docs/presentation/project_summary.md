# Executive Project Summary (1-Page)

## Project Title
**Anti-Proxy Automated Attendance System**
*Production-Grade Edge Biometrics & Continuous Presence Tracking*

---

### The Problem
Traditional college attendance systems fail at scale:
- **Paper Roll Calls**: Waste 10–15 minutes of every lecture and permit verbal "buddy calling".
- **Kiosk / RFID / Static Face Scanners**: Vulnerable to "buddy punching"—a student taps their friend's card or flashes a phone selfie at a kiosk and walks away, falsely claiming full credit for a lecture they never attended.

### The Solution
The **Anti-Proxy Automated Attendance System** replaces momentary check-ins with **continuous presence tracking over time**. By monitoring physical transit across doorway boundaries using edge computer vision, the system continuously tracks `ENTRY` and `EXIT` events and computes exact cumulative presence duration:

$$\text{Presence Ratio} = \frac{\sum (\text{EXIT}_i - \text{ENTRY}_i)}{\text{Class Duration}} \ge 75\%$$

Even if an impostor flashes a photo to trigger an `ENTRY` at 10:00 AM, the lack of continuous presence or a corresponding `EXIT` transit automatically results in an `ABSENT` verdict.

---

### System Architecture Highlights
1. **Edge Computer Vision (`vision-service`)**:
   - **Detection & Embeddings**: InsightFace SCRFD ($640 \times 640$) + ArcFace generating 512-dimensional unit feature vectors.
   - **Multi-Frame Tracking**: Pure NumPy/SciPy ByteTrack with an 8-state Kalman filter and 2-stage IoU Hungarian association.
   - **Evidence Fusion**: Sliding window requiring $\ge 3$ consistent identity matches ($\theta \ge 0.50$, margin $\Delta \ge 0.15$), bounding false confirmation probability to $< 10^{-6}$.
   - **Boundary Engine**: Spatial line-crossing detection with a 14-pixel deadband to eliminate threshold chatter.
   - **Outbox Resilience**: Durable SQLite outbox with exponential backoff, ensuring zero event loss during network outages.
2. **High-Performance Core (`backend`)**:
   - Asynchronous FastAPI backend backed by MongoDB 7.0 (with in-memory mongomock fallback).
   - Machine-to-machine service authentication using timing-safe tokens (`X-Camera-Token`), payload size enforcement (64 KB), and IP rate limiting (600 req/min).
   - Session Roster and Presence Engine enforcing 75% attendance thresholding and graceful handling of missing exits.
   - Immutable audit logging for every teacher override and administrative adjustment.
3. **Interactive Teacher UI (`frontend`)**:
   - React 18 / TypeScript single-page dashboard with adaptive live polling (3–5s) displaying student presence states (`INSIDE`, `OUTSIDE`, `NOT_SEEN`), real-time timers, and camera telemetry.

---

### Key Evidence & Verified Metrics
- **Test Coverage**: **299 backend tests** passing in 75s, **44 fast vision tests** passing in 19s, **12 frontend suites** passing in 3s.
- **Recognition Accuracy Validation**: Evaluated across 25 enrolled identities and 180 probe samples (150 genuine, 4,350 impostor comparisons); achieved **100% Rank-1 accuracy**, **100% open-set unknown rejection**, and an empirical separation gap of **+0.5050** between lowest genuine (`0.6419`) and highest impostor (`0.1369`).
- **DevSecOps Pipeline**: Full GitHub Actions CI with automated security gates (Bandit SAST, Semgrep OWASP, Gitleaks secret detection, pip-audit PyPI CVEs, npm audit, and Trivy container scanning). Pre-commit hooks clean across 100% of repo files.
- **Privacy By Design**: Zero raw facial photos or video streams stored in the database. Only 512-d mathematical embeddings are persisted.

---

### Team & Deliverables
- **Codebase**: Fully reproducible via `docker compose up -d` or native local venv.
- **Documentation**: 9 Architecture Decision Records (ADRs), complete API references, testing guides, and threat models.
