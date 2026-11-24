from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.users.dependencies import require_org_roles
from app.features.users.models import User
from app.features.users.schemas import UserCreate, UserResponse
from app.features.users.service import create_user


router = APIRouter(
    prefix="/organizations/{organization_id}/employees",
    tags=["Organization Employees"],
)


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_employee_endpoint(
    organization_id: int,
    employee_data: UserCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")

    employee = await create_user(db, organization_id, employee_data)
    if employee is None:
        raise HTTPException(
            status_code=409,
            detail="An employee with this email already exists in the organization",
        )
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
