"""Accounts for tests that start a real backend process.

A teacher who registers is PENDING until an administrator approves them and
assigns their classes, and a teacher can open a session only for an assigned
class. These helpers give the backend process a first administrator and
return an approved teacher's headers. Passwords are generated per run.
"""

from __future__ import annotations

import secrets
import time

import requests

TEST_CLASS_CODE = "DS-B"


def add_bootstrap_admin(env: dict[str, str]) -> tuple[str, str]:
    """Make the backend process create its own first administrator. Returns (email, password)."""
    email = f"admin.{secrets.token_hex(4)}@vision-tests.invalid"
    password = secrets.token_urlsafe(24)
    env["BOOTSTRAP_ADMIN_EMAIL"] = email
    env["BOOTSTRAP_ADMIN_PASSWORD"] = password
    return email, password


def approved_teacher_headers(
    backend_url: str,
    admin_email: str,
    admin_password: str,
    class_code: str = TEST_CLASS_CODE,
) -> dict[str, str]:
    """Register a teacher, have the administrator approve them for ``class_code``, and log in."""
    teacher_email = f"teacher.{time.time_ns()}@vision-tests.invalid"
    teacher_password = secrets.token_urlsafe(18) + "aA1!"

    registered = requests.post(
        f"{backend_url}/api/v1/auth/register",
        json={"email": teacher_email, "password": teacher_password, "role": "TEACHER"},
        timeout=5.0,
    )
    if registered.status_code != 201:
        raise RuntimeError(f"Teacher registration failed: {registered.status_code} {registered.text}")

    admin_login = requests.post(
        f"{backend_url}/api/v1/auth/login",
        json={"email": admin_email, "password": admin_password},
        timeout=5.0,
    )
    if admin_login.status_code != 200:
        raise RuntimeError(f"Administrator login failed: {admin_login.status_code}")
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    approved = requests.post(
        f"{backend_url}/api/v1/admin/approvals/{registered.json()['user_id']}/approve",
        headers=admin_headers,
        json={"assigned_classes": [class_code]},
        timeout=5.0,
    )
    if approved.status_code != 200:
        raise RuntimeError(f"Teacher approval failed: {approved.status_code} {approved.text}")

    login = requests.post(
        f"{backend_url}/api/v1/auth/login",
        json={"email": teacher_email, "password": teacher_password},
        timeout=5.0,
    )
    if login.status_code != 200:
        raise RuntimeError(f"Teacher login failed: {login.status_code} {login.text}")
    return {"Authorization": f"Bearer {login.json()['access_token']}"}
