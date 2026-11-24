from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.users.auth_service import revoke_user_sessions
from app.features.users.dependencies import require_org_roles
from app.features.users.models import User
from app.features.users.organization_staff import OrganizationStaff
from app.features.users.schemas import UserCreate, UserResponse
from app.features.users.service import create_user


router = APIRouter(
    prefix="/organizations/{organization_id}/employees",
    tags=["Organization Employees"],
)


class EmployeeCreate(UserCreate):
    organization_role: Literal["admin"] | None = None


class EmployeeStatusUpdate(BaseModel):
    is_active: bool


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_employee_endpoint(
    organization_id: int,
    employee_data: EmployeeCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    employee = await create_user(
        db,
        organization_id,
        UserCreate(
            full_name=employee_data.full_name,
            email=employee_data.email,
            password=employee_data.password,
        ),
    )
    if employee is None:
        raise HTTPException(
            status_code=409,
            detail="An employee with this email already exists in the organization",
        )
    if employee_data.organization_role == "admin":
        db.add(
            OrganizationStaff(
                user_id=employee.id,
                organization_id=organization_id,
                role="admin",
                is_active=True,
            )
        )
        await db.commit()
        await db.refresh(employee)
    return success_response(
        message="Employee created successfully",
        data=UserResponse.model_validate(employee),
    )


@router.get("/")
async def list_employees_endpoint(
    organization_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    result = await db.execute(
        select(User)
        .where(User.organization_id == current_user.organization_id)
        .order_by(User.id)
    )
    employees = result.scalars().all()
    return success_response(
        message="Employees fetched successfully",
        data=[UserResponse.model_validate(employee) for employee in employees],
    )


@router.patch("/{user_id}/status")
async def update_employee_status(
    organization_id: int,
    user_id: int,
    status_data: EmployeeStatusUpdate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    if user_id == current_user.id and not status_data.is_active:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own account",
        )
    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == current_user.organization_id,
        )
    )
    employee = result.scalar_one_or_none()
    if employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    target_role_result = await db.execute(
        select(OrganizationStaff.role).where(
            OrganizationStaff.user_id == employee.id,
            OrganizationStaff.organization_id == current_user.organization_id,
            OrganizationStaff.is_active.is_(True),
        )
    )
    target_role = target_role_result.scalar_one_or_none()
    if target_role == "owner":
        current_role_result = await db.execute(
            select(OrganizationStaff.role).where(
                OrganizationStaff.user_id == current_user.id,
                OrganizationStaff.organization_id == current_user.organization_id,
                OrganizationStaff.is_active.is_(True),
            )
        )
        if current_role_result.scalar_one_or_none() != "owner":
            raise HTTPException(
                status_code=403,
                detail="Only an organization owner can deactivate another owner",
            )
        active_owner_count = await db.scalar(
            select(func.count()).select_from(OrganizationStaff).where(
                OrganizationStaff.organization_id == current_user.organization_id,
                OrganizationStaff.role == "owner",
                OrganizationStaff.is_active.is_(True),
            )
        )
        if active_owner_count <= 1:
            raise HTTPException(
                status_code=409,
                detail="The last active organization owner cannot be deactivated",
            )

    employee.is_active = status_data.is_active
    await db.commit()
    if not employee.is_active:
        await revoke_user_sessions(db, employee.id)
    await db.refresh(employee)
    return success_response(
        message="Employee status updated successfully",
        data=UserResponse.model_validate(employee),
    )
