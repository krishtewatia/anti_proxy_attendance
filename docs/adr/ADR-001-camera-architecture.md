# ADR-001: Camera Architecture

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
