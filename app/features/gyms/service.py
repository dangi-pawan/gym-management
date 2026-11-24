from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.gyms.schemas import GymCreate, GymUpdate
from app.features.members.models import Member


async def create_gym(
    db: AsyncSession,
    gym_data: GymCreate,
    organization_id: int,
) -> Gym:
    new_gym = Gym(
        name=gym_data.name,
        organization_id=organization_id,
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
):
    offset = (page - 1) * limit
    query = (
        select(Gym)
        .where(Gym.organization_id == organization_id)
        .order_by(Gym.id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    gyms = result.scalars().all()

    count_result = await db.execute(
        select(func.count()).select_from(Gym).where(
            Gym.organization_id == organization_id
        )
    )
    return gyms, count_result.scalar_one()


async def get_gym_by_id(db: AsyncSession, gym_id: int):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    return result.scalar_one_or_none()


async def update_gym(db: AsyncSession, gym_id: int, gym_data: GymUpdate):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    gym = result.scalar_one_or_none()
    if gym is None:
        return None
    gym.name = gym_data.name
    await db.commit()
    await db.refresh(gym)
    return gym


async def delete_gym(db: AsyncSession, gym_id: int):
    result = await db.execute(select(Gym).where(Gym.id == gym_id))
    gym = result.scalar_one_or_none()
    if gym is None:
        return "not_found"

    member_exists = await db.scalar(
        select(exists().where(Member.gym_id == gym_id))
    )
    if member_exists:
        return "has_members"

    await db.delete(gym)
    await db.commit()
    return "deleted"
