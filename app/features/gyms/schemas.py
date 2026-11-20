from pydantic import BaseModel, ConfigDict


class GymCreate(BaseModel):
    name: str


class GymResponse(BaseModel):
    id: int
    name: str

    model_config = ConfigDict(from_attributes=True)


class GymCreateResponse(BaseModel):
    success: bool
    message: str
    data: GymResponse



class GymListResponse(BaseModel):
    success: bool
    message: str
    data: list[GymResponse]
    total: int
    page: int
    limit: int



class GymUpdate(BaseModel):
    name: str