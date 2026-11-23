
from fastapi import APIRouter, Depends, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.common.responses.helpers import success_response

from app.features.organizations.schemas import (
    OrganizationCreate,
    OrganizationUpdate,
    OrganizationResponse,
    OrganizationCreateResponse,
    OrganizationListResponse,
    OrganizationDeleteResponse,
)

from app.features.organizations.service import (
    create_organization,
    get_all_organizations,
    get_organization_by_id,
    update_organization,
    delete_organization,
)


router = APIRouter(
    prefix="/organizations",
    tags=["Organizations"],
)


@router.post(
    "/",
    response_model=OrganizationCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization_endpoint(
    organization_data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
):
    organization = await create_organization(
        db,
        organization_data,
    )

    return success_response(
        message="Organization created successfully",
        data=OrganizationResponse.model_validate(organization),
    )


@router.get(
    "/",
    response_model=OrganizationListResponse,
)
async def get_all_organizations_endpoint(
    db: AsyncSession = Depends(get_db),
):
    organizations = await get_all_organizations(db)

    return success_response(
        message="Organizations fetched successfully",
        data=[
            OrganizationResponse.model_validate(organization)
            for organization in organizations
        ],
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationCreateResponse,
)
async def get_organization_by_id_endpoint(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
):
    organization = await get_organization_by_id(
        db,
        organization_id,
    )

    if organization is None:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    return success_response(
        message="Organization fetched successfully",
        data=OrganizationResponse.model_validate(organization),
    )


@router.put(
    "/{organization_id}",
    response_model=OrganizationCreateResponse,
)
async def update_organization_endpoint(
    organization_id: int,
    organization_data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
):
    organization = await update_organization(
        db,
        organization_id,
        organization_data,
    )

    if organization is None:
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    return success_response(
        message="Organization updated successfully",
        data=OrganizationResponse.model_validate(organization),
    )


@router.delete(
    "/{organization_id}",
    response_model=OrganizationDeleteResponse,
)
async def delete_organization_endpoint(
    organization_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await delete_organization(
        db,
        organization_id,
    )

    if result == "not_found":
        raise HTTPException(
            status_code=404,
            detail="Organization not found",
        )

    if result == "has_gyms":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete organization because it has gyms",
        )

    return success_response(
        message="Organization deleted successfully",
    )
