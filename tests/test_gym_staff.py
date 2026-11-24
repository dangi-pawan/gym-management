
import pytest
import pytest_asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.features.gyms.models import Gym
from app.features.users.models import User
from app.features.users.gym_staff import GymStaff

from app.features.organizations.models import Organization

@pytest_asyncio.fixture
async def db_session(db_connection):
    TestSessionLocal = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    async with TestSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_assign_employee_to_multiple_gyms(
    db_session,
    organization_id,
):
    user = User(
        organization_id=organization_id,
        full_name="Test Employee",
        email="employee@example.com",
        password_hash="test-hash",
    )

    gym_one = Gym(
        name="Gym One",
        organization_id=organization_id,
    )

    gym_two = Gym(
        name="Gym Two",
        organization_id=organization_id,
    )

    db_session.add_all([user, gym_one, gym_two])
    await db_session.flush()

    assignment_one = GymStaff(
        user_id=user.id,
        gym_id=gym_one.id,
        organization_id=organization_id,
        role="trainer",
    )

    assignment_two = GymStaff(
        user_id=user.id,
        gym_id=gym_two.id,
        organization_id=organization_id,
        role="manager",
    )

    db_session.add_all([assignment_one, assignment_two])
    await db_session.commit()

    assert assignment_one.id is not None
    assert assignment_two.id is not None
    assert assignment_one.user_id == assignment_two.user_id
    assert assignment_one.gym_id != assignment_two.gym_id


@pytest.mark.asyncio
async def test_prevent_duplicate_employee_assignment(
    db_session,
    organization_id,
):
    user = User(
        organization_id=organization_id,
        full_name="Test Employee",
        email="employee@example.com",
        password_hash="test-hash",
    )

    gym = Gym(
        name="Test Gym",
        organization_id=organization_id,
    )

    db_session.add_all([user, gym])
    await db_session.flush()

    assignment = GymStaff(
        user_id=user.id,
        gym_id=gym.id,
        organization_id=organization_id,
        role="trainer",
    )

    db_session.add(assignment)
    await db_session.commit()

    duplicate_assignment = GymStaff(
        user_id=user.id,
        gym_id=gym.id,
        organization_id=organization_id,
        role="manager",
    )

    db_session.add(duplicate_assignment)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()



@pytest.mark.asyncio
async def test_prevent_cross_organization_staff_assignment(
    db_session,
    organization_id,
):
    # Create another organization.
    second_organization = Organization(
        name="Another Organization",
    )

    db_session.add(second_organization)
    await db_session.flush()

    # Employee belongs to the first organization.
    user = User(
        organization_id=organization_id,
        full_name="Test Employee",
        email="employee@example.com",
        password_hash="test-hash",
    )

    # Gym belongs to the second organization.
    gym = Gym(
        name="Another Organization Gym",
        organization_id=second_organization.id,
    )

    db_session.add_all([user, gym])
    await db_session.flush()

    # Attempt to assign the first organization's employee
    # to the second organization's gym.
    assignment = GymStaff(
        user_id=user.id,
        gym_id=gym.id,
        organization_id=organization_id,
        role="trainer",
    )

    db_session.add(assignment)

    with pytest.raises(IntegrityError):
        await db_session.commit()

    await db_session.rollback()
