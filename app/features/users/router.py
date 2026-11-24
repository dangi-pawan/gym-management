from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.users.auth_service import revoke_user_sessions
from app.features.users.dependencies import require_org_roles
from app.features.users.models import User
from app.features.users.organization_staff import OrganizationStaff
from app.features.users.schemas import UserResponse
from app.features.users.auth_schemas import EmployeeInvitationCreate
from app.features.users.account_tokens import EmployeeInvitationToken
from app.features.users.auth_service import (
    create_employee_invitation,
    resend_employee_invitation,
    increment_auth_rate_limit,
    AuthenticationRateLimitException,
)
from app.features.users.account_tokens import EmployeeInvitationToken
from app.core.config import settings
from app.core.email import send_email


router = APIRouter(
    prefix="/organizations/{organization_id}/employees",
    tags=["Organization Employees"],
)


class EmployeeStatusUpdate(BaseModel):
    is_active: bool



@router.post("/invitations", status_code=status.HTTP_202_ACCEPTED)
async def invite_employee_endpoint(
    organization_id: int,
    invitation_data: EmployeeInvitationCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")
    current_role = await db.scalar(
        select(OrganizationStaff.role).where(
            OrganizationStaff.user_id == current_user.id,
            OrganizationStaff.organization_id == organization_id,
            OrganizationStaff.is_active.is_(True),
        )
    )
    if invitation_data.organization_role == "admin" and current_role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Only an organization owner can invite another organization admin",
        )

    invitation_rate_key = f"employee-invite:{organization_id}:{current_user.id}"
    if await increment_auth_rate_limit(
        db,
        key=invitation_rate_key,
        max_attempts=settings.EMPLOYEE_INVITATION_MAX_PER_HOUR,
        window_minutes=60,
    ):
        raise AuthenticationRateLimitException()

    employee, raw_token = await create_employee_invitation(
        db,
        organization_id=organization_id,
        full_name=invitation_data.full_name,
        email=str(invitation_data.email),
        organization_role=invitation_data.organization_role,
    )
    await send_email(
        str(employee.email),
        "You have been invited to Gym Management",
        (
            f"Hello {employee.full_name},\n\n"
            "An administrator invited you to join the organization. "
            "Accept the invitation by submitting this one-time token to "
            "POST /auth/accept-invitation and choosing your password. "
            "The token expires in 48 hours.\n\n"
            f"Invitation token: {raw_token}"
        ),
    )
    return success_response(
        message="Employee invitation sent successfully",
        data={"user_id": employee.id, "email": employee.email},
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
    if not employee.is_active:
        await db.execute(
            update(EmployeeInvitationToken)
            .where(
                EmployeeInvitationToken.user_id == employee.id,
                EmployeeInvitationToken.used_at.is_(None),
            )
            .values(used_at=func.now())
        )
        await revoke_user_sessions(db, employee.id)
    else:
        await db.commit()
    await db.refresh(employee)
    return success_response(
        message="Employee status updated successfully",
        data=UserResponse.model_validate(employee),
    )




@router.post("/{user_id}/invitation/resend", status_code=status.HTTP_202_ACCEPTED)
async def resend_employee_invitation_endpoint(
    organization_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(status_code=503, detail="Email delivery is not configured")

    rate_key = f"employee-invite:{organization_id}:{current_user.id}"
    if await increment_auth_rate_limit(
        db,
        key=rate_key,
        max_attempts=settings.EMPLOYEE_INVITATION_MAX_PER_HOUR,
        window_minutes=60,
    ):
        raise AuthenticationRateLimitException()

    current_role = await db.scalar(
        select(OrganizationStaff.role).where(
            OrganizationStaff.user_id == current_user.id,
            OrganizationStaff.organization_id == organization_id,
            OrganizationStaff.is_active.is_(True),
        )
    )
    previous_role = await db.scalar(
        select(EmployeeInvitationToken.organization_role)
        .where(EmployeeInvitationToken.user_id == user_id)
        .order_by(EmployeeInvitationToken.id.desc())
        .limit(1)
    )
    if previous_role == "admin" and current_role != "owner":
        raise HTTPException(
            status_code=403,
            detail="Only an organization owner can resend an admin invitation",
        )

    employee, raw_token, _organization_role = await resend_employee_invitation(
        db,
        organization_id=organization_id,
        user_id=user_id,
    )

    await send_email(
        str(employee.email),
        "Your Gym Management invitation",
        (
            f"Hello {employee.full_name},\n\n"
            "Use this one-time token with POST /auth/accept-invitation to set "
            "your password. It expires in 48 hours.\n\n"
            f"Invitation token: {raw_token}"
        ),
    )
    return success_response(message="Employee invitation resent successfully")
