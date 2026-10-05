## 2026-10-03T09:57:40Z
You are Survey Explorer 3 (teamwork_preview_explorer).
Your working directory is: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_3
Workspace root: c:\Users\hp\Downloads\anti_proxy_project
Mandatory: Read ORIGINAL_REQUEST.md at: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\ORIGINAL_REQUEST.md

Your focus is Requirement R3 (Streamlined Teacher Dashboard & 4-Student Ledger UI) and Requirement R4 (Automated Verification & Operational Runbook):
1. Investigate the frontend application structure (`frontend/` or `client/`). Identify package manager, framework (React, Vite/Next/CRA), routing, and state management.
2. Locate and inspect `SessionDetails.tsx` and related components. What multi-camera CCTV/RTSP selectors currently exist? How can they be cleaned up/hidden for the CS-101 session?
3. Examine how live camera preview/status is rendered, and how the student ledger is structured. How can we present a clean split view with live mobile camera stream/status and a 4-student ledger with badges (`🟢 IN ROOM`, `🟡 EXITED`, `⚪ NOT SEEN`) and active dwell time progress bars?
4. Check real-time snapshot polling: endpoint `GET /api/v1/sessions/{id}/live-snapshot`, polling interval, response schema, and how state changes are reflected without page refresh.
5. Inspect existing verification/test scripts, backend test infrastructure, docker-compose configuration, running containers, and port mappings.
6. Detail the design for `scripts/verify_demo_pipeline.py` (R4): seeding run, MongoDB check, event ingestion `POST /api/v1/events` for `person_01` (`student1`), snapshot verification `GET /api/v1/sessions/{id}/live-snapshot` (IN ROOM -> EXITED).
7. Outline the exact operational commands needed for rebuilding containers, seeding data, and running the demo.

Output your comprehensive findings in:
`c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\survey_explorer_3\report.md`
and write a standard `handoff.md` in your working directory.
When finished, send a message to the orchestrator.
