import pytest
from pydantic import ValidationError

from app.schemas.auth import (
    UserCreate,
    UserLogin,
)


def test_teacher_registration_is_valid():
    user = UserCreate(
        email="teacher@example.com",
        password="securepassword",
        role="TEACHER",
    )

    assert user.role == "TEACHER"


def test_student_registration_is_valid():
    user = UserCreate(
        email="student@example.com",
        password="securepassword",
        role="STUDENT",
    )

    assert user.role == "STUDENT"


def test_admin_registration_is_rejected():
    with pytest.raises(ValidationError):
        UserCreate(
            email="admin@example.com",
            password="securepassword",
            role="ADMIN",
        )


def test_short_password_is_rejected():
    with pytest.raises(ValidationError):
        UserCreate(
            email="teacher@example.com",
            password="short",
            role="TEACHER",
        )


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        UserCreate(
            email="teacher@example.com",
            password="securepassword",
            role="TEACHER",
            unexpected="field",
        )


def test_login_schema():
    login = UserLogin(
        email="teacher@example.com",
        password="securepassword",
    )

    assert login.email == "teacher@example.com"
