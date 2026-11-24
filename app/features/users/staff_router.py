from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.gyms.models import Gym
from app.features.users.dependencies import require_org_roles
from app.features.users.gym_staff import GymStaff
from app.features.users.models import User


router = APIRouter(
    prefix="/gyms/{gym_id}/staff",
    tags=["Gym Staff"],
)


class GymStaffAssignmentCreate(BaseModel):
    user_id: int
    role: Literal["manager", "trainer", "receptionist"]


class GymStaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    gym_id: int
    organization_id: int
    role: str
    is_active: bool


async def _get_gym_for_owner(
    db: AsyncSession,
    gym_id: int,
    organization_id: int,
) -> Gym:
    result = await db.execute(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.organization_id == organization_id,
        )
    )
    gym = result.scalar_one_or_none()
    if gym is None:
        raise HTTPException(status_code=404, detail="Gym not found")
    return gym


@router.post("/", status_code=status.HTTP_201_CREATED)
async def assign_gym_staff(
    gym_id: int,
    assignment: GymStaffAssignmentCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    gym = await _get_gym_for_owner(db, gym_id, current_user.organization_id)
    user_result = await db.execute(
        select(User).where(
            User.id == assignment.user_id,
            User.organization_id == current_user.organization_id,
            User.is_active.is_(True),
        )
    )
    employee = user_result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")

    result = await db.execute(
        select(GymStaff).where(
            GymStaff.user_id == employee.id,
            GymStaff.gym_id == gym.id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        if existing.is_active:
            raise HTTPException(
                status_code=409,
                detail="Employee is already assigned to this gym",
            )
        existing.role = assignment.role
        existing.is_active = True
        await db.commit()
        await db.refresh(existing)
        return success_response(
            message="Gym staff assignment reactivated",
            data=GymStaffResponse.model_validate(existing),
        )

    staff = GymStaff(
        user_id=employee.id,
        gym_id=gym.id,
        organization_id=current_user.organization_id,
        role=assignment.role,
        is_active=True,
    )
    db.add(staff)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Employee is already assigned to this gym",
        ) from None
    await db.refresh(staff)
    return success_response(
        message="Employee assigned to gym successfully",
        data=GymStaffResponse.model_validate(staff),
    )


@router.get("/")
async def list_gym_staff(
    gym_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    gym = await _get_gym_for_owner(db, gym_id, current_user.organization_id)
    result = await db.execute(
        select(GymStaff).where(
            GymStaff.gym_id == gym.id,
            GymStaff.organization_id == current_user.organization_id,
            GymStaff.is_active.is_(True),
        ).order_by(GymStaff.id)
    )
    staff = result.scalars().all()
    return success_response(
        message="Gym staff fetched successfully",
        data=[GymStaffResponse.model_validate(item) for item in staff],
    )


@router.delete("/{user_id}")
async def remove_gym_staff(
    gym_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    await _get_gym_for_owner(db, gym_id, current_user.organization_id)
    result = await db.execute(
        select(GymStaff).where(
            GymStaff.user_id == user_id,
            GymStaff.gym_id == gym_id,
            GymStaff.organization_id == current_user.organization_id,
            GymStaff.is_active.is_(True),
        )
    )
    staff = result.scalar_one_or_none()
    if staff is None:
        raise HTTPException(status_code=404, detail="Gym staff assignment not found")
    staff.is_active = False
    await db.commit()
    return success_response(message="Gym staff assignment removed")
