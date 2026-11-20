
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

from app.features.members.schemas import (
    MemberCreate,
    MemberUpdate,
    MemberCreateResponse,
    MemberListResponse,
    MemberDeleteResponse
)

from app.features.members.service import (
    create_member,
    get_all_members,
    get_member_by_id,
    update_member,
    delete_member
)


router = APIRouter(
    prefix="/gyms/{gym_id}/members",
    tags=["Members"]
)


@router.post(
    "/",
    response_model=MemberCreateResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_member_endpoint(
    gym_id: int,
    member_data: MemberCreate,
    db: AsyncSession = Depends(get_db)
):
    member = await create_member(db, gym_id, member_data)

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gym not found"
        )

    return {
        "success": True,
        "message": "Member created successfully",
        "data": member
    }


@router.get(
    "/",
    response_model=MemberListResponse,
    status_code=status.HTTP_200_OK
)
async def get_all_members_endpoint(
    gym_id: int,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    result = await get_all_members(db, gym_id, page, limit)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gym not found"
        )

    members, total = result

    return {
        "success": True,
        "message": "Members fetched successfully",
        "data": members,
        "total": total,
        "page": page,
        "limit": limit
    }


@router.get(
    "/{member_id}",
    response_model=MemberCreateResponse,
    status_code=status.HTTP_200_OK
)
async def get_member_endpoint(
    gym_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db)
):
    member = await get_member_by_id(db, gym_id, member_id)

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found"
        )

    return {
        "success": True,
        "message": "Member fetched successfully",
        "data": member
    }


@router.put(
    "/{member_id}",
    response_model=MemberCreateResponse,
    status_code=status.HTTP_200_OK
)
async def update_member_endpoint(
    gym_id: int,
    member_id: int,
    member_data: MemberUpdate,
    db: AsyncSession = Depends(get_db)
):
    member = await update_member(
        db, gym_id, member_id, member_data
    )

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found"
        )

    return {
        "success": True,
        "message": "Member updated successfully",
        "data": member
    }


@router.delete(
    "/{member_id}",
    response_model=MemberDeleteResponse,
    status_code=status.HTTP_200_OK
)
async def delete_member_endpoint(
    gym_id: int,
    member_id: int,
    db: AsyncSession = Depends(get_db)
):
    deleted = await delete_member(db, gym_id, member_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found"
        )

    return {
        "success": True,
        "message": "Member deleted successfully"
    }
