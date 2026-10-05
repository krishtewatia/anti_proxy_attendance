# ADR-006: Service-to-Service Authentication & Event Ingestion Security Baseline

## Status
Accepted

## Context
The Anti-Proxy Attendance System relies on the Vision Service to detect faces, track spatial boundaries, and transmit transit events (`ENTRY` / `EXIT`) to the FastAPI backend at `POST /api/v1/events`.

While human user interactions (teachers, students, admins) are protected by scoped JWT Bearer tokens, the `/api/v1/events` endpoint represents machine-to-machine (M2M) perception telemetry. In earlier versions of the system, this endpoint was unauthenticated and accepted events from any client on the network with arbitrary `camera_id` parameters. This introduced a critical vulnerability:
1. **Attendance Poisoning**: A rogue client or compromised workstation on the local network could forge transit events for students who never attended class, generating illegitimate attendance records.
2. **Denial of Service / Memory Exhaustion**: Lack of payload limits and rate controls exposed the ingestion route to resource exhaustion attacks.
3. **WebRTC Ingest Exposure**: The phone camera WebRTC ingest server had open signaling and status endpoints without access controls.

## Decision
We enforce a robust service-to-service authentication and security baseline across the perception and backend services:

### 1. Dedicated Machine Credentials via API Key Headers
- Service-to-service authentication is strictly separated from human JWT flows.
- Vision Service and camera agents authenticate requests using the `X-API-Key` (or `X-Vision-API-Key`) HTTP header.
- The event body payload contract remains completely unchanged (`event_id`, `camera_id`, `track_id`, `identity`, `direction`, `timestamp`, `evidence`).

### 2. Cryptographic Storage and Constant-Time Comparison
- Raw API keys are never stored in persistent databases or recorded in plain-text logs.
- The server computes SHA-256 digests of configured and incoming credentials.
- Hash comparison is executed strictly using `secrets.compare_digest()` to eliminate timing attack vectors.

### 3. Granular Camera ID Binding
- Supports both a global Vision Service master credential (authorized for any camera) and granular per-camera credentials bound to explicit `camera_id` lists (e.g. `CAM_ROOM_101_DOOR`).
- If a camera-bound key attempts to emit events for an unapproved camera, the request is rejected with `HTTP 403 Forbidden` (`API key is not authorized for camera_id`).

### 4. Fail-Closed Policy and Security Auditing
- Missing or invalid API keys result in `HTTP 401 Unauthorized`.
- All authentication and authorization failures record a `SERVICE_AUTH_FAILED` entry in the `audit_events` collection with client IP, timestamp, and failure reason.
- Secrets, keys, and hashes are strictly excluded from audit entries and application logs.

### 5. Ingestion Hardening (Payload Size & Rate Limiting)
- Enforces an explicit payload size cap (`EVENTS_MAX_PAYLOAD_BYTES`, default 64 KB) returning `HTTP 413 Payload Too Large`.
- Implements a thread-safe, sliding-window rate limiter per client IP / camera (`EVENTS_RATE_LIMIT_PER_MINUTE`, default 600 req/min) returning `HTTP 429 Too Many Requests`.

### 6. WebRTC Phone Camera Endpoint Protection
- The phone camera WebRTC receiver supports a configurable access token (`WEBRTC_ACCESS_TOKEN`).
- When configured, access to signaling (`GET /`, `POST /offer`, `GET /status`) requires authentication via query parameter (`?token=...`) or `Authorization: Bearer` / `X-Access-Token` header.

### 7. CORS and Secret Hygiene Baseline
- Wildcard CORS (`*`) with credentials (`allow_credentials=True`) is explicitly disallowed. CORS defaults to an explicit whitelist of development/production origins.
- Startup validation checks `JWT_SECRET_KEY` length ($\ge 32$ characters) and rejects known default/weak keys.
- Application loggers use a `SensitiveDataFilter` to mask tokens, passwords, API keys, embeddings, and base64 image data.

## Consequences
- **Positive:**
  - Complete protection against forged attendance events and camera spoofing.
  - Minimal overhead: fast SHA-256 + constant-time comparison without database round-trips.
  - Zero disruption to existing event schemas or user JWT lifecycles.
  - Complete compliance with security audit, CORS, and secret hygiene standards.
- **Trade-off:**
  - Vision service dispatchers and camera agents must manage and provide valid credentials.
