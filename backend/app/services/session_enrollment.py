from app.database.session_roster import (
    create_session_roster,
    get_session_roster,
)
from app.schemas.session_roster import SessionRoster


async def enroll_session_roster(
    session_id: str,
    identities: list[str],
) -> SessionRoster:
    roster = SessionRoster(
        session_id=session_id,
        identities=identities,
    )

    await create_session_roster(roster)

    return roster


async def get_enrolled_roster(
    session_id: str,
) -> SessionRoster | None:
    return await get_session_roster(session_id)
