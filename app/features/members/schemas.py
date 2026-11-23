
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from app.common.responses.schemas import APIResponse


class MemberCreate(BaseModel):
    name: str = Field(min_length=2, max_length=50)
    age: int = Field(gt=0, le=120)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError("Name cannot be empty")

        return value


class MemberUpdate(MemberCreate):
    pass


class MemberResponse(BaseModel):
    id: int
    gym_id: int
    name: str
    age: int

    model_config = ConfigDict(from_attributes=True)


class MemberListData(BaseModel):
    members: list[MemberResponse]
    total: int
    page: int
    limit: int


MemberCreateResponse = APIResponse[MemberResponse]
MemberListResponse = APIResponse[MemberListData]
MemberDeleteResponse = APIResponse[None]
