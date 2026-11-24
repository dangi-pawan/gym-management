from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.gyms.schemas import GymCreate, GymUpdate

from sqlalchemy import select, func, exists

from app.features.members.models import Member


async def create_gym(
    db: AsyncSession,
    gym_data: GymCreate
) -> Gym:
    new_gym = Gym(
        name=gym_data.name,
        organization_id=gym_data.organization_id,
    )

    db.add(new_gym)
    await db.commit()
    await db.refresh(new_gym)

    return new_gym


async def get_all_gyms(
    db: AsyncSession,
    page: int,
    limit: int
):
    offset = (page - 1) * limit

    query = (
        select(Gym)
        .order_by(Gym.id)
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    gyms = result.scalars().all()

    count_query = select(func.count()).select_from(Gym)
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    return gyms, total





async def get_gym_by_id(
    db: AsyncSession,
    gym_id: int
):
    query = select(Gym).where(Gym.id == gym_id)

    result = await db.execute(query)

    gym = result.scalar_one_or_none()

    return gym




async def update_gym(
    db: AsyncSession,
    gym_id: int,
    gym_data: GymUpdate
):
    query = select(Gym).where(Gym.id == gym_id)
    result = await db.execute(query)
    gym = result.scalar_one_or_none()

    if gym is None:
        return None

    gym.name = gym_data.name

    await db.commit()
    await db.refresh(gym)

    return gym



async def delete_gym(
    db: AsyncSession,
    gym_id: int
):
    query = select(Gym).where(Gym.id == gym_id)
    result = await db.execute(query)
    gym = result.scalar_one_or_none()

    if gym is None:
        return "not_found"

    member_exists_query = select(
        exists().where(Member.gym_id == gym_id)
    )

    member_exists = await db.scalar(member_exists_query)

    if member_exists:
        return "has_members"

    await db.delete(gym)
    await db.commit()

    return "deleted"