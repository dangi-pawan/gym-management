
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.members.models import Member
from app.features.memberships.models import MemberGymAssignment
from app.features.members.schemas import MemberCreate, MemberUpdate


async def create_member(
    db: AsyncSession,
    gym_id: int,
    member_data: MemberCreate
):
    gym_query = select(Gym).where(Gym.id == gym_id)
    gym_result = await db.execute(gym_query)
    gym = gym_result.scalar_one_or_none()

    if gym is None:
        return None

    new_member = Member(
        gym_id=gym_id,
        organization_id=gym.organization_id,
        name=member_data.name,
        age=member_data.age,
    )

    db.add(new_member)
    await db.flush()
    db.add(
        MemberGymAssignment(
            organization_id=gym.organization_id,
            member_id=new_member.id,
            gym_id=gym_id,
            is_primary=True,
            status="active",
        )
    )
    await db.commit()
    await db.refresh(new_member)

    return new_member



async def get_all_members(
    db: AsyncSession,
    gym_id: int,
    page: int,
    limit: int
):
    gym_query = select(Gym.id).where(Gym.id == gym_id)
    gym_result = await db.execute(gym_query)

    if gym_result.scalar_one_or_none() is None:
        return None

    offset = (page - 1) * limit

    members_query = (
        select(Member)
        .where(Member.gym_id == gym_id)
        .order_by(Member.id)
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(members_query)
    members = result.scalars().all()

    count_query = (
        select(func.count())
        .select_from(Member)
        .where(Member.gym_id == gym_id)
    )

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    return members, total


async def get_member_by_id(
    db: AsyncSession,
    gym_id: int,
    member_id: int
):
    query = select(Member).where(
        Member.id == member_id,
        Member.gym_id == gym_id
    )

    result = await db.execute(query)

    return result.scalar_one_or_none()

async def update_member(
    db: AsyncSession,
    gym_id: int,
    member_id: int,
    member_data: MemberUpdate
):
    query = select(Member).where(
        Member.id == member_id,
        Member.gym_id == gym_id
    )

    result = await db.execute(query)
    member = result.scalar_one_or_none()

    if member is None:
        return None

    member.name = member_data.name
    member.age = member_data.age

    await db.commit()
    await db.refresh(member)

    return member



async def delete_member(
    db: AsyncSession,
    gym_id: int,
    member_id: int
):
    query = select(Member).where(
        Member.id == member_id,
        Member.gym_id == gym_id
    )

    result = await db.execute(query)
    member = result.scalar_one_or_none()

    if member is None:
        return False

    await db.delete(member)
    await db.commit()

    return True