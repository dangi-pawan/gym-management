from pydantic import BaseModel, ConfigDict, Field

from app.common.responses.schemas import APIResponse


class GymCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    organization_id: int = Field(gt=0)


class GymUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GymResponse(BaseModel):
    id: int
    name: str
    organization_id: int

    model_config = ConfigDict(from_attributes=True)


class GymListData(BaseModel):
    gyms: list[GymResponse]
    total: int
    page: int
    limit: int


GymCreateResponse = APIResponse[GymResponse]
GymListResponse = APIResponse[GymListData]
GymDeleteResponse = APIResponse[None]