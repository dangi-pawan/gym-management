from typing import Annotated

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
