# Load test results

`scripts/load_test.py`: one period, four sections at once (4 teachers, 280
students), 120 s of camera frames per session (640x480, one frame in flight per
camera, pictures with no faces), against a throwaway local copy of the stack.
Measured 27 Oct 2026. Pages stay fast in every run; recognition is the limit.

| Run | Vision CPU | Frames sent / skipped | Answer p50 | Answer p95 | Failed |
|---|---|---:|---:|---:|---:|
| Steady, worst case (26 Oct) | 1.0 vCPU | 172 / 0 | 2.85 s | 4.49 s | 2 |
| Steady, production-like | 1.5 + backend 0.5 = 2 vCPU | 233 / 0 | 2.00 s | 3.29 s | 0 |
| Doorway with frame gate, all doors busy at the same moments | 2 vCPU | 201 / 495 | 1.55 s | 3.80 s | 4 |
| **Doorway with frame gate, doors a quarter cycle apart** | 2 vCPU | 236 / 578 | **1.39 s** | **2.41 s** | 0 |

* "Steady": every camera sends all the time (the page before the frame gate).
* "Doorway": a new student every second for 4 s in every 10 s, then nobody
  new; the page skips frames with nothing new (frontend/src/utils/frameGate.ts).
* Target: answer p95 under 1.5 s. Not met in any run; the typical answer
  (p50) is under 1.5 s with the gate when the four doors are not all busy at
  the same moment.
* The gate skips about 70% of frames: much less CPU (and CPU credits) used, and
  the vision service has spare time between arrivals. It cannot help when all
  four doors are busy at once: then four cameras share about two answers a
  second.

Below: the full output of the two production-like runs.


Run 2026-10-27 05:44 UTC against the local stack (production-like: vision 1.5 vCPU + backend 0.5 vCPU = the t3.small's 2 vCPU).

Scenario: steady (every camera sends continuously, as before the frame gate).

One period, four sections at once: 4 teachers, 280 students, 120 s of frames per session (640x480, one in flight per camera, no faces). Wall time 127 s.

Each camera got an answer 0.49 times a second on average.

| Call | Count | p50 (s) | p95 (s) | max (s) | 4xx | 5xx/failed |
|---|---:|---:|---:|---:|---:|---:|
| frame | 233 | 2.000 | 3.288 | 4.777 | 0 | 0 |
| student: dashboard | 280 | 0.029 | 0.192 | 0.663 | 0 | 0 |
| student: me | 280 | 0.019 | 0.091 | 0.296 | 0 | 0 |
| student: setup | 280 | 0.019 | 0.098 | 0.285 | 0 | 0 |
| student: subjects | 280 | 0.042 | 0.261 | 0.786 | 0 | 0 |
| teacher: class overview | 4 | 0.085 | 0.121 | 0.121 | 0 | 0 |
| teacher: dashboard | 8 | 0.024 | 0.050 | 0.050 | 0 | 0 |
| teacher: end session | 4 | 0.028 | 0.113 | 0.113 | 0 | 0 |
| teacher: hand mark | 80 | 0.066 | 0.102 | 0.156 | 0 | 0 |
| teacher: open round | 8 | 0.446 | 0.843 | 0.843 | 0 | 0 |
| teacher: register csv | 4 | 0.072 | 0.094 | 0.094 | 0 | 0 |
| teacher: session sheet | 4 | 0.105 | 0.110 | 0.110 | 0 | 0 |
| teacher: start | 4 | 0.072 | 0.101 | 0.101 | 0 | 0 |
| teacher: start from slot | 4 | 0.515 | 0.617 | 0.617 | 0 | 0 |

Peak per container during the run:

| Container | CPU % | Memory |
|---|---:|---|
| antiproxy-lt-backend | 51 | 92.5MiB / 640MiB |
| antiproxy-lt-frontend | 4 | 12.7MiB / 128MiB |
| antiproxy-lt-mongodb | 50 | 392.4MiB / 512MiB |
| antiproxy-lt-vision-service | 154 | 819.8MiB / 1GiB |

Targets: p95 frame < 1.5 s, p95 of every page call < 1.0 s, no 5xx.
**Result: NOT MET** (frame p95 3.29 s, slowest page p95 0.84 s, 0 failed).

Made-up data with the prefix `lt_` was added for the run and removed afterwards.


Run 2026-10-27 05:50 UTC against the local stack (production-like: vision 1.5 vCPU + backend 0.5 vCPU = the t3.small's 2 vCPU).

Scenario: doorway (a new student every second for 4 s in every 10 s, the four doors a quarter cycle apart; the page skips unchanged frames); frames sent 236, skipped 578.

One period, four sections at once: 4 teachers, 280 students, 120 s of frames per session (640x480, one in flight per camera, no faces). Wall time 130 s.

Each camera got an answer 0.49 times a second on average.

| Call | Count | p50 (s) | p95 (s) | max (s) | 4xx | 5xx/failed |
|---|---:|---:|---:|---:|---:|---:|
| frame | 236 | 1.391 | 2.410 | 3.453 | 0 | 0 |
| student: dashboard | 280 | 0.024 | 0.414 | 1.001 | 0 | 0 |
| student: me | 280 | 0.017 | 0.189 | 0.842 | 0 | 0 |
| student: setup | 280 | 0.015 | 0.212 | 0.811 | 0 | 0 |
| student: subjects | 280 | 0.032 | 0.831 | 1.467 | 0 | 0 |
| teacher: class overview | 4 | 0.049 | 0.086 | 0.086 | 0 | 0 |
| teacher: dashboard | 8 | 0.023 | 0.043 | 0.043 | 0 | 0 |
| teacher: end session | 4 | 0.043 | 0.102 | 0.102 | 0 | 0 |
| teacher: hand mark | 80 | 0.086 | 0.168 | 0.185 | 0 | 0 |
| teacher: open round | 8 | 1.112 | 2.206 | 2.206 | 0 | 0 |
| teacher: register csv | 4 | 0.059 | 0.065 | 0.065 | 0 | 0 |
| teacher: session sheet | 4 | 0.153 | 0.215 | 0.215 | 0 | 0 |
| teacher: start | 4 | 0.937 | 0.981 | 0.981 | 0 | 0 |
| teacher: start from slot | 4 | 0.933 | 1.038 | 1.038 | 0 | 0 |

Peak per container during the run:

| Container | CPU % | Memory |
|---|---:|---|
| antiproxy-lt-backend | 51 | 108MiB / 640MiB |
| antiproxy-lt-frontend | 4 | 11.76MiB / 128MiB |
| antiproxy-lt-mongodb | 53 | 387.4MiB / 512MiB |
| antiproxy-lt-vision-service | 152 | 827.7MiB / 1GiB |

Targets: p95 frame < 1.5 s, p95 of every page call < 1.0 s, no 5xx.
**Result: NOT MET** (frame p95 2.41 s, slowest page p95 2.21 s, 0 failed).

Made-up data with the prefix `lt_` was added for the run and removed afterwards.
