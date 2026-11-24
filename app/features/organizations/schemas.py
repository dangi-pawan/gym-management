from pydantic import BaseModel, ConfigDict, Field

from app.common.responses.schemas import APIResponse


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)


class OrganizationUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=150)


class OrganizationResponse(BaseModel):
    id: int
    name: str
    slug: str

    model_config = ConfigDict(from_attributes=True)


OrganizationCreateResponse = APIResponse[OrganizationResponse]
OrganizationResponseSchema = APIResponse[OrganizationResponse]
OrganizationListResponse = APIResponse[list[OrganizationResponse]]
OrganizationDeleteResponse = APIResponse[None]
