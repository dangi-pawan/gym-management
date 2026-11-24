from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.features.users.schemas import UserCreate
from app.features.users.sessions import AuthSession
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


@pytest.mark.asyncio
async def test_password_reset_uses_single_use_email_token(
    client,
    organization_id,
    db_connection,
    monkeypatch,
):
    import re
    import app.features.users.auth_router as auth_router_module

    await _create_employee(db_connection, organization_id)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "no-reply@example.test")

    sent_messages = []

    async def fake_send_email(to_email, subject, body):
        sent_messages.append((to_email, subject, body))

    monkeypatch.setattr(auth_router_module, "send_email", fake_send_email)

    initial_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    assert initial_login.status_code == 200

    forgot = await client.post(
        "/auth/forgot-password",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
        },
    )
    assert forgot.status_code == 200
    assert len(sent_messages) == 1
    match = re.search(r"One-time reset token: (\S+)", sent_messages[0][2])
    assert match is not None

    reset = await client.post(
        "/auth/reset-password",
        json={
            "token": match.group(1),
            "new_password": "ResetPassword123",
        },
    )
    assert reset.status_code == 200
    assert (await client.get("/auth/me")).status_code == 401

    reused = await client.post(
        "/auth/reset-password",
        json={
            "token": match.group(1),
            "new_password": "AnotherResetPassword123",
        },
    )
    assert reused.status_code == 400

    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "ResetPassword123",
        },
    )
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_authenticated_mutation_rejects_missing_csrf_header(
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
    assert login.status_code == 200

    response = await client.post(
        "/auth/change-password",
        json={
            "current_password": "StrongPassword123",
            "new_password": "AnotherStrongPassword123",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_registration_requires_email_verification(
    client,
    monkeypatch,
):
    import re
    import app.features.users.auth_router as auth_router_module

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "no-reply@example.test")
    sent = []

    async def fake_send_email(to_email, subject, body):
        sent.append(body)

    monkeypatch.setattr(auth_router_module, "send_email", fake_send_email)

    registration = await client.post(
        "/auth/register",
        json={
            "organization_name": "Verified Club",
            "full_name": "Verified Owner",
            "email": "verified@example.com",
            "password": "StrongPassword123",
        },
    )
    assert registration.status_code == 202
    assert registration.json()["data"]["email_verification_required"] is True

    before_verification = await client.post(
        "/auth/login",
        json={
            "organization_slug": "verified-club",
            "email": "verified@example.com",
            "password": "StrongPassword123",
        },
    )
    assert before_verification.status_code == 401

    token = re.search(r"Verification token: (\S+)", sent[-1]).group(1)
    verified = await client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200
    assert verified.json()["data"]["csrf_token"]

    me = await client.get("/auth/me")
    assert me.status_code == 200

    reused = await client.post("/auth/verify-email", json={"token": token})
    assert reused.status_code == 400


@pytest.mark.asyncio
async def test_login_is_rate_limited_after_configured_failures(
    client,
    organization_id,
    db_connection,
    monkeypatch,
):
    await _create_employee(db_connection, organization_id)
    monkeypatch.setattr(settings, "LOGIN_MAX_ATTEMPTS", 2)

    payload = {
        "organization_slug": "test-organization",
        "email": "employee@example.com",
        "password": "WrongPassword123",
    }
    first = await client.post("/auth/login", json=payload)
    second = await client.post("/auth/login", json=payload)
    third = await client.post("/auth/login", json=payload)

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429


@pytest.mark.asyncio
async def test_logout_all_revokes_every_session(
    client,
    organization_id,
    db_connection,
):
    await _create_employee(db_connection, organization_id)
    first = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    first_access = client.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)

    second_client = client
    second = await second_client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee@example.com",
            "password": "StrongPassword123",
        },
    )
    assert first.status_code == 200 and second.status_code == 200
    csrf = second.json()["data"]["csrf_token"]
    logout_all = await client.post(
        "/auth/logout-all",
        headers={"X-CSRF-Token": csrf},
    )
    assert logout_all.status_code == 200
    assert (await client.get("/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_csrf_header_must_match_signed_cookie(
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
    assert login.status_code == 200

    rejected = await client.post(
        "/auth/change-password",
        headers={"X-CSRF-Token": "forged-token"},
        json={
            "current_password": "StrongPassword123",
            "new_password": "AnotherStrongPassword123",
        },
    )
    assert rejected.status_code == 403
    assert (await client.get("/auth/me")).status_code == 200


@pytest.mark.asyncio
async def test_refresh_cannot_extend_absolute_session_lifetime(
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
    assert login.status_code == 200

    session_factory = async_sessionmaker(
        bind=db_connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    async with session_factory() as session:
        auth_session = await session.scalar(
            select(AuthSession).where(AuthSession.user_id > 0).order_by(AuthSession.id.desc())
        )
        assert auth_session is not None
        auth_session.absolute_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    refresh = await client.post(
        "/auth/refresh",
        headers={"X-CSRF-Token": login.json()["data"]["csrf_token"]},
    )
    assert refresh.status_code == 401
    assert (await client.get("/auth/me")).status_code == 401
