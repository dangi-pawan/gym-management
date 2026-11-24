import pytest_asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.session import get_db
from app.main import app

from app.features.organizations.models import Organization


@pytest_asyncio.fixture
async def db_connection():
    test_engine = create_async_engine(
        settings.DATABASE_URL,
        poolclass=NullPool,
    )

    async with test_engine.connect() as connection:
        transaction = await connection.begin()

        try:
            yield connection
        finally:
            if transaction.is_active:
                await transaction.rollback()

    await test_engine.dispose()


@pytest_asyncio.fixture
async def organization_id(db_connection):
    TestSessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    async with TestSessionLocal() as session:
        organization = Organization(
            name="Test Organization",
            slug="test-organization",
        )

        session.add(organization)
        await session.commit()

        return organization.id


@pytest_asyncio.fixture
async def create_gym(client, organization_id):
    async def _create(name):
        return await client.post(
            "/gyms/",
            json={
                "name": name,
                "organization_id": organization_id,
            },
        )

    return _create


@pytest_asyncio.fixture
async def client(db_connection):
    TestSessionLocal = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )

    async def override_get_db():
        async with TestSessionLocal() as session:
            yield session

    previous_override = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = override_get_db

    try:
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as test_client:
            yield test_client

    finally:
        if previous_override is not None:
            app.dependency_overrides[get_db] = previous_override
        else:
            app.dependency_overrides.pop(get_db, None)
