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
async def test_employee_login_sets_http_only_auth_cookies(
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
    assert "access_token" not in payload["data"]
    assert "refresh_token" not in payload["data"]
    assert payload["data"]["csrf_token"]

    cookies = {cookie.name: cookie for cookie in response.cookies.jar}
    assert settings.ACCESS_TOKEN_COOKIE_NAME in cookies
    assert settings.REFRESH_TOKEN_COOKIE_NAME in cookies
    assert settings.CSRF_TOKEN_COOKIE_NAME in cookies
    assert cookies[settings.ACCESS_TOKEN_COOKIE_NAME].has_nonstandard_attr("HttpOnly")
    assert cookies[settings.REFRESH_TOKEN_COOKIE_NAME].has_nonstandard_attr("HttpOnly")
    assert not cookies[settings.CSRF_TOKEN_COOKIE_NAME].has_nonstandard_attr("HttpOnly")


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

    response = await client.get("/auth/me")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["email"] == "employee@example.com"
    assert payload["data"]["organization_id"] == organization_id


@pytest.mark.asyncio
async def test_authenticated_employee_endpoint_rejects_missing_cookie(client):
    response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_authenticated_employee_endpoint_rejects_invalid_cookie(client):
    client.cookies.set(settings.ACCESS_TOKEN_COOKIE_NAME, "not-a-valid-token")
    response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_refresh_cookie_and_rejects_reuse(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    csrf = login.json()["data"]["csrf_token"]
    old_refresh = client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME)

    refreshed = await client.post(
        "/auth/refresh",
        headers={"X-CSRF-Token": csrf},
    )
    assert refreshed.status_code == 200
    assert client.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME) != old_refresh

    new_csrf = refreshed.json()["data"]["csrf_token"]
    for cookie in client.cookies.jar:
        if cookie.name == settings.REFRESH_TOKEN_COOKIE_NAME:
            cookie.value = old_refresh
    reused = await client.post(
        "/auth/refresh",
        headers={"X-CSRF-Token": new_csrf},
    )
    assert reused.status_code == 401

    revoked_access = await client.get("/auth/me")
    assert revoked_access.status_code == 401


@pytest.mark.asyncio
async def test_mutating_cookie_authenticated_request_requires_csrf(client):
    # Login cookie setup is exercised by the other tests. This verifies that
    # refresh cannot be invoked without the double-submit CSRF header.
    response = await client.post("/auth/refresh")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_password_change_revokes_existing_sessions(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    csrf = login.json()["data"]["csrf_token"]
    changed = await client.post(
        "/auth/change-password",
        headers={"X-CSRF-Token": csrf},
        json={
            "current_password": "StrongPassword123",
            "new_password": "AnotherStrongPassword123",
        },
    )
    assert changed.status_code == 200
    assert (await client.get("/auth/me")).status_code == 401

    relogin = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "AnotherStrongPassword123",
        },
    )
    assert relogin.status_code == 200


@pytest.mark.asyncio
async def test_logout_revokes_session(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    csrf = login.json()["data"]["csrf_token"]
    logout = await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": csrf},
    )
    assert logout.status_code == 200
    assert (await client.get("/auth/me")).status_code == 401
