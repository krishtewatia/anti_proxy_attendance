from pydantic import BaseModel, ConfigDict


class SessionFinalizationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    records: list[dict]
