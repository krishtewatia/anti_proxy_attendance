## 2026-10-03T10:25:08Z
You are Reviewer 1 for Milestone 1 (teamwork_preview_reviewer).
Your working directory is: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\reviewer_m1_1
Workspace root: c:\Users\hp\Downloads\anti_proxy_project
Mandatory: Read ORIGINAL_REQUEST.md at: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\ORIGINAL_REQUEST.md
Also read PROJECT.md at: c:\Users\hp\Downloads\anti_proxy_project\PROJECT.md
Also read Worker M1 Handoff at: c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\worker_m1\handoff.md

Review `scripts/seed_clean_demo.py` for:
1. Code correctness, robust error handling, connection URI resolution (`MONGODB_URL`, `--mongo-uri`, default authenticated URI).
2. Purge completeness: properly wipes mock users, legacy test sessions, old cameras, and synthetic formula embeddings.
3. Authentic bcrypt hashing for Admin, Teacher, and 4 Students.
4. Correct schema conformance for users, student_profiles, biometric_profiles (512-d unit norm, ENROLLED), cameras (vertical line x=0.5, entry_side SIDE_A), and session sess_demo_cs101 (owned by user_teacher_demo, active today, 4 students in roster).
5. Run verification checks.

Write your structured review report and handoff to `c:\Users\hp\Downloads\anti_proxy_project\.agents\teamwork\reviewer_m1_1\handoff.md` with explicit Verdict: APPROVE or REQUEST_CHANGES.
When complete, notify orchestrator via send_message.
