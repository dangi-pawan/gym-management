

from pydantic import BaseModel, ConfigDict, Field

from app.common.responses.schemas import APIResponse


class GymCreate(BaseModel):
    name: str


class GymUpdate(BaseModel):
    name: str


class GymResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class GymListData(BaseModel):
    gyms: list[GymResponse]
    total: int
    page: int
    limit: int


GymCreateResponse = APIResponse[GymResponse]
GymListResponse = APIResponse[GymListData]
GymDeleteResponse = APIResponse[None]

