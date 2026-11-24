import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.features.users.schemas import UserCreate
from app.features.users.service import create_user


async def _create_employee(db_connection, organization_id):
    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        return await create_user(
            session,
            organization_id,
            UserCreate(
                full_name="Test Employee",
                email="employee@example.com",
                password="StrongPassword123",
            ),
        )


@pytest.mark.asyncio
async def test_employee_login_returns_access_token(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)

    response = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "EMPLOYEE@example.com",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["token_type"] == "bearer"

    claims = jwt.decode(
        payload["data"]["access_token"],
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert claims["sub"]
    assert claims["org_id"] == organization_id
    assert claims["type"] == "access"


@pytest.mark.asyncio
async def test_employee_login_rejects_invalid_password(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)

    response = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "WrongPassword123",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_employee_login_rejects_unknown_organization(client):
    response = await client.post(
        "/auth/login",
        json={
            "organization_slug": "unknown-club",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"



@pytest.mark.asyncio
async def test_authenticated_employee_endpoint_returns_current_user(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)

    login_response = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    access_token = login_response.json()["data"]["access_token"]

    response = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["email"] == "employee@example.com"
    assert payload["data"]["organization_id"] == organization_id


@pytest.mark.asyncio
async def test_authenticated_employee_endpoint_rejects_missing_token(client):
    response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_authenticated_employee_endpoint_rejects_invalid_token(client):
    response = await client.get(
        "/auth/me",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401
