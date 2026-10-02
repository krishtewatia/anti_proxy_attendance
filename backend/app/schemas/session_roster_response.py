from pydantic import BaseModel, ConfigDict, Field


class SessionRosterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identities: list[str] = Field(min_length=1)


class SessionRosterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    identities: list[str]
