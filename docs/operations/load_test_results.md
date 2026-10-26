# Load test results

Run 2026-10-26 14:31 UTC against the local stack (limited to 2 vCPU / 2 GB like the t3.small).

One period, four sections at once: 4 teachers, 280 students, 120 s of frames per session (640x480, one in flight per camera, no faces). Wall time 129 s.

Each camera got an answer 0.36 times a second on average.

| Call | Count | p50 (s) | p95 (s) | max (s) | 4xx | 5xx/failed |
|---|---:|---:|---:|---:|---:|---:|
| frame | 172 | 2.853 | 4.486 | 5.035 | 0 | 2 |
| student: dashboard | 280 | 0.020 | 0.103 | 0.283 | 0 | 0 |
| student: me | 280 | 0.017 | 0.079 | 0.339 | 0 | 0 |
| student: setup | 280 | 0.013 | 0.074 | 0.223 | 0 | 0 |
| student: subjects | 280 | 0.024 | 0.111 | 0.525 | 0 | 0 |
| teacher: class overview | 4 | 0.044 | 0.053 | 0.053 | 0 | 0 |
| teacher: dashboard | 8 | 0.019 | 0.052 | 0.052 | 0 | 0 |
| teacher: end session | 4 | 0.026 | 0.049 | 0.049 | 0 | 0 |
| teacher: hand mark | 80 | 0.073 | 0.135 | 0.278 | 0 | 0 |
| teacher: open round | 8 | 0.588 | 1.354 | 1.354 | 0 | 0 |
| teacher: register csv | 4 | 0.032 | 0.037 | 0.037 | 0 | 0 |
| teacher: session sheet | 4 | 0.038 | 0.040 | 0.040 | 0 | 0 |
| teacher: start | 4 | 0.083 | 0.087 | 0.087 | 0 | 0 |
| teacher: start from slot | 4 | 0.334 | 0.393 | 0.393 | 0 | 0 |

Peak per container during the run:

| Container | CPU % | Memory |
|---|---:|---|
| antiproxy-lt-backend | 51 | 97.89MiB / 640MiB |
| antiproxy-lt-frontend | 0 | 11.04MiB / 128MiB |
| antiproxy-lt-mongodb | 51 | 386.4MiB / 512MiB |
| antiproxy-lt-vision-service | 105 | 826.4MiB / 1GiB |

Targets: p95 frame < 1.5 s, p95 of every page call < 1.0 s, no 5xx.
**Result: NOT MET** (frame p95 4.49 s, slowest page p95 1.35 s, 2 failed).

Made-up data with the prefix `lt_` was added for the run and removed afterwards.
