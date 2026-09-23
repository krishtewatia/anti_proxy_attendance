# Vision Service to FastAPI Event Contract (Step 3.1)

## Overview
This document specifies the strict API contract between the **Vision Service** (producer) and the **FastAPI Backend** (consumer).

The Vision Service is strictly a **perception layer**. It observes physical movement through a camera, tracks faces across frames, matches biometric embeddings, evaluates virtual boundary crossing, and emits timestamped transit events. It possesses **zero awareness** of courses, class schedules, enrolled student records, attendance thresholds, or session lifecycles.

---

## 1. Permitted vs. Forbidden Fields

### Fields the Vision Service MUST Provide:
| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `event_id` | `UUID / str` | Unique event ID for deduplication and idempotency | `"evt_9b1c2d3e4f5a"` |
| `camera_id` | `str` | Logical identifier of the camera / doorway | `"CAM_ROOM_101_DOOR"` |
| `track_id` | `int` | Sequential tracker ID from ByteTrack | `22` |
| `identity` | `str` | Biometric label from enrolled gallery, or `"UNKNOWN"` | `"person_02"` / `"ST042"` |
| `direction` | `Enum` | Spatial motion event: `ENTRY`, `EXIT`, `UNRESOLVED` | `"ENTRY"` |
| `timestamp` | `ISO 8601 UTC` | Exact time the boundary crossing occurred | `"2026-09-23T14:30:15.820Z"` |
| `evidence` | `Object` | Biometric & tracking confidence metrics | *See Evidence Schema below* |

### Fields the Vision Service is FORBIDDEN to Send:
- ❌ `session_id` (Class sessions are managed by teachers and the backend timetable).
- ❌ `student_id` / `student_name` (The vision service only knows gallery labels like `"person_02"` or biometric token IDs).
- ❌ `attendance_status` (`"PRESENT"`, `"ABSENT"`, `"PARTIAL"`, `"LATE"` are calculated by the backend).
- ❌ `proxy_flag` (Anti-proxy detection requires cross-referencing multiple sessions/cameras).

---

## 2. Event Types (`direction`)

1. **`ENTRY`**:
   - Emitted when a tracked person crosses the virtual boundary line moving from the approach zone (`SIDE_A`) into the room (`SIDE_B`).
2. **`EXIT`**:
   - Emitted when a tracked person crosses the virtual boundary line moving from the room (`SIDE_B`) back into the hallway (`SIDE_A`).
3. **`UNRESOLVED`**:
   - Emitted when a track concludes (expires or exits camera view) without successfully crossing the boundary line, or if trajectory direction could not be reliably determined.
   - Useful for logging anomalous lingerings, door turn-backs, or low-confidence tracks.

---

## 3. Evidence Object Schema

The `evidence` payload allows the backend to assess observation quality, flag marginal recognitions, and audit potential proxy attempts:

```json
{
  "peak_similarity": 0.613,
  "mean_similarity": 0.585,
  "supporting_frames": 5,
  "total_frames": 5,
  "consistency_pct": 100.0,
  "margin_over_runner_up": 0.461,
  "runner_up_identity": "person_03"
}
```

- `peak_similarity`: Highest cosine similarity observed across all frames of the track ($-1.0$ to $1.0$).
- `mean_similarity`: Mean cosine similarity across all supporting frames.
- `supporting_frames`: Number of sampled frames where the face matched `identity`.
- `total_frames`: Total number of sampled frames the track was active.
- `consistency_pct`: Percentage of active track frames voting for `identity` ($0.0$ to $100.0$).
- `margin_over_runner_up`: Difference between `identity`'s mean score and the highest competing candidate's score.
- `runner_up_identity`: Name of the closest competing gallery identity (optional).

---

## 4. Complete JSON Example Payloads

### Example 1: Confirmed Student Entry
```json
{
  "event_id": "evt_d3e4f5a6b7c8",
  "camera_id": "CAM_ROOM_101_DOOR",
  "track_id": 22,
  "identity": "person_02",
  "direction": "ENTRY",
  "timestamp": "2026-09-23T14:30:15.820Z",
  "evidence": {
    "peak_similarity": 0.613,
    "mean_similarity": 0.585,
    "supporting_frames": 5,
    "total_frames": 5,
    "consistency_pct": 100.0,
    "margin_over_runner_up": 0.461,
    "runner_up_identity": "person_03"
  }
}
```

### Example 2: Confirmed Student Exit
```json
{
  "event_id": "evt_e5a6b7c8d9e0",
  "camera_id": "CAM_ROOM_101_DOOR",
  "track_id": 45,
  "identity": "person_02",
  "direction": "EXIT",
  "timestamp": "2026-09-23T15:15:42.110Z",
  "evidence": {
    "peak_similarity": 0.640,
    "mean_similarity": 0.602,
    "supporting_frames": 6,
    "total_frames": 6,
    "consistency_pct": 100.0,
    "margin_over_runner_up": 0.490,
    "runner_up_identity": "person_01"
  }
}
```

### Example 3: Unresolved / Unrecognized Individual
```json
{
  "event_id": "evt_f7a8b9c0d1e2",
  "camera_id": "CAM_ROOM_101_DOOR",
  "track_id": 19,
  "identity": "UNKNOWN",
  "direction": "UNRESOLVED",
  "timestamp": "2026-09-23T14:32:05.400Z",
  "evidence": {
    "peak_similarity": 0.280,
    "mean_similarity": 0.220,
    "supporting_frames": 1,
    "total_frames": 3,
    "consistency_pct": 33.3,
    "margin_over_runner_up": 0.040,
    "runner_up_identity": "person_04"
  }
}
```
