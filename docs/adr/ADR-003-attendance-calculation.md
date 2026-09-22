# ADR-003: Attendance Calculation

## Status
Accepted

## Context
Traditional attendance mechanisms (paper sign-in sheets, RFID tap, static single-shot facial check-ins) permit proxy attendance and early departures: a student checks in at minute zero and immediately leaves the lecture hall. A robust anti-proxy attendance system must model continuous or interval-based physical classroom presence.

## Decision
We define an interval-based attendance calculation engine with explicit lifecycle and boundary rules:
1. **Accumulated Valid Intervals:** Presence is measured as the sum total of valid intervals spent physically in the classroom during the scheduled session.
2. **Interval Boundaries:**
   - A valid **ENTRY** event starts a presence interval.
   - A valid **EXIT** event closes the active presence interval.
   - Multiple valid intervals across a session are accumulated together.
3. **Required Presence Threshold:**
   - The instructor/teacher specifies the required presence duration or percentage threshold for each session (e.g., at least 45 minutes out of a 60-minute lecture).
4. **Session Boundary Rules:**
   - **Early Entry:** Presence before the official session start time does not count toward required session duration.
   - **Late Exit:** Presence after the official session end time is capped at the scheduled session end time.
   - **Missing Exit:** If a student enters but has no corresponding EXIT event when the session finishes, the active interval is automatically closed at the session end time.
5. **Anomaly & Duplicate Handling:**
   - **Duplicate ENTRY:** Successive ENTRY events while an interval is already active are safely debounced/ignored.
   - **Orphaned EXIT:** An EXIT event received without an active or preceding ENTRY transitions the student record into a `REVIEW` state for teacher review.
6. **Final Attendance States:**
   - `PRESENT`: Cumulative presence meets or exceeds the required threshold.
   - `INSUFFICIENT`: Student was detected, but cumulative presence did not meet the required threshold.
   - `ABSENT`: No valid presence recorded during the session.
   - `REVIEW`: Anomalous events detected requiring instructor audit or manual resolution.

## Consequences
- **Positive:**
  - Accurately captures actual lecture engagement and eliminates early-exit proxy bypasses.
  - Transparent state transitions with deterministic rule evaluations and audit logs.
  - Gracefully handles real-world edge cases (missing exit events, duplicate scans).
- **Trade-off:**
  - Requires maintaining interval state machines and reconciliation logic per student per session on the backend.
