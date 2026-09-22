# ADR-002: Vision / Backend Separation

## Status
Accepted

## Context
Face recognition, spatial object tracking, and camera stream ingest represent computationally heavy, high-throughput perception tasks. In contrast, attendance calculation, course roster verification, session lifecycles, and audit logging represent relational/document-oriented business logic and security policies. Blending these concerns into a monolithic pipeline creates operational coupling, testing difficulty, and poor scalability.

## Decision
We enforce a strict boundary between perception and business logic:
- **The Vision Service determines what the camera observed.**
  - Detects faces, matches biometric embeddings, tracks bounding boxes, and generates timestamped transit events.
  - Example emission: `ST042 → ENTRY → 10:03:21 → confidence 0.94`
- **The Backend determines what that observation means for attendance.**
  - Evaluates authorization, eligibility, active sessions, duplicate debouncing, presence interval accumulation, and anomaly flags.
  - Example evaluation: Is ST042 enrolled in this class? Is there an active session right now? Is this a duplicate ENTRY within a debounce window? Should we open a presence interval?

## Consequences
- **Positive:**
  - Decoupled architectures allow the Vision Service and Backend to scale, deploy, and evolve independently.
  - Computer vision models or inference backends can be updated or swapped without altering business rules, database schemas, or web endpoints.
  - Clean separation enables deterministic unit testing of backend business rules using mock transit events without requiring running camera feeds or GPU resources.
- **Trade-off:**
  - Introduces network/IPC boundary and requires maintaining an explicit, versioned event schema between the services.
