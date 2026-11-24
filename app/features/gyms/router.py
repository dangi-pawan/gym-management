from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.gyms.schemas import (
    GymCreate,
    GymCreateResponse,
    GymListResponse,
    GymUpdate,
    GymResponse,
    GymListData,
    GymDeleteResponse,
)
from app.features.gyms.service import (
    create_gym,
    get_all_gyms,
    get_gym_by_id,
    update_gym,
    delete_gym,
)
from app.features.users.dependencies import require_gym_roles, require_org_roles
from app.features.users.models import User


router = APIRouter(prefix="/gyms", tags=["Gyms"])


@router.post("/", response_model=GymCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_gym_endpoint(
    gym_data: GymCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    gym = await create_gym(db, gym_data, current_user.organization_id)
    return success_response(
        message="Gym created successfully",
        data=GymResponse.model_validate(gym),
    )


@router.get("/", response_model=GymListResponse)
async def get_all_gyms_endpoint(
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    gyms, total = await get_all_gyms(
        db, page, limit, current_user.organization_id
    )
    data = GymListData(
        gyms=[GymResponse.model_validate(gym) for gym in gyms],
        total=total,
        page=page,
        limit=limit,
    )
    return success_response(message="Gyms fetched successfully", data=data)


@router.get("/{gym_id}", response_model=GymCreateResponse)
async def get_gym_by_id_endpoint(
    gym_id: int,
    _: Annotated[User, Depends(require_gym_roles("manager", "trainer", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    gym = await get_gym_by_id(db, gym_id)
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym not found")
    return success_response(
        message="Gym fetched successfully",
        data=GymResponse.model_validate(gym),
    )


@router.put("/{gym_id}", response_model=GymCreateResponse)
async def update_gym_endpoint(
    gym_id: int,
    gym_data: GymUpdate,
    _: Annotated[User, Depends(require_gym_roles("manager"))],
    db: AsyncSession = Depends(get_db),
):
    gym = await update_gym(db, gym_id, gym_data)
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym not found")
    return success_response(
        message="Gym updated successfully",
        data=GymResponse.model_validate(gym),
    )


@router.delete("/{gym_id}", response_model=GymDeleteResponse)
async def delete_gym_endpoint(
    gym_id: int,
    _: Annotated[User, Depends(require_gym_roles("manager"))],
    db: AsyncSession = Depends(get_db),
):
    result = await delete_gym(db, gym_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Gym not found")
    if result == "has_members":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete gym because it has members",
        )
    return success_response(message="Gym deleted successfully")
