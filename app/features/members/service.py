from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.members.models import Member
from app.features.memberships.models import MemberGymAssignment
from app.features.members.schemas import MemberCreate, MemberUpdate


async def create_member(
    db: AsyncSession,
    gym_id: int,
    member_data: MemberCreate,
):
    gym_result = await db.execute(select(Gym).where(Gym.id == gym_id))
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
    limit: int,
):
    gym_result = await db.execute(select(Gym.id).where(Gym.id == gym_id))
    if gym_result.scalar_one_or_none() is None:
        return None

    offset = (page - 1) * limit
    assignment_join = (
        (MemberGymAssignment.member_id == Member.id)
        & (MemberGymAssignment.organization_id == Member.organization_id)
    )
    members_query = (
        select(Member)
        .join(MemberGymAssignment, assignment_join)
        .where(
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.status == "active",
        )
        .order_by(Member.id)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(members_query)
    members = result.scalars().all()

    count_query = (
        select(func.count(Member.id))
        .select_from(Member)
        .join(MemberGymAssignment, assignment_join)
        .where(
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.status == "active",
        )
    )
    total = await db.scalar(count_query)
    return members, total


async def get_member_by_id(
    db: AsyncSession,
    gym_id: int,
    member_id: int,
):
    query = (
        select(Member)
        .join(
            MemberGymAssignment,
            (MemberGymAssignment.member_id == Member.id)
            & (MemberGymAssignment.organization_id == Member.organization_id),
        )
        .where(
            Member.id == member_id,
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.status == "active",
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_member(
    db: AsyncSession,
    gym_id: int,
    member_id: int,
    member_data: MemberUpdate,
):
    member = await get_member_by_id(db, gym_id, member_id)
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
    member_id: int,
):
    assignment_result = await db.execute(
        select(MemberGymAssignment).where(
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.member_id == member_id,
            MemberGymAssignment.status == "active",
        )
    )
    assignment = assignment_result.scalar_one_or_none()
    if assignment is None:
        return False

    member_result = await db.execute(
        select(Member).where(
            Member.id == member_id,
            Member.organization_id == assignment.organization_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        return False

    was_primary = assignment.is_primary
    assignment.status = "inactive"
    assignment.is_primary = False

    if member.gym_id == gym_id or was_primary:
        remaining_result = await db.execute(
            select(MemberGymAssignment)
            .where(
                MemberGymAssignment.organization_id == assignment.organization_id,
                MemberGymAssignment.member_id == member_id,
                MemberGymAssignment.status == "active",
            )
            .order_by(MemberGymAssignment.id)
        )
        remaining = remaining_result.scalars().all()
        if remaining:
            remaining[0].is_primary = True
            member.gym_id = remaining[0].gym_id

    await db.commit()
    return True
