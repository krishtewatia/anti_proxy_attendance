from pydantic import BaseModel, ConfigDict, Field


class SessionRoster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1)
    identities: list[str] = Field(min_length=1)
