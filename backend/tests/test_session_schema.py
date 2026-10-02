from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.session import SessionCreate


def test_valid_session():
    session = SessionCreate(
        course_name="Data Structures",
        classroom_id="ROOM_101",
        start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
        required_presence_percentage=75.0,
    )

    assert session.course_name == "Data Structures"
    assert session.classroom_id == "ROOM_101"
    assert session.required_presence_percentage == 75.0


def test_invalid_presence_percentage():
    with pytest.raises(ValidationError):
        SessionCreate(
            course_name="Data Structures",
            classroom_id="ROOM_101",
            start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
            required_presence_percentage=120.0,
        )


def test_extra_fields_are_rejected():
    with pytest.raises(ValidationError):
        SessionCreate(
            course_name="Data Structures",
            classroom_id="ROOM_101",
            start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
            required_presence_percentage=75.0,
            student_id="student_01",
        )


def test_created_by_in_session_create_is_rejected():
    with pytest.raises(ValidationError):
        SessionCreate(
            course_name="Data Structures",
            classroom_id="ROOM_101",
            start_time=datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 29, 11, 0, tzinfo=timezone.utc),
            required_presence_percentage=75.0,
            created_by="someone_else",
        )
