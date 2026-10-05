# Comprehensive Investigation Report: Requirement R1 (Clean Demo Database Seeding & Biometrics)

**Investigator**: Survey Explorer 1 (`survey_explorer_1`)
**Mission**: Investigate Database, Auth, Recognition Benchmark Biometrics, and Seeding Architecture for Requirement R1
**Timestamp**: 2026-10-03T10:15:00Z
**Workspace Root**: `c:\Users\hp\Downloads\anti_proxy_project`

---

## 1. Executive Summary

Requirement R1 mandates creating `scripts/seed_clean_demo.py` to wipe all synthetic mock data (`alice`, `bob`, `charlie`, dummy teachers, and mathematical mock embeddings `[0.05 * (i % 7)]`) and initialize a pristine environment tailored for a 4-person live demo:
- **Admin**: `admin@system.local` (`AdminDevPass123!`)
- **Teacher**: `teacher@demo.edu` (`TeacherDevPass123!`)
- **4 Students**: `student1` through `student4` (IDs: `STU_001` through `STU_004`), mapped to CV identities `person_01` through `person_04`.
- **Authentic Biometrics**: Extracted from `vision-service/tests/recognition_benchmark/person_0{1..4}/` via InsightFace (`buffalo_l`), L2-normalized 512-dimensional feature vectors stored in `biometric_profiles`.
- **Doorway Camera**: `CAM_ROOM_101_DOOR` in `ROOM_101` with **vertical** dividing line configuration (`p1: [0.5, 0.0]`, `p2: [0.5, 1.0]`, `entry_side: "SIDE_A"`).
- **Active Demo Session**: `sess_demo_cs101` ("CS-101 Introduction to Computer Science") in `ROOM_101` owned by `teacher@demo.edu` spanning the current day, enrolling all 4 students in `session_rosters`.

Our investigation audited all configuration files, MongoDB databases across containers, password verification routines, recognition benchmark images, and live InsightFace pipelines. All findings, schema constraints, and script specifications are documented below.

---

## 2. Detailed Investigation Findings

### 2.1 MongoDB Connection & Network Configuration Across Services

| Component | Host / Port | Environment Variables | User / Auth Database | URI Construction |
|---|---|---|---|---|
| **MongoDB Service** | `127.0.0.1:27017` (Host mapping), `mongodb:27017` (Docker bridge) | `MONGO_INITDB_ROOT_USERNAME=admin`<br>`MONGO_INITDB_ROOT_PASSWORD=secure_root_mongo_dev_password_12345`<br>`MONGO_APP_USERNAME=antiproxy_user`<br>`MONGO_APP_PASSWORD=secure_app_mongo_dev_password_12345`<br>`DATABASE_NAME=anti_proxy_attendance` | App User: `antiproxy_user`<br>AuthSource: `anti_proxy_attendance`<br>Role: `readWrite` | Initialized via `docker/init-mongo.js` |
| **FastAPI Backend** | `anti-proxy-backend:8000` | `MONGODB_URL=mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@mongodb:27017/anti_proxy_attendance?authSource=anti_proxy_attendance`<br>`DATABASE_NAME=anti_proxy_attendance`<br>`EVENTS_COLLECTION=attendance_events` | Uses `motor.motor_asyncio.AsyncIOMotorClient`<br>Fallback: `mongomock_motor.AsyncMongoMockClient` | `backend/app/database/mongodb.py:23` |
| **Vision Service** | `anti-proxy-vision-service:8088` | `BACKEND_URL=http://backend:8000`<br>`VISION_SERVICE_API_KEY=test_vision_api_key_for_smoke_test_12345`<br>`CAMERA_ID=CAM_ROOM_101_DOOR` | **No direct MongoDB connection**. Ingests via HTTP `POST /api/v1/events` with header `X-API-Key: test_vision_api_key_for_smoke_test_12345` | `vision-service/run_webrtc_camera.py:138` |
| **Host Scripts** (`seed_clean_demo.py`) | Connects from Host to `127.0.0.1:27017` | Loads `.env` via `python-dotenv`:<br>`MONGODB_URL=mongodb://localhost:27017`<br>`MONGO_APP_USERNAME=antiproxy_user`<br>`MONGO_APP_PASSWORD=secure_app_mongo_dev_password_12345`<br>`DATABASE_NAME=anti_proxy_attendance` | Authenticates against `anti_proxy_attendance` | `mongodb://antiproxy_user:secure_app_mongo_dev_password_12345@localhost:27017/anti_proxy_attendance?authSource=anti_proxy_attendance` |

**Verification Result**:
A test ping from host Python via `pymongo.MongoClient` returned `{'ok': 1.0}`, proving direct read/write access from host scripts to the running MongoDB container.

---

### 2.2 Backend Schemas, Models, Collections & Index Requirements

The application relies on 6 core collections in MongoDB (`anti_proxy_attendance`):

#### 1. `users` Collection
- **File**: `backend/app/database/users.py`, `backend/app/schemas/auth.py`
- **Index**: Unique index on `email` (`uq_users_email`)
- **Document Structure**:
  ```json
  {
    "user_id": "user_admin_demo",
    "email": "admin@system.local",
    "password_hash": "$2b$12$...",
    "role": "ADMIN",
    "is_active": true,
    "created_at": "2026-10-03T10:00:00Z"
  }
  ```
  For students, additional fields `student_id` (e.g. `"STU_001"`) and `name` (e.g. `"student1"`) are stored in `users`.

#### 2. `student_profiles` Collection
- **File**: `backend/app/database/student_profiles.py`, `backend/app/schemas/student.py`
- **Indexes**:
  - Unique index on `user_id` (`uq_student_profiles_user_id`)
  - Unique index on `identity` (`uq_student_profiles_identity`)
- **Document Structure**:
  ```json
  {
    "user_id": "user_stu_001",
    "identity": "person_01",
    "created_at": "2026-10-03T10:00:00Z",
    "updated_at": "2026-10-03T10:00:00Z"
  }
  ```
- **Architectural Link**: Resolves authenticated user (`user_id`) to perceptual computer vision identity (`identity: person_01`). Used in `GET /api/v1/students/directory` to associate students with biometrics.

#### 3. `biometric_profiles` Collection
- **File**: `backend/app/database/biometric_profiles.py`, `backend/app/schemas/biometric.py`
- **Document Structure**:
  ```json
  {
    "identity": "person_01",
    "mean_embedding": [0.01148997, 0.06984408, ...], // Exactly 512 floats
    "sample_count": 3,
    "quality_score": 0.95,
    "enrolled_by": "seed_system",
    "created_at": "2026-10-03T10:00:00Z",
    "updated_at": "2026-10-03T10:00:00Z"
  }
  ```
- **Validation**: Schema `BiometricEnrollRequest` enforces `min_length=512, max_length=512`. Vectors must be L2-normalized unit vectors ($\|v\| = 1.0$).

#### 4. `session_rosters` Collection
- **File**: `backend/app/database/session_roster.py`, `backend/app/schemas/session_roster.py`
- **Document Structure**:
  ```json
  {
    "session_id": "sess_demo_cs101",
    "identities": ["person_01", "person_02", "person_03", "person_04"],
    "created_at": "2026-10-03T10:00:00Z",
    "updated_at": "2026-10-03T10:00:00Z"
  }
  ```
- **Crucial Note**: The backend queries `session_rosters` by `session_id`. Note that an older collection `session_roster` (singular) exists in some legacy test cleanups; both must be purged during wipe.

#### 5. `sessions` Collection
- **File**: `backend/app/database/sessions.py`, `backend/app/schemas/session.py`
- **Document Structure**:
  ```json
  {
    "session_id": "sess_demo_cs101",
    "course_name": "CS-101 Introduction to Computer Science",
    "classroom_id": "ROOM_101",
    "start_time": "2026-10-03T00:00:00Z",
    "end_time": "2026-10-03T23:59:59Z",
    "required_presence_percentage": 75.0,
    "status": "ACTIVE",
    "created_by": "user_teacher_demo",
    "created_at": "2026-10-03T10:00:00Z",
    "updated_at": "2026-10-03T10:00:00Z"
  }
  ```
- **CRITICAL OWNERSHIP REQUIREMENT**:
  In `backend/app/api/dependencies/auth.py:104`:
  ```python
  if session.get("created_by") != current_user.get("user_id"):
      raise HTTPException(status_code=403, detail="Forbidden: You do not own this session")
  ```
  `sessions.created_by` **MUST** equal the exact `user_id` of `teacher@demo.edu`. Otherwise, the Teacher Dashboard and `GET /api/v1/sessions/sess_demo_cs101/live-snapshot` fail with HTTP 403 Forbidden!
- **Session Time Window**: Must cover current day (`start_time <= now <= end_time`) so `find_active_session_for_classroom("ROOM_101", timestamp)` resolves incoming events to `sess_demo_cs101`.

#### 6. `cameras` Collection
- **File**: `backend/app/database/cameras.py`, `backend/app/schemas/camera.py`
- **Index**: Unique index on `camera_id` (`uq_cameras_camera_id`)
- **Document Structure**:
  ```json
  {
    "camera_id": "CAM_ROOM_101_DOOR",
    "classroom_id": "ROOM_101",
    "role": "BOTH",
    "source_type": "PHONE",
    "rtsp_url": null,
    "secret_reference": null,
    "enabled": true,
    "boundary_config": {
      "p1": [0.5, 0.0],
      "p2": [0.5, 1.0],
      "entry_side": "SIDE_A",
      "deadband_pixels": 4.0
    },
    "status": "CONNECTED",
    "last_seen": "2026-10-03T10:00:00Z",
    "fps": 15.0,
    "notes": "Doorway camera monitoring ROOM_101 entry and exit",
    "created_at": "2026-10-03T10:00:00Z",
    "updated_at": "2026-10-03T10:00:00Z"
  }
  ```
- **Boundary Configuration Analysis**:
  In `vision-service/pipeline/live_cv_pipeline.py:63`:
  When $x_1 = x_2 = 0.5$, `classify_point_side` treats the line as **vertical**:
  - $c_x < 0.5 - \text{deadband}$: classifies as `SIDE_A` (Left side / approach)
  - $c_x > 0.5 + \text{deadband}$: classifies as `SIDE_B` (Right side / inside)
  - Crossing Left-to-Right (Side A $\to$ Side B) emits `ENTRY`.
  - Crossing Right-to-Left (Side B $\to$ Side A) emits `EXIT`.
  Previous seed script incorrectly had horizontal configuration `[0.0, 0.5] -> [1.0, 0.5]`.

---

### 2.3 Password Authentication & Hashing Architecture

- **Hashing Algorithm**: `bcrypt` (version 5.0.0 on host, bcrypt in backend).
- **Implementation**: `backend/app/security/passwords.py`:
  - `hash_password(pwd)`: Generates `bcrypt.gensalt()`, hashes UTF-8 bytes, returns decoded UTF-8 string.
  - `verify_password(plain, hashed)`: `bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))`.
- **Live Login Test Verification**:
  - Tested `POST /api/v1/auth/login` with `{"email": "admin@system.local", "password": "AdminDevPass123!"}`:
    **Result**: `HTTP 200 OK`, returned JWT with `role: "ADMIN"`.
  - Tested `POST /api/v1/auth/login` with `{"email": "teacher@demo.edu", "password": "TeacherDevPass123!"}`:
    **Result**: `HTTP 200 OK`, returned JWT with `role: "TEACHER"`.
- **Seeding Hash Generation**:
  `scripts/seed_clean_demo.py` can generate bcrypt hashes directly on the host using `bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")`.

---

### 2.4 Recognition Benchmark Reference Images

Images located in `vision-service/tests/recognition_benchmark/person_0{1..4}/`:

| Subject | Files | Format | Dimensions (W x H) | Status / Quality |
|---|---|---|---|---|
| `person_01` | `image_01.jpg`<br>`image_02.jpg`<br>`image_03.jpg` | JPEG<br>JPEG<br>JPEG | 2026 x 2146<br>4032 x 2268<br>3472 x 4624 | 3 images. High resolution, passes SCRFD detection and quality gates. |
| `person_02` | `image_01.jpg`<br>`image_02.jpg`<br>`image_03.jpeg`<br>`image_04.jpeg`<br>`image_05.jpeg` | JPEG<br>JPEG<br>JPEG<br>JPEG<br>JPEG | 2197 x 3135<br>1555 x 1561<br>960 x 1280<br>960 x 1280<br>960 x 1280 | 5 images. High clarity, multiple angles. |
| `person_03` | `image_01.jpeg`<br>`image_02.jpeg`<br>`image_03.jpeg` | JPEG<br>JPEG<br>JPEG | 813 x 1280<br>960 x 1280<br>960 x 1280 | 3 images. Crisp portrait frames. |
| `person_04` | `image_01.jpeg`<br>`image_02.jpeg`<br>`image_03.jpeg` | JPEG<br>JPEG<br>JPEG | 960 x 1280<br>960 x 1280<br>960 x 1280 | 3 images. Crisp portrait frames. |

All subjects have between 3 and 5 images ($3 \le N \le 5$), fully satisfying the enrollment requirement in `vision-service/enrollment/engine.py`.

---

### 2.5 InsightFace Model Loading & Feature Extraction Architecture

- **Model**: InsightFace `buffalo_l` (detection via SCRFD, feature extraction via ArcFace ResNet50/100).
- **Inference Pipeline**:
  `vision-service/pipeline/live_cv_pipeline.py:100-148`:
  1. For each image in `tests/recognition_benchmark/<person_id>/`, run `app.get(img)` or `check_image_quality(img, app=app)`.
  2. Extract 512-dimensional embedding vector from best detected face.
  3. Weight each embedding: $w_i = \text{det\_score} \cdot \ln(1 + \max(\text{sharpness}, 0))$.
  4. Compute weighted mean embedding: $\mathbf{e}_{\text{raw}} = \sum \bar{w}_i \mathbf{e}_i$.
  5. Apply L2 normalization:
     $$\mathbf{e}_{\text{unit}} = \frac{\mathbf{e}_{\text{raw}}}{\|\mathbf{e}_{\text{raw}}\|_2 + 10^{-10}}$$
     This yields an authentic 512-d unit vector ($\|\mathbf{e}\| = 1.0$).
- **Live Verification**:
  Executed `load_gallery` inside the `anti-proxy-vision-service` container on `tests/recognition_benchmark`. All 4 identities extracted successfully with length 512 and unit norm 1.0:
  - `person_01`: `[0.01148997, 0.06984408, 0.03379063, -0.03705370, -0.05405608, ...]`
  - `person_02`: `[0.05001995, 0.02011990, 0.05125619, 0.05571456, -0.04140614, ...]`
  - `person_03`: `[0.04240012, -0.03312147, 0.06319043, 0.07449853, -0.11854449, ...]`
  - `person_04`: `[-0.01013403, 0.08096212, 0.00686668, 0.09222218, 0.02009514, ...]`

The full vectors have been captured into `benchmark_embeddings.json` in our directory.

---

### 2.6 Current Database Contamination & Audit of Old Seeding Scripts

Inspection of MongoDB revealed substantial contamination from previous automated tests and mock seeds:
- `users`: **161 documents** (includes dummy `alice`, `bob`, `charlie`, and over 150 automated test user accounts like `teacher_smoke_*`, `teacher_att_*`, etc.).
- `sessions`: **76 documents** (historical sessions from test runs).
- `session_rosters`: **38 documents**.
- `student_profiles`: **22 documents**.
- `biometric_profiles`: **4 documents**, all containing mathematical mock embeddings `[0.05 * (i % 7)]`.
- `attendance_events`: **21 documents**.
- `cameras`: 1 document with incorrect horizontal boundary line `[0.0, 0.5] -> [1.0, 0.5]`.

**Audit of `scripts/seed_demo.py`**:
1. Does not wipe existing collections; performs upserts/skips if users exist.
2. Uses synthetic names (`Alice Smith`, `Bob Jones`, `Charlie Davis`) instead of the required clean demo students (`student1` - `student4`).
3. Uses synthetic mathematical mock vectors `0.05 * (i % 7)` instead of running InsightFace on benchmark images.
4. Uses horizontal boundary line instead of vertical.
5. Uses dynamic date-based session IDs `sess_demo_YYYYMMDD` instead of canonical `sess_demo_cs101`.

---

## 3. Specification for `scripts/seed_clean_demo.py`

To satisfy all Acceptance Criteria for Requirement R1, `scripts/seed_clean_demo.py` must follow this exact specification:

### 3.1 Execution Strategy & Arguments
- Standalone execution: `python scripts/seed_clean_demo.py`
- Arguments:
  - `--mongo-url`: Defaults to `MONGODB_URL` from `.env` or `mongodb://localhost:27017`
  - `--db-name`: Defaults to `DATABASE_NAME` or `anti_proxy_attendance`
  - `--wipe`: Boolean flag (default `True`) to wipe existing test/demo data before seeding
  - `--student-password`: Defaults to `StudentDevPass123!`
  - `--teacher-password`: Defaults to `TeacherDevPass123!`
  - `--admin-password`: Defaults to `AdminDevPass123!`

### 3.2 MongoDB Purge Logic
When `--wipe` is enabled:
```python
collections_to_wipe = [
    "users",
    "student_profiles",
    "biometric_profiles",
    "session_rosters",
    "session_roster",
    "sessions",
    "cameras",
    "attendance_events",
    "attendance_records",
    "attendance_corrections",
]
for coll in collections_to_wipe:
    db[coll].delete_many({})
```
Using `delete_many({})` leaves existing indexes intact while ensuring the database starts completely clean.

### 3.3 Multi-Tier Authentic Biometrics Extraction
The script must extract genuine 512-d unit vectors using a robust multi-tier fallback:
1. **Tier 1 (Direct Python Import)**:
   Attempt `from pipeline.live_cv_pipeline import create_face_analysis, load_gallery`. If available, compute embeddings directly.
2. **Tier 2 (Docker Container Exec)**:
   If Tier 1 raises `ImportError` (e.g. on host Python without ONNX/InsightFace), execute:
   `docker exec anti-proxy-vision-service python -c "from pipeline.live_cv_pipeline import create_face_analysis, load_gallery; ..."` and parse JSON stdout.
3. **Tier 3 (Verified Static Authentic Embedding Constants)**:
   If Docker is unreachable, fall back to the exact pre-computed 512-d unit vectors generated by InsightFace `buffalo_l` on `recognition_benchmark/person_0{1..4}/`. This guarantees 100% reliable execution under any environment without falling back to mock math embeddings.

### 3.4 Seed Records Definition

#### A. Users (Exactly 6 Users)
1. **Admin**:
   - `user_id`: `"user_admin_demo"`
   - `email`: `"admin@system.local"`
   - `password_hash`: bcrypt hash of `"AdminDevPass123!"`
   - `role`: `"ADMIN"`
   - `is_active`: `True`
2. **Teacher**:
   - `user_id`: `"user_teacher_demo"`
   - `email`: `"teacher@demo.edu"`
   - `password_hash`: bcrypt hash of `"TeacherDevPass123!"`
   - `role`: `"TEACHER"`
   - `name`: `"Demo Teacher"`
   - `is_active`: `True`
3. **Students 1-4**:
   - For $i \in \{1, 2, 3, 4\}$:
     - `user_id`: `f"user_student{i}"`
     - `email`: `f"student{i}@demo.edu"`
     - `password_hash`: bcrypt hash of `"StudentDevPass123!"`
     - `role`: `"STUDENT"`
     - `student_id`: `f"STU_00{i}"`
     - `name`: `f"student{i}"`
     - `is_active`: `True`

#### B. Student Profiles (Exactly 4 Documents)
- `{"user_id": "user_student1", "identity": "person_01"}`
- `{"user_id": "user_student2", "identity": "person_02"}`
- `{"user_id": "user_student3", "identity": "person_03"}`
- `{"user_id": "user_student4", "identity": "person_04"}`

#### C. Biometric Profiles (Exactly 4 Documents)
- For each identity in `["person_01", "person_02", "person_03", "person_04"]`:
  - `identity`: identity
  - `mean_embedding`: genuine 512-d float array ($\|\mathbf{e}\| = 1.0$)
  - `sample_count`: 3 (or 5 for person_02)
  - `quality_score`: 0.95
  - `enrolled_by`: `"user_teacher_demo"`

#### D. Camera Registry (Exactly 1 Document)
- `camera_id`: `"CAM_ROOM_101_DOOR"`
- `classroom_id`: `"ROOM_101"`
- `role`: `"BOTH"`
- `source_type`: `"PHONE"`
- `enabled`: `True`
- `boundary_config`:
  ```json
  {
    "p1": [0.5, 0.0],
    "p2": [0.5, 1.0],
    "entry_side": "SIDE_A",
    "deadband_pixels": 4.0
  }
  ```
- `status`: `"CONNECTED"`
- `fps`: `15.0`

#### E. Active Demo Session (Exactly 1 Document)
- `session_id`: `"sess_demo_cs101"`
- `course_name`: `"CS-101 Introduction to Computer Science"`
- `classroom_id`: `"ROOM_101"`
- `start_time`: today at `00:00:00 UTC` (or `now - timedelta(hours=2)`)
- `end_time`: today at `23:59:59 UTC` (or `now + timedelta(hours=12)`)
- `required_presence_percentage`: `75.0`
- `status`: `"ACTIVE"`
- `created_by`: `"user_teacher_demo"`

#### F. Session Roster (Exactly 1 Document)
- `session_id`: `"sess_demo_cs101"`
- `identities`: `["person_01", "person_02", "person_03", "person_04"]`

### 3.5 Final Console Output Format
The script prints a clean summary table with:
- Target Database & MongoDB URI
- Wipe Status
- Credentials block:
  - Admin: `admin@system.local` / `AdminDevPass123!`
  - Teacher: `teacher@demo.edu` / `TeacherDevPass123!`
  - Student 1: `student1@demo.edu` (`STU_001` -> `person_01`) / `StudentDevPass123!`
  - Student 2: `student2@demo.edu` (`STU_002` -> `person_02`) / `StudentDevPass123!`
  - Student 3: `student3@demo.edu` (`STU_003` -> `person_03`) / `StudentDevPass123!`
  - Student 4: `student4@demo.edu` (`STU_004` -> `person_04`) / `StudentDevPass123!`
- Registered Camera: `CAM_ROOM_101_DOOR` (Vertical threshold $x = 0.5$)
- Active Demo Session: `sess_demo_cs101` in `ROOM_101`
- Enrolled Roster: `person_01`, `person_02`, `person_03`, `person_04`

---

## 4. Acceptance Criteria Checklist & Verification Strategy

| Criterion | Target Metric | Verification Method |
|---|---|---|
| Zero errors execution | Exit code 0 | Run `python scripts/seed_clean_demo.py` from workspace root |
| Wiped collections count | Exactly 6 users, 4 student profiles, 4 biometric profiles, 1 camera, 1 session, 1 roster | Query MongoDB collections via pymongo/mongosh and assert exact document counts |
| Authentic 512-d embeddings | $L_2$ norm = 1.0, length = 512, cosine similarity $> 0.99$ to buffalo_l benchmark output | Assert `len(doc["mean_embedding"]) == 512` and compare against `tests/recognition_benchmark` |
| Admin / Teacher Login | HTTP 200 with JWT bearer token | `POST /api/v1/auth/login` for `admin@system.local` and `teacher@demo.edu` |
| Teacher session ownership | HTTP 200 on live snapshot (not 403) | `GET /api/v1/sessions/sess_demo_cs101/live-snapshot` using Teacher JWT |
| Event Resolution | Associating events to `sess_demo_cs101` | `POST /api/v1/events` for `CAM_ROOM_101_DOOR` returns `session_id: "sess_demo_cs101"` |
