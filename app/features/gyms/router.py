from fastapi import APIRouter, Depends, status, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.features.gyms.schemas import (
    GymCreate,
    GymCreateResponse,
    GymListResponse,
    GymUpdate,

)
from app.features.gyms.service import (
    create_gym,
    get_all_gyms,
    get_gym_by_id,
    update_gym,
    delete_gym
)


router = APIRouter(
    prefix="/gyms",
    tags=["Gyms"]
)


@router.post(
    "/",
    response_model=GymCreateResponse,
    status_code=status.HTTP_201_CREATED
)
async def create_gym_endpoint(
    gym_data: GymCreate,
    db: AsyncSession = Depends(get_db)
):
    gym = await create_gym(db, gym_data)

    return {
        "success": True,
        "message": "Gym created successfully",
        "data": gym
    }



@router.get(
    "/",
    response_model=GymListResponse,
    status_code=status.HTTP_200_OK
)
async def get_all_gyms_endpoint(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    gyms, total = await get_all_gyms(db, page, limit)

    return {
        "success": True,
        "message": "Gyms fetched successfully",
        "data": gyms,
        "total": total,
        "page": page,
        "limit": limit
    }




@router.get(
    "/{gym_id}",
    response_model=GymCreateResponse,
    status_code=status.HTTP_200_OK
)
async def get_gym_by_id_endpoint(
    gym_id: int,
    db: AsyncSession = Depends(get_db)
):
    gym = await get_gym_by_id(db, gym_id)

    if gym is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gym not found"
        )

    return {
        "success": True,
        "message": "Gym fetched successfully",
        "data": gym
    }





@router.put(
    "/{gym_id}",
    response_model=GymCreateResponse,
    status_code=status.HTTP_200_OK
)
async def update_gym_endpoint(
    gym_id: int,
    gym_data: GymUpdate,
    db: AsyncSession = Depends(get_db)
):
    gym = await update_gym(db, gym_id, gym_data)

    if gym is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gym not found"
        )

    return {
        "success": True,
        "message": "Gym updated successfully",
        "data": gym
    }




@router.delete(
    "/{gym_id}",
    status_code=status.HTTP_200_OK
)
async def delete_gym_endpoint(
    gym_id: int,
    db: AsyncSession = Depends(get_db)
):
    result = await delete_gym(db, gym_id)

    if result == "not_found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gym not found"
        )

    if result == "has_members":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete gym because it has members"
        )

    return {
        "success": True,
        "message": "Gym deleted successfully"
    }
