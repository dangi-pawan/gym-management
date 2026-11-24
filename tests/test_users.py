
import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.security import verify_password
from app.features.organizations.models import Organization
from app.features.users.schemas import UserCreate
from app.features.users.service import create_user


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
async def test_create_user(db_session, organization_id):
    user_data = UserCreate(
        full_name="Test Employee",
        email="employee@example.com",
        password="StrongPassword123",
    )

    user = await create_user(
        db_session,
        organization_id,
        user_data,
    )

    assert user is not None
    assert user.id is not None
    assert user.organization_id == organization_id
    assert user.email == "employee@example.com"
    assert user.full_name == "Test Employee"

    # Password must never be stored as plain text.
    assert user.password_hash != user_data.password

    # Verify the stored password hash.
    assert verify_password(
        user_data.password,
        user.password_hash,
    )


@pytest.mark.asyncio
async def test_duplicate_email_in_same_organization(
    db_session,
    organization_id,
):
    user_data = UserCreate(
        full_name="Test Employee",
        email="employee@example.com",
        password="StrongPassword123",
    )

    first_user = await create_user(
        db_session,
        organization_id,
        user_data,
    )

    second_user = await create_user(
        db_session,
        organization_id,
        user_data,
    )

    assert first_user is not None
    assert second_user is None


@pytest.mark.asyncio
async def test_same_email_allowed_in_different_organizations(
    db_session,
    organization_id,
):
    second_organization = Organization(
        name="Another Test Organization",
    )

    db_session.add(second_organization)
    await db_session.commit()
    await db_session.refresh(second_organization)

    user_data = UserCreate(
        full_name="Test Employee",
        email="employee@example.com",
        password="StrongPassword123",
    )

    first_user = await create_user(
        db_session,
        organization_id,
        user_data,
    )

    second_user = await create_user(
        db_session,
        second_organization.id,
        user_data,
    )

    assert first_user is not None
    assert second_user is not None
    assert first_user.email == second_user.email
    assert first_user.organization_id != second_user.organization_id
