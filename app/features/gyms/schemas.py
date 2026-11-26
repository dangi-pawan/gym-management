from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.responses.schemas import APIResponse


class GymCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="Asia/Kolkata", min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone") from None
        return value


class GymUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("timezone must be a valid IANA timezone") from None
        return value


class GymResponse(BaseModel):
    id: int
    name: str
    organization_id: int
    timezone: str

    model_config = ConfigDict(from_attributes=True)


class GymListData(BaseModel):
    gyms: list[GymResponse]
    total: int
    page: int
    limit: int


GymCreateResponse = APIResponse[GymResponse]
GymListResponse = APIResponse[GymListData]
GymDeleteResponse = APIResponse[None]
