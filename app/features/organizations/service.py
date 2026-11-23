
from sqlalchemy import select, exists
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.organizations.models import Organization
from app.features.organizations.schemas import (
    OrganizationCreate,
    OrganizationUpdate,
)
from app.features.gyms.models import Gym


async def create_organization(
    db: AsyncSession,
    organization_data: OrganizationCreate,
) -> Organization:
    new_organization = Organization(
        name=organization_data.name
    )

    db.add(new_organization)
    await db.commit()
    await db.refresh(new_organization)

    return new_organization


async def get_all_organizations(
    db: AsyncSession,
):
    result = await db.execute(
        select(Organization).order_by(Organization.id)
    )

    return result.scalars().all()


async def get_organization_by_id(
    db: AsyncSession,
    organization_id: int,
):
    result = await db.execute(
        select(Organization).where(
            Organization.id == organization_id
        )
    )

    return result.scalar_one_or_none()


async def update_organization(
    db: AsyncSession,
    organization_id: int,
    organization_data: OrganizationUpdate,
):
    organization = await get_organization_by_id(
        db,
        organization_id,
    )

    if organization is None:
        return None

    organization.name = organization_data.name

    await db.commit()
    await db.refresh(organization)

    return organization


async def delete_organization(
    db: AsyncSession,
    organization_id: int,
):
    organization = await get_organization_by_id(
        db,
        organization_id,
    )

    if organization is None:
        return "not_found"

    gym_exists = await db.scalar(
        select(
            exists().where(
                Gym.organization_id == organization_id
            )
        )
    )

    if gym_exists:
        return "has_gyms"

    await db.delete(organization)
    await db.commit()

    return "deleted"
