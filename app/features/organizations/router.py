from typing import Annotated

from pydantic import BaseModel
from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.organizations.schemas import (
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationListResponse,
    OrganizationCreateResponse,
    OrganizationDeleteResponse,
)
from app.features.organizations.service import (
    get_organization_by_id,
    update_organization,
    delete_organization,
)
from app.features.users.dependencies import require_org_roles
from app.features.users.models import User
from app.features.users.organization_staff import OrganizationStaff


router = APIRouter(prefix="/organizations", tags=["Organizations"])


@router.get("/", response_model=OrganizationListResponse)
async def get_organization_endpoint(
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    organization = await get_organization_by_id(db, current_user.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return success_response(
        message="Organization fetched successfully",
        data=[OrganizationResponse.model_validate(organization)],
    )


@router.get("/{organization_id}", response_model=OrganizationCreateResponse)
async def get_organization_by_id_endpoint(
    organization_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization = await get_organization_by_id(db, organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return success_response(
        message="Organization fetched successfully",
        data=OrganizationResponse.model_validate(organization),
    )


@router.put("/{organization_id}", response_model=OrganizationCreateResponse)
async def update_organization_endpoint(
    organization_id: int,
    organization_data: OrganizationUpdate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    organization = await update_organization(db, organization_id, organization_data)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return success_response(
        message="Organization updated successfully",
        data=OrganizationResponse.model_validate(organization),
    )


@router.delete(
    "/{organization_id}",
    response_model=OrganizationDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_organization_endpoint(
    organization_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    result = await delete_organization(db, organization_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail="Organization not found")
    if result == "has_gyms":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete organization because it has gyms",
        )
    if result == "has_users":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete organization while user accounts exist",
        )
    return success_response(message="Organization deleted successfully")



class OwnershipTransferRequest(BaseModel):
    new_owner_user_id: int


@router.post("/{organization_id}/ownership/transfer")
async def transfer_organization_ownership(
    organization_id: int,
    transfer: OwnershipTransferRequest,
    current_user: Annotated[User, Depends(require_org_roles("owner"))],
    db: AsyncSession = Depends(get_db),
):
    if organization_id != current_user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")
    if transfer.new_owner_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You are already the owner")

    target_result = await db.execute(
        select(User).where(
            User.id == transfer.new_owner_user_id,
            User.organization_id == current_user.organization_id,
            User.is_active.is_(True),
            User.email_verified_at.is_not(None),
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=404,
            detail="Active, email-verified employee not found",
        )

    current_assignment_result = await db.execute(
        select(OrganizationStaff).where(
            OrganizationStaff.user_id == current_user.id,
            OrganizationStaff.organization_id == current_user.organization_id,
            OrganizationStaff.is_active.is_(True),
            OrganizationStaff.role == "owner",
        ).with_for_update()
    )
    current_assignment = current_assignment_result.scalar_one_or_none()
    if current_assignment is None:
        raise HTTPException(status_code=403, detail="Owner role required")

    target_assignment_result = await db.execute(
        select(OrganizationStaff).where(
            OrganizationStaff.user_id == target.id,
            OrganizationStaff.organization_id == current_user.organization_id,
        ).with_for_update()
    )
    target_assignment = target_assignment_result.scalar_one_or_none()

    current_assignment.role = "admin"
    if target_assignment is None:
        db.add(
            OrganizationStaff(
                user_id=target.id,
                organization_id=current_user.organization_id,
                role="owner",
                is_active=True,
            )
        )
    else:
        target_assignment.role = "owner"
        target_assignment.is_active = True

    await db.commit()
    return success_response(
        message="Organization ownership transferred successfully"
    )
