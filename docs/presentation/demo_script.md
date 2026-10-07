# Live Demonstration Script: Step-by-Step Walkthrough

**Demo Duration**: ~5–7 minutes
**Target Audience**: Project Reviewers, Faculty Evaluators, Department Leadership
**Core Objective**: Demonstrate the complete lifecycle of anti-proxy attendance tracking—from session creation and edge camera ingestion to live presence state transitions and finalized audit reports.

---

## 1. Pre-Flight Demonstration Checklist

Before beginning the live presentation:
```bash
# 1. Start the Docker Compose stack (or verify running containers):
docker compose up -d

# 2. Seed fresh demo accounts, classroom LH-101, and camera CAM_ROOM_101_DOOR:
python scripts/seed_demo.py --non-interactive

# 3. Confirm services are reachable:
#    Frontend: http://localhost:3000
#    Backend Docs: http://localhost:8000/docs
#    WebRTC Streamer: http://localhost:8088
```

---

## 2. Demonstration Scene Sequence

### Scene 1: System Login & Session Creation
- **Action**: Open [http://localhost:3000](http://localhost:3000) in browser. Log in as:
  - **Email**: `teacher@demo.edu`
  - **Password**: `TeacherSecurePass123!`
- **Presenter Dialogue**:
  > *"Welcome everyone. I'm logged in as Professor Example on the Anti-Proxy Attendance portal. Let's look at today's lecture: Computer Science 101, scheduled in Lecture Hall LH-101. The university policy requires students to be physically present for at least 75% of class time to receive credit."*
- **Action**: Click into **CS-101 Session Details**.
- **Visual on Screen**: Roster table displays enrolled students (e.g., Alice and Bob) in gray badges: `State: NOT_SEEN`, `Presence: 0 min (0%)`, `Projected: ABSENT`.

---

### Scene 2: Camera Stream Activation (Edge Ingestion)
- **Action**: Open [http://localhost:8088](http://localhost:8088) on a mobile device on the local network (or a secondary browser window pointing to a webcam/test video). Allow camera permissions.
- **Presenter Dialogue**:
  > *"At the doorway of LH-101, we have an edge camera node connected via WebRTC. Notice the virtual calibrated boundary line drawn across the doorway with a 14-pixel deadband. The edge vision pipeline is running ByteTrack with Kalman filtering and InsightFace ArcFace feature extraction entirely locally."*
- **Visual on Screen**: Video feed with virtual boundary line overlay. Terminal or camera log shows `Camera worker active on CAM_ROOM_101_DOOR`.

---

### Scene 3: Student Entry & Sub-Second 3-Vote Confirmation
- **Action**: A student (e.g., Alice) walks across the virtual doorway into the classroom.
- **Presenter Dialogue**:
  > *"Watch closely as Alice walks through the entrance. Notice the bounding box locks onto her face. ByteTrack maintains Track ID #42 as she moves. In less than one second, ArcFace extracts 512-dimensional embeddings across consecutive frames. Our evidence accumulator requires 3 consistent votes with cosine similarity exceeding 0.50 and a runner-up margin greater than 0.15."*
- **Visual on Screen**:
  - The vision service detects the transit from `SIDE_A` through the deadband to `SIDE_B`.
  - Dispatches `ENTRY` event authenticated with `X-Camera-Token`.
  - On the Teacher's Dashboard, Alice's row flashes green:
    - **State**: **`INSIDE`**
    - **Last Event**: `10:02:15 AM (ENTRY)`
    - **Live Timer**: Active and incrementing every second.

---

### Scene 4: Student Temporary Exit (Hallway Break)
- **Action**: Alice steps out of the classroom to take a phone call (crosses from `SIDE_B` to `SIDE_A`).
- **Presenter Dialogue**:
  > *"Unlike traditional RFID or static scanners where a student taps and leaves, our system tracks transit dynamically. Alice has just stepped out into the hallway. The camera detects the reverse boundary crossing and dispatches an EXIT event."*
- **Visual on Screen**:
  - Alice's row updates to an amber badge: **`OUTSIDE`**.
  - Alice's presence counter **pauses** at her accumulated time (e.g., 18 minutes).
  - The feed clearly documents that attendance time does not accumulate while outside.

---

### Scene 5: Student Re-Entry & Presence Resumption
- **Action**: Alice re-enters the classroom 5 minutes later.
- **Presenter Dialogue**:
  > *"When Alice returns, the state machine smoothly registers her second ENTRY. Notice that our pipeline does not drop or duplicate her previous time; it resumes accumulating exactly from where she left off."*
- **Visual on Screen**:
  - Alice's row transitions back to green **`INSIDE`**.
  - Total presence timer resumes incrementing.

---

### Scene 6: Session Finalization & 75% Rule Enforcement
- **Action**: The teacher clicks the blue **Finalize Session** button.
- **Presenter Dialogue**:
  > *"The lecture is now over. The teacher finalizes the session. Behind the scenes, the FastAPI Presence Engine sums Alice's discrete presence intervals and compares her ratio against the 75% course threshold."*
- **Visual on Screen**:
  - Confirmation modal appears: *"Finalize Session: This will calculate final attendance and lock the session against further modifications."*
  - Teacher confirms.
  - Finalized table renders:
    - **Alice**: `52.5 min / 60 min` $\rightarrow$ **87.5% Presence** $\rightarrow$ **`PRESENT`** (Green badge).
    - **Bob**: `0 min / 60 min` $\rightarrow$ **0.0% Presence** $\rightarrow$ **`ABSENT`** (Red badge).

---

### Scene 7: Teacher Manual Override & Immutable Audit Log
- **Action**: Teacher clicks **Override** on Bob's record, selecting `Status: PRESENT` and typing justification: *"Attended via approved remote video conference due to illness"*.
- **Presenter Dialogue**:
  > *"In real university environments, exceptions happen. A teacher can manually correct attendance, but transparency is non-negotiable: a justification reason is strictly required, and the modification is immediately recorded in our tamper-evident audit log."*
- **Action**: Navigate to **Audit Trail** in the navigation bar.
- **Visual on Screen**: Immutable audit table shows:
  - **Timestamp**: `Just now`
  - **Actor**: `teacher@demo.edu`
  - **Action**: `ATTENDANCE_OVERRIDE`
  - **Previous**: `ABSENT` $\rightarrow$ **New**: `PRESENT`
  - **Justification**: *"Attended via approved remote video conference due to illness"*.

---

## 3. Concluding Remarks
> *"To summarize: By shifting from a momentary kiosk scan to continuous edge transit tracking, we mathematically eliminate buddy punching, automate 100% of attendance bookkeeping, protect student privacy by never storing raw photos, and provide complete administrative auditability."*
