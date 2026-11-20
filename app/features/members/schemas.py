from pydantic import BaseModel, Field


class MemberCreate(BaseModel):
    name: str = Field(min_length=3, max_length=50)
    age: int = Field(ge=18, le=80)