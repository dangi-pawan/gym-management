from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.gyms.schemas import GymCreate, GymUpdate
from app.features.members.models import Member
from app.features.memberships.models import (
    GymMembershipPlan,
    MemberGymAssignment,
    MemberSubscription,
    MembershipPlanAccessGym,
    SubscriptionAccessGym,
)
from app.features.users.gym_staff import GymStaff
from app.features.users.organization_staff import OrganizationStaff


async def create_gym(
    db: AsyncSession,
    gym_data: GymCreate,
    organization_id: int,
) -> Gym:
    new_gym = Gym(
        name=gym_data.name,
        organization_id=organization_id,
        timezone=gym_data.timezone,
    )
    db.add(new_gym)
    await db.commit()
    await db.refresh(new_gym)
    return new_gym


async def get_all_gyms(
    db: AsyncSession,
    page: int,
    limit: int,
    organization_id: int,
    user_id: int,
):
    offset = (page - 1) * limit
    org_role_result = await db.execute(
        select(OrganizationStaff.role).where(
            OrganizationStaff.user_id == user_id,
            OrganizationStaff.organization_id == organization_id,
            OrganizationStaff.is_active.is_(True),
        )
    )
    organization_role = org_role_result.scalar_one_or_none()

    if organization_role in {"owner", "admin"}:
        base_query = select(Gym).where(Gym.organization_id == organization_id)
        count_query = select(func.count()).select_from(Gym).where(
            Gym.organization_id == organization_id
        )
    else:
        base_query = (
            select(Gym)
            .join(GymStaff, GymStaff.gym_id == Gym.id)
            .where(
                Gym.organization_id == organization_id,
                GymStaff.organization_id == organization_id,
                GymStaff.user_id == user_id,
                GymStaff.is_active.is_(True),
            )
        )
        count_query = (
            select(func.count())
            .select_from(Gym)
            .join(GymStaff, GymStaff.gym_id == Gym.id)
            .where(
                Gym.organization_id == organization_id,
                GymStaff.organization_id == organization_id,
                GymStaff.user_id == user_id,
                GymStaff.is_active.is_(True),
            )
        )

    result = await db.execute(
        base_query.order_by(Gym.id).offset(offset).limit(limit)
    )
    gyms = result.scalars().all()
    total = await db.scalar(count_query)
    return gyms, total


async def get_gym_by_id(db: AsyncSession, gym_id: int):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    return result.scalar_one_or_none()


async def update_gym(db: AsyncSession, gym_id: int, gym_data: GymUpdate):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    gym = result.scalar_one_or_none()
    if gym is None:
        return None
    gym.name = gym_data.name
    if gym_data.timezone is not None:
        gym.timezone = gym_data.timezone
    await db.commit()
    await db.refresh(gym)
    return gym


async def delete_gym(db: AsyncSession, gym_id: int):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    gym = result.scalar_one_or_none()
    if gym is None:
        return "not_found"

    member_exists = await db.scalar(
        select(
            exists().where(
                MemberGymAssignment.gym_id == gym_id,
                MemberGymAssignment.status == "active",
            )
        )
    )
    legacy_member_exists = await db.scalar(
        select(exists().where(Member.gym_id == gym_id))
    )
    if member_exists or legacy_member_exists:
        return "has_members"

    membership_history_exists = await db.scalar(
        select(
            exists().where(GymMembershipPlan.gym_id == gym_id)
            | exists().where(MembershipPlanAccessGym.gym_id == gym_id)
            | exists().where(MemberSubscription.purchased_at_gym_id == gym_id)
            | exists().where(SubscriptionAccessGym.gym_id == gym_id)
        )
    )
    if membership_history_exists:
        return "has_memberships"

    await db.delete(gym)
    await db.commit()
    return "deleted"
