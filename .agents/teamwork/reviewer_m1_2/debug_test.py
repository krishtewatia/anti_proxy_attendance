import asyncio
import os
import sys
from pathlib import Path

# Add tests/e2e
sys.path.insert(0, r"c:\Users\hp\Downloads\anti_proxy_project\tests\e2e")
sys.path.insert(0, r"c:\Users\hp\Downloads\anti_proxy_project\backend")
sys.path.insert(0, r"c:\Users\hp\Downloads\anti_proxy_project")

from conftest import (
    get_mongo_connection_uri,
    DATABASE_NAME,
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    TEACHER_EMAIL,
    TEACHER_PASSWORD,
    STUDENT_PASSWORD,
    STUDENT_USER_MAP,
    SESSION_ID,
    seed_clean_demo_state,
)
from pymongo import MongoClient
import httpx

async def main():
    uri = get_mongo_connection_uri()
    print("Resolved URI:", uri)
    client = MongoClient(uri)
    db = client[DATABASE_NAME]
    print("Pre-seed session count:", db.sessions.count_documents({}))
    seed_clean_demo_state(db)
    print("Post-seed session count:", db.sessions.count_documents({}))
    print("Post-seed users count:", db.users.count_documents({}))

    session = db.sessions.find_one({"session_id": SESSION_ID})
    print("Session found immediately:", session is not None)

    async with httpx.AsyncClient(base_url="http://localhost:8000") as http:
        # Admin
        res = await http.post("/api/v1/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        print("Admin login:", res.status_code)

        # Teacher
        res = await http.post("/api/v1/auth/login", json={"email": TEACHER_EMAIL, "password": TEACHER_PASSWORD})
        print("Teacher login:", res.status_code)

        # Students
        for ident, (stu_name, stu_id, _) in STUDENT_USER_MAP.items():
            email = f"{stu_name}@demo.edu"
            res = await http.post("/api/v1/auth/login", json={"email": email, "password": STUDENT_PASSWORD})
            print(f"Student {stu_name} ({email}) login: {res.status_code} - {res.text}")

    print("Post-http session count:", db.sessions.count_documents({}))

asyncio.run(main())
