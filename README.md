# AI Face Recognition Attendance System — Single Local Webcam & ERP Integration

[![CI Pipeline](https://github.com/krishtewatia/anti_proxy_attendance/actions/workflows/ci.yml/badge.svg)](https://github.com/krishtewatia/anti_proxy_attendance/actions/workflows/ci.yml)
[![Pre-Commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)](.pre-commit-config.yaml)

A production-grade, privacy-conscious classroom attendance system using edge computer vision (**InsightFace SCRFD + ArcFace**), a high-performance **FastAPI/MongoDB** backend, and a modern **React ERP** portal.

---

## 1. System Overview

The system is designed for **one-time classroom attendance marking** using a single physical camera connected directly to the instructor's laptop:

```text
Laptop Built-in Webcam / USB Phone Webcam / External USB Camera
                             ↓
                 Windows DirectShow / MSMF
                             ↓
              OpenCV cv2.VideoCapture(index)
                             ↓
        InsightFace SCRFD Face Detection (Buffalo_L)
                             ↓
            ArcFace 512-d Feature Extractor
                             ↓
          Multi-Frame Plurality Confirmation
                             ↓
             FastAPI POST /attendance/mark
                             ↓
                  MongoDB Persistence
                             ↓
              Teacher ERP Live Dashboard
```

### Core Attendance Rule:
> **Face Detected → Student Recognized → Marked PRESENT Once per Session**
- **One-Time Attendance**: Each student is marked PRESENT only once per session.
- **Duplicate Prevention**: Subsequent appearances return `already_present` without duplicate records.
- **Unknown Face Rejection**: Unknown or unconfirmed faces are never marked present.
- **Session Auto-Discovery**: The native vision runner automatically detects the teacher's active session.

---

## 2. Architecture & Execution Model

To ensure reliable hardware access to Windows webcams without virtualization friction, the recommended architecture is:

```text
Windows Host
│
├── Physical Webcam (Built-in / USB Phone / External)
│
├── Vision Service (Native Windows Python Process)
│     ├── OpenCV VideoCapture() via DirectShow / MSMF
│     ├── SCRFD + ArcFace Deep Learning Pipeline
│     └── MJPEG Stream Server (http://localhost:8088/preview.mjpg)
│
├── Docker Containers
│     ├── MongoDB 7.0 (Port 27017)
│     ├── FastAPI Backend (Port 8000)
│     └── React Frontend SPA (Port 3000)
│
└── Web Browser (Instructor ERP UI)
```

---

## 3. Quickstart & Startup Lifecycle

### Recommended: One-Click Startup Script
The project includes automated startup and shutdown scripts for Windows:

```powershell
# Start everything (Docker MongoDB, Backend, Frontend + Standby Vision Agent):
powershell -ExecutionPolicy Bypass -File scripts/start_dev.ps1
```
*What this script does:*
1. Starts Docker containers (`anti-proxy-mongodb`, `anti-proxy-backend`, `anti-proxy-frontend`).
2. Waits for FastAPI backend to pass `/health`.
3. Preloads the native Windows Vision Agent (`run_local_webcam.py`) in **Standby Mode** on port 8088.
4. **The physical camera remains completely CLOSED and released** until the teacher starts an attendance session in the ERP portal.

To cleanly stop the system and release all camera and container handles:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/stop_dev.ps1 [-StopDocker]
```

---

### Manual Startup Method

#### Step 1: Start Docker Services
```powershell
docker compose up -d mongodb backend frontend
```
Verify health:
- **Frontend ERP Portal**: [http://localhost:3000](http://localhost:3000)
- **Backend API**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Backend Health**: [http://localhost:8000/health](http://localhost:8000/health)

#### Step 2: Camera Discovery & Hardware Diagnostics
```powershell
# Discover available camera devices:
.\vision-service\.venv\Scripts\python.exe vision-service/list_cameras.py

# Run standalone camera test on index 0:
.\vision-service\.venv\Scripts\python.exe vision-service/test_camera.py --camera-index 0
```

#### Step 3: Run the Native Vision Agent
Launch the vision agent natively on Windows:
```powershell
# Auto-probes available camera (defaults to Standby until session starts):
.\vision-service\.venv\Scripts\python.exe vision-service/run_local_webcam.py
```
- **Live Annotated MJPEG Stream**: [http://localhost:8088/preview.mjpg](http://localhost:8088/preview.mjpg)
- **Telemetry & Status**: [http://localhost:8088/status](http://localhost:8088/status)
- **Control / Reset**: `POST http://localhost:8088/reset`

---

## 4. Automatic Camera Lifecycle

The system enforces a clean hardware ownership lifecycle:

```text
Teacher logs into ERP
        ↓
Teacher selects Class + Subject
        ↓
Teacher clicks "Take Attendance"
        ↓
Backend marks session ACTIVE
        ↓
Vision Agent detects active session within 500ms
        ↓
Vision Agent OPENS physical webcam (DirectShow)
        ↓
Live MJPEG feed starts streaming to Teacher ERP
        ↓
Students stand before webcam → Recognized → Marked PRESENT
        ↓
Teacher clicks "End Attendance & Finalize"
        ↓
Backend marks session FINALIZED
        ↓
Vision Agent detects no active session
        ↓
Vision Agent RELEASES physical webcam cleanly
        ↓
Camera immediately available to other Windows applications
```

---

## 5. Phone as USB Webcam Support

To use an Android or iOS smartphone as the attendance camera:
1. Connect phone to the laptop via **USB cable**.
2. Run standard USB webcam software on phone & PC (e.g., **DroidCam**, **Iriun Webcam**, or **Camo**).
3. The phone camera is exposed to Windows as a standard DirectShow video device.
4. Run `python vision-service/list_cameras.py` to identify its device index (e.g. index `1`).
5. Launch the vision runner targeting that index:
   ```powershell
   python vision-service/run_local_webcam.py --camera-index 1
   ```

---

## 5. End-to-End Classroom Walkthrough

1. **Teacher Login**:
   - Open [http://localhost:3000](http://localhost:3000)
   - Email: `teacher@demo.edu` | Password: `TeacherDevPass123!`
2. **Start Attendance Session (Screen 1)**:
   - Select Class (`DS-B`) and Subject (`Machine Learning`)
   - Click **Take Attendance**
   - Session status becomes `ACTIVE`; auto-roster of students is loaded as `ABSENT`.
3. **Live Attendance Scanning (Screen 2)**:
   - Viewport connects to `http://localhost:8088/preview.mjpg`.
   - The vision runner automatically syncs with the active session.
   - Enrolled students step in front of the camera:
     - ArcFace recognizes identity $\to$ Backend marks student **`PRESENT`**.
     - Student row updates live in the teacher's roster.
     - Repeat sightings are recognized without duplicate entries.
4. **Finalize Attendance (Screen 3)**:
   - Click **End Attendance & Finalize**.
   - Attendance session is finalized; remaining unscanned students remain `ABSENT`.
   - Teacher can review attendance percentage and click **Export CSV** to download `Machine_Learning_attendance_<id>.csv`.

---

## 6. Pre-configured Credentials

| Role | Email | Password | Assigned Classes |
| :--- | :--- | :--- | :--- |
| **Admin** | `admin@system.local` | `AdminDevPass123!` | System Administrator |
| **Teacher** | `teacher@demo.edu` | `TeacherDevPass123!` | DS-B, CS-A |
| **Student** | `rahul@demo.edu` | `StudentDevPass123!` | DS-B (Rahul Sharma, DS202601) |
| **Student** | `aman@demo.edu` | `StudentDevPass123!` | DS-B (Aman Kumar, DS202602) |
| **Student** | `priya@demo.edu` | `StudentDevPass123!` | DS-B (Priya Singh, DS202603) |
| **Student** | `krish@demo.edu` | `StudentDevPass123!` | DS-B (Krish Tewatia, DS202604) |

---

## 7. Verification & Automated Test Suites

### Run Backend Tests:
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase2_multi_role_e2e.py tests/test_one_time_demo_e2e.py
```
*(All pass with 100% success).*

### Run Vision Service Tests:
```powershell
cd vision-service
.\.venv\Scripts\python.exe -m pytest -q
```
*(131 passed).*

### Run Frontend Build & Tests:
```powershell
cd frontend
npm run test
npm run build
```
*(All 12 test suites pass, TypeScript build succeeds cleanly).*

### Run Physical Hardware Integration Verification:
```powershell
python scripts/verify_physical_camera_integration.py
```

---

## 8. Troubleshooting

| Issue | Resolution |
| :--- | :--- |
| **Camera opened: NO** | Ensure another application (Teams, Zoom, Camera app) is not holding exclusive access. Check Windows Settings > Privacy & Security > Camera. |
| **Camera stream interrupted** | Verify USB cable connection or select correct index with `python vision-service/list_cameras.py`. |
| **Camera unavailable overlay in UI** | Ensure native vision runner is active on port 8088 (`python vision-service/run_local_webcam.py`). |
| **No active session found** | Attendance events are held until a teacher clicks "Take Attendance" in the ERP UI. |
