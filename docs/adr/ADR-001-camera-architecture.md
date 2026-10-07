# ADR-001: Camera Architecture

> [!NOTE]
> **Historical context.** This document was written when a phone could stream to the vision service over WebRTC on port 8088. That path has been removed (see [ADR-010](../adr/ADR-010-drop-webrtc-phone-ingest.md)). Frames now go from the browser to the backend, the vision service is internal only, and doorway mode is offline-tested with no live ingest. Passages below that describe WebRTC, the phone camera page or port 8088 as a public endpoint no longer apply.

## Status
Accepted

## Context
Automated attendance verification requires capturing student transit reliably into and out of classrooms. In designing the initial deployment topology, we need to balance system complexity, directional transit accuracy, and operational hardware requirements for the MVP.

## Decision
We will start with a dedicated two-camera architecture:
- Two fixed cameras per classroom.
- One designated **ENTRY** camera focused on transit entering the room.
- One designated **EXIT** camera focused on transit exiting the room.
- One classroom initially for the MVP deployment.
- One session processed at a time initially.
- Future evaluation: investigate whether a single-camera architecture (using directional line-crossing tracking) is practical and sufficiently reliable without compromising anti-proxy guarantees.

## Consequences
- **Positive:** Dedicated directional cameras drastically simplify transit classification, reduce face orientation ambiguity, and prevent conflating ingress and egress events.
- **Trade-off:** Requires mounting and streaming two camera feeds per classroom rather than a single shared sensor.
