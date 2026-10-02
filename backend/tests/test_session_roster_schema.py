import pytest
from pydantic import ValidationError

from app.schemas.session_roster import SessionRoster


def test_valid_session_roster():
    roster = SessionRoster(
        session_id="session_001",
        identities=["person_01", "person_02", "person_03"],
    )
    assert roster.session_id == "session_001"
    assert len(roster.identities) == 3


def test_empty_identities_rejected():
    with pytest.raises(ValidationError):
        SessionRoster(
            session_id="session_001",
            identities=[],
        )


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        SessionRoster(
            session_id="session_001",
            identities=["person_01"],
            unexpected_field="disallowed",
        )
