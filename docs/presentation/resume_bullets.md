# Evidence-Backed Engineering Resume Bullets

> [!IMPORTANT]
> **Strict Verification Standard:**
> Every resume bullet in this document is **100% backed by verifiable code, empirical benchmark reports, or automated test suites in this repository**.
> Claims lacking rigorous empirical evidence (e.g., *"99.9% accuracy on thousands of unconstrained faces"* or *"full GDPR compliance"*) have been explicitly excluded.

---

## 1. Computer Vision & Edge AI Engineer

- **Multi-Frame Tracking & Feature Extraction**:
  - *Bullet*: Architected a real-time edge computer vision pipeline integrating InsightFace SCRFD ($640 \times 640$) face detection and ArcFace 512-dimensional embedding extraction with an 8-state Kalman ByteTrack tracker, maintaining identity persistence across multi-frame transits and momentary occlusions.
  - *Repo Evidence*: [`vision-service/pipeline/live_cv_pipeline.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py), [`vision-service/tracking/bytetrack.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tracking/bytetrack.py).

- **Biometric Accuracy Validation & Mathematical Bound**:
  - *Bullet*: Executed systematic biometric validation across 25 enrolled subjects and 4,500 comparison pairs; calibrated a data-driven cosine threshold ($\theta = 0.50$, margin $\Delta \ge 0.15$) with an empirical separation gap of $+0.5050$ (Max Impostor $0.1369$ vs Min Genuine $0.6419$), and mathematically proved that 3-vote temporal confirmation bounds multi-frame false accepts to $< 10^{-6}$.
  - *Repo Evidence*: [`docs/evaluation/recognition_eval.md`](file:///c:/Users/hp/Downloads/anti_proxy_project/docs/evaluation/recognition_eval.md), [`docs/adr/ADR-007-recognition-similarity-threshold.md`](file:///c:/Users/hp/Downloads/anti_proxy_project/docs/adr/ADR-007-recognition-similarity-threshold.md).

- **Spatial Hysteresis & Directional Transit Detection**:
  - *Bullet*: Designed a signed-distance boundary crossing state machine incorporating an empirical 14-pixel deadband ($d \in [-7\text{px}, +7\text{px}]$) to accurately differentiate `ENTRY` and `EXIT` transitions while eliminating false transit triggers caused by door-threshold hesitation.
  - *Repo Evidence*: [`vision-service/pipeline/live_cv_pipeline.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/pipeline/live_cv_pipeline.py#L220-L280), [`vision-service/tests/test_multi_person_robustness.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_multi_person_robustness.py).

- **Hardware Video Ingestion Abstraction**:
  - *Bullet*: Implemented an asynchronous multi-source video ingestion layer supporting WebRTC phone camera streaming via `aiortc` (port 8088), RTSP CCTV feeds with auto-reconnection and exponential backoff, and offline MP4 frame decoding at calibrated 5–10 FPS.
  - *Repo Evidence*: [`vision-service/camera/factory.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/camera/factory.py), [`vision-service/camera/webrtc_receiver.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/camera/webrtc_receiver.py), [`vision-service/camera/rtsp_source.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/camera/rtsp_source.py).

---

## 2. Backend & Distributed Systems Engineer

- **Asynchronous FastAPI Core & State Recovery**:
  - *Bullet*: Engineered a high-throughput, asynchronous FastAPI backend backed by MongoDB 7.0 and Motor; implemented a robust presence engine calculating cumulative classroom time ratios across discrete transit intervals, gracefully capping missing exits at session boundaries.
  - *Repo Evidence*: [`backend/app/services/presence_engine.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/presence_engine.py), [`backend/app/api/routes/sessions.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/routes/sessions.py), [`backend/tests/test_attendance_e2e.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_attendance_e2e.py).

- **Timing-Safe Service Authentication & DoS Defense**:
  - *Bullet*: Secured high-volume machine-to-machine event ingestion (`POST /api/v1/events`) using timing-safe cryptographic comparisons (`secrets.compare_digest`), request payload size constraints (64 KB cap), in-memory IP rate limiting (600 req/min), and unique database-level idempotency indexes.
  - *Repo Evidence*: [`backend/app/api/dependencies/camera_auth.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/dependencies/camera_auth.py), [`backend/app/api/dependencies/rate_limiter.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/api/dependencies/rate_limiter.py), [`backend/tests/test_service_auth.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/tests/test_service_auth.py).

- **Offline-First Outbox Pattern**:
  - *Bullet*: Implemented an edge transactional outbox pattern using local SQLite WAL journaling and background worker threads with exponential backoff and randomized jitter, guaranteeing zero transit event loss during network partitions or backend service downtime.
  - *Repo Evidence*: [`vision-service/events/outbox.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/events/outbox.py), [`vision-service/events/event_dispatcher.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/events/event_dispatcher.py), [`vision-service/tests/test_reliability_outbox.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/vision-service/tests/test_reliability_outbox.py).

- **Tamper-Evident Governance & Auditing**:
  - *Bullet*: Developed an immutable, append-only audit trail logging every manual attendance override and administrative change, capturing actor identity, timestamp, before/after states, and mandatory justification text.
  - *Repo Evidence*: [`backend/app/database/audit.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/database/audit.py), [`backend/app/services/attendance_correction.py`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/app/services/attendance_correction.py).

---

## 3. Full-Stack & DevSecOps Engineer

- **Comprehensive Test Suite & Quality Verification**:
  - *Bullet*: Authored and maintained a multi-tier test pyramid comprising **299 backend tests** (75s execution), **44 fast vision tests** (19s execution), and **12 frontend test suites** (3s execution), incorporating pytest markers (`unit`, `integration`, `e2e`) and automated mongomock fallbacks.
  - *Repo Evidence*: [`docs/evaluation/test_coverage_matrix.md`](file:///c:/Users/hp/Downloads/anti_proxy_project/docs/evaluation/test_coverage_matrix.md), [`backend/pytest.ini`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/pytest.ini).

- **Automated DevSecOps Pipeline & Security Gates**:
  - *Bullet*: Established a local and GitHub Actions DevSecOps workflow integrating Bandit (Python AST SAST), Semgrep (OWASP Top 10), Gitleaks (secret detection), pip-audit (PyPI CVEs), npm audit, and Trivy container vulnerability scanning, triaging all scanner warnings with zero blanket ignores.
  - *Repo Evidence*: [`.github/workflows/ci.yml`](file:///c:/Users/hp/Downloads/anti_proxy_project/.github/workflows/ci.yml), [`.github/workflows/security.yml`](file:///c:/Users/hp/Downloads/anti_proxy_project/.github/workflows/security.yml), [`.pre-commit-config.yaml`](file:///c:/Users/hp/Downloads/anti_proxy_project/.pre-commit-config.yaml).

- **Multi-Stage Containerization & Reproducible Deployment**:
  - *Bullet*: Authored secure, non-root, multi-stage Dockerfiles and unified Docker Compose architecture with health checks, internal network isolation, named volume model persistence, and automated demo bootstrap scripts (`seed_demo.py`, `docker_smoke_test.py`).
  - *Repo Evidence*: [`docker-compose.yml`](file:///c:/Users/hp/Downloads/anti_proxy_project/docker-compose.yml), [`backend/Dockerfile`](file:///c:/Users/hp/Downloads/anti_proxy_project/backend/Dockerfile), [`frontend/Dockerfile`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/Dockerfile).

- **Real-Time Interactive Instructor Dashboard**:
  - *Bullet*: Built a responsive React 18 / TypeScript SPA utilizing adaptive short-polling (3–5s) to visualize real-time classroom presence, displaying live status chips (`INSIDE`, `OUTSIDE`, `NOT_SEEN`), cumulative presence meters, and one-click audit-backed overrides.
  - *Repo Evidence*: [`frontend/src/pages/SessionDetails.tsx`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/src/pages/SessionDetails.tsx), [`frontend/src/components/session/LiveAttendanceFeed.tsx`](file:///c:/Users/hp/Downloads/anti_proxy_project/frontend/src/components/session/LiveAttendanceFeed.tsx).
