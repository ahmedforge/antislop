from pydantic import UUID4, BaseModel, ConfigDict, Field


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    install_id: UUID4
    channel_id: str = Field(pattern=r"^UC[A-Za-z0-9_-]{22}$")
    reason: str = Field(min_length=1, max_length=2000)
