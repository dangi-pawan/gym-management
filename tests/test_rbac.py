import re

import pytest

from app.core.config import settings


@pytest.mark.asyncio
async def test_owner_can_invite_employee_and_assign_gym_role(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    gym = await create_gym("RBAC Gym")
    gym_id = gym.json()["data"]["id"]

    invitation, accepted = await invite_employee(
        "Gym Manager",
        "manager@example.com",
    )
    assert invitation.status_code == 202
    assert accepted.status_code == 200
    employee_id = invitation.json()["data"]["user_id"]

    assignment = await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": employee_id, "role": "manager"},
    )
    assert assignment.status_code == 201
    assert assignment.json()["data"]["role"] == "manager"


@pytest.mark.asyncio
async def test_manager_can_create_members_but_trainer_is_read_only(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    gym = await create_gym("Manager Gym")
    gym_id = gym.json()["data"]["id"]
    invitation, accepted = await invite_employee(
        "Gym Manager",
        "manager@example.com",
    )
    assert invitation.status_code == 202 and accepted.status_code == 200
    manager_id = invitation.json()["data"]["user_id"]
    assignment = await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": manager_id, "role": "manager"},
    )
    assert assignment.status_code == 201

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME)},
    )
    manager_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "manager@example.com",
            "password": "StrongPassword123",
        },
    )
    assert manager_login.status_code == 200
    client.headers["X-CSRF-Token"] = manager_login.json()["data"]["csrf_token"]

    created = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Member One", "age": 28},
    )
    assert created.status_code == 201


@pytest.mark.asyncio
async def test_organization_owner_cannot_access_another_tenants_gym(
    client,
    monkeypatch,
):
    import app.features.users.auth_router as auth_router_module

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "no-reply@example.test")
    sent = []

    async def fake_send_email(to_email, subject, body):
        sent.append(body)

    monkeypatch.setattr(auth_router_module, "send_email", fake_send_email)

    first_registration = await client.post(
        "/auth/register",
        json={
            "organization_name": "First Tenant",
            "full_name": "First Owner",
            "email": "first@example.com",
            "password": "StrongPassword123",
        },
    )
    assert first_registration.status_code == 202
    first_token = re.search(r"Verification token: (\S+)", sent[-1]).group(1)
    verified = await client.post("/auth/verify-email", json={"token": first_token})
    assert verified.status_code == 200
    client.headers["X-CSRF-Token"] = verified.json()["data"]["csrf_token"]
    first_gym = await client.post("/gyms/", json={"name": "First Gym"})
    first_gym_id = first_gym.json()["data"]["id"]

    second_registration = await client.post(
        "/auth/register",
        json={
            "organization_name": "Second Tenant",
            "full_name": "Second Owner",
            "email": "second@example.com",
            "password": "StrongPassword123",
        },
    )
    assert second_registration.status_code == 202
    second_token = re.search(r"Verification token: (\S+)", sent[-1]).group(1)
    second_verified = await client.post(
        "/auth/verify-email",
        json={"token": second_token},
    )
    assert second_verified.status_code == 200

    response = await client.get(f"/gyms/{first_gym_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trainer_cannot_create_or_update_members(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    gym = await create_gym("Trainer Gym")
    gym_id = gym.json()["data"]["id"]
    created_member = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Existing Member", "age": 26},
    )
    assert created_member.status_code == 201
    member_id = created_member.json()["data"]["id"]

    invitation, accepted = await invite_employee(
        "Gym Trainer",
        "trainer@example.com",
    )
    assert invitation.status_code == 202 and accepted.status_code == 200
    employee_id = invitation.json()["data"]["user_id"]
    assignment = await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": employee_id, "role": "trainer"},
    )
    assert assignment.status_code == 201

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME)},
    )
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "trainer@example.com",
            "password": "StrongPassword123",
        },
    )
    assert login.status_code == 200
    client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "New Member", "age": 26},
    )
    assert response.status_code == 403
    update = await client.put(
        f"/gyms/{gym_id}/members/{member_id}",
        json={"name": "Changed", "age": 27},
    )
    assert update.status_code == 403


@pytest.mark.asyncio
async def test_deactivating_employee_prevents_future_login(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    await create_gym("Account Control Gym")
    invitation, accepted = await invite_employee(
        "Employee Account",
        "employee-status@example.com",
    )
    assert invitation.status_code == 202 and accepted.status_code == 200
    employee_id = invitation.json()["data"]["user_id"]

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME)},
    )
    employee_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee-status@example.com",
            "password": "StrongPassword123",
        },
    )
    assert employee_login.status_code == 200

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME)},
    )
    owner_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "owner@example.com",
            "password": "OwnerPassword123",
        },
    )
    assert owner_login.status_code == 200
    client.headers["X-CSRF-Token"] = owner_login.json()["data"]["csrf_token"]

    deactivated = await client.patch(
        f"/organizations/{organization_id}/employees/{employee_id}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    blocked_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "employee-status@example.com",
            "password": "StrongPassword123",
        },
    )
    assert blocked_login.status_code == 401


@pytest.mark.asyncio
async def test_owner_can_transfer_ownership_and_old_owner_becomes_admin(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    await create_gym("Ownership Transfer Gym")
    invitation, accepted = await invite_employee(
        "New Owner",
        "new-owner@example.com",
    )
    assert invitation.status_code == 202 and accepted.status_code == 200
    new_owner_id = invitation.json()["data"]["user_id"]

    transfer = await client.post(
        f"/organizations/{organization_id}/ownership/transfer",
        json={"new_owner_user_id": new_owner_id},
    )
    assert transfer.status_code == 200

    me = await client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["data"]["organization_role"] == "admin"


@pytest.mark.asyncio
async def test_admin_cannot_invite_another_organization_admin(
    client,
    organization_id,
    create_gym,
    invite_employee,
):
    await create_gym("Admin Invitation Gym")
    admin_invitation, accepted = await invite_employee(
        "Organization Admin",
        "org-admin@example.com",
        organization_role="admin",
    )
    assert admin_invitation.status_code == 202
    assert accepted.status_code == 200

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME)},
    )
    admin_login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "org-admin@example.com",
            "password": "StrongPassword123",
        },
    )
    assert admin_login.status_code == 200
    client.headers["X-CSRF-Token"] = admin_login.json()["data"]["csrf_token"]

    response = await client.post(
        f"/organizations/{organization_id}/employees/invitations",
        json={
            "full_name": "Second Admin",
            "email": "second-admin@example.com",
            "organization_role": "admin",
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_resending_invitation_invalidates_previous_token(
    client,
    organization_id,
    create_gym,
    monkeypatch,
):
    import app.features.users.router as employee_router_module

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "no-reply@example.test")
    sent = []

    async def fake_send_email(to_email, subject, body):
        sent.append(body)

    monkeypatch.setattr(employee_router_module, "send_email", fake_send_email)
    await create_gym("Invitation Resend Gym")

    invited = await client.post(
        f"/organizations/{organization_id}/employees/invitations",
        json={"full_name": "Pending Employee", "email": "pending@example.com"},
    )
    assert invited.status_code == 202
    user_id = invited.json()["data"]["user_id"]
    old_token = re.search(r"Invitation token: (\S+)", sent[-1]).group(1)

    resent = await client.post(
        f"/organizations/{organization_id}/employees/{user_id}/invitation/resend"
    )
    assert resent.status_code == 202
    new_token = re.search(r"Invitation token: (\S+)", sent[-1]).group(1)
    assert new_token != old_token

    old_acceptance = await client.post(
        "/auth/accept-invitation",
        json={"token": old_token, "password": "StrongPassword123"},
    )
    assert old_acceptance.status_code == 400

    new_acceptance = await client.post(
        "/auth/accept-invitation",
        json={"token": new_token, "password": "StrongPassword123"},
    )
    assert new_acceptance.status_code == 200


@pytest.mark.asyncio
async def test_deactivating_pending_invitation_invalidates_token(
    client,
    organization_id,
    create_gym,
    monkeypatch,
):
    import app.features.users.router as employee_router_module

    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", "no-reply@example.test")
    sent = []

    async def fake_send_email(to_email, subject, body):
        sent.append(body)

    monkeypatch.setattr(employee_router_module, "send_email", fake_send_email)
    await create_gym("Pending Deactivation Gym")

    invited = await client.post(
        f"/organizations/{organization_id}/employees/invitations",
        json={"full_name": "Pending Employee", "email": "pending-deactivate@example.com"},
    )
    assert invited.status_code == 202
    user_id = invited.json()["data"]["user_id"]
    token = re.search(r"Invitation token: (\S+)", sent[-1]).group(1)

    deactivated = await client.patch(
        f"/organizations/{organization_id}/employees/{user_id}/status",
        json={"is_active": False},
    )
    assert deactivated.status_code == 200

    accepted = await client.post(
        "/auth/accept-invitation",
        json={"token": token, "password": "StrongPassword123"},
    )
    assert accepted.status_code == 400
