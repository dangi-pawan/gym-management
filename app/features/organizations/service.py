import re
import unicodedata

from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.organizations.models import Organization
from app.features.organizations.schemas import (
    OrganizationCreate,
    OrganizationUpdate,
)
from app.features.gyms.models import Gym


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return slug or "organization"


async def create_organization(
    db: AsyncSession,
    organization_data: OrganizationCreate,
) -> Organization:
    base_slug = _slugify(organization_data.name)

    # The unique constraint is the final concurrency guard. If another request
    # claims a candidate between our attempts, retry with the next suffix.
    for attempt in range(1, 100):
        suffix = "" if attempt == 1 else f"-{attempt}"
        candidate = f"{base_slug[:180 - len(suffix)]}{suffix}"
        new_organization = Organization(
            name=organization_data.name,
            slug=candidate,
        )
        db.add(new_organization)

        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            constraint_name = (
                getattr(exc.orig, "constraint_name", None)
                or getattr(
                    getattr(exc.orig, "diag", None),
                    "constraint_name",
                    None,
                )
            )
            if constraint_name != "uq_organizations_slug":
                raise
            continue

        await db.refresh(new_organization)
        return new_organization

    raise RuntimeError("Unable to generate a unique organization slug")


async def get_organization_by_slug(
    db: AsyncSession,
    slug: str,
) -> Organization | None:
    result = await db.execute(
        select(Organization).where(Organization.slug == slug)
    )
    return result.scalar_one_or_none()


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
    organization = await get_organization_by_id(db, organization_id)
    if organization is None:
        return None

    # Slugs are stable identifiers and do not change when the display name changes.
    organization.name = organization_data.name
    await db.commit()
    await db.refresh(organization)
    return organization


async def delete_organization(
    db: AsyncSession,
    organization_id: int,
):
    organization = await get_organization_by_id(db, organization_id)
    if organization is None:
        return "not_found"

    gym_exists = await db.scalar(
        select(exists().where(Gym.organization_id == organization_id))
    )
    if gym_exists:
        return "has_gyms"

    await db.delete(organization)
    await db.commit()
    return "deleted"
