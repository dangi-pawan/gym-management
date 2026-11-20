from fastapi import APIRouter , Query
from app.features.members.schemas import MemberCreate


router = APIRouter(
    prefix="/members",
    tags=["Members"]
)

@router.get("/")
async def get_members(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100)
):
    return {
        "skip": skip,
        "limit": limit,
        "message": "Members list"
    }


@router.post("/")
async def create_member(member: MemberCreate):
    return {
        "message": "Member created successfully",
        "data": member
    }


@router.get("/{member_id}")
async def get_member(member_id: int):
    return {
        "member_id": member_id,
        "message": "Member details"
    }


