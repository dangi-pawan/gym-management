import pytest


@pytest.mark.asyncio
async def test_owner_can_create_employee_and_assign_gym_role(
    client,
    organization_id,
    create_gym,
):
    gym = await create_gym("RBAC Gym")
    gym_id = gym.json()["data"]["id"]

    employee_response = await client.post(
        f"/organizations/{organization_id}/employees/",
        json={
            "full_name": "Gym Manager",
            "email": "manager@example.com",
            "password": "StrongPassword123",
        },
    )
    assert employee_response.status_code == 201
    employee_id = employee_response.json()["data"]["id"]

    assignment = await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": employee_id, "role": "manager"},
    )
    assert assignment.status_code == 201
    assert assignment.json()["data"]["role"] == "manager"


@pytest.mark.asyncio
async def test_manager_can_manage_members(
    client,
    organization_id,
    create_gym,
):
    gym = await create_gym("Manager Gym")
    gym_id = gym.json()["data"]["id"]

    employee = await client.post(
        f"/organizations/{organization_id}/employees/",
        json={
            "full_name": "Gym Manager",
            "email": "manager@example.com",
            "password": "StrongPassword123",
        },
    )
    employee_id = employee.json()["data"]["id"]
    await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": employee_id, "role": "manager"},
    )

    await client.post("/auth/logout", headers={
        "X-CSRF-Token": client.cookies.get("csrf_token")
    })
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "manager@example.com",
            "password": "StrongPassword123",
        },
    )
    client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]

    created = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Member One", "age": 28},
    )
    assert created.status_code == 201


@pytest.mark.asyncio
async def test_organization_owner_cannot_access_another_tenants_gym(
    client,
):
    first_registration = await client.post(
        "/auth/register",
        json={
            "organization_name": "First Tenant",
            "full_name": "First Owner",
            "email": "first@example.com",
            "password": "StrongPassword123",
        },
    )
    client.headers["X-CSRF-Token"] = first_registration.json()["data"]["csrf_token"]
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
    client.headers["X-CSRF-Token"] = second_registration.json()["data"]["csrf_token"]

    response = await client.get(f"/gyms/{first_gym_id}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_trainer_cannot_create_member(
    client,
    organization_id,
    create_gym,
):
    gym = await create_gym("Trainer Gym")
    gym_id = gym.json()["data"]["id"]
    employee = await client.post(
        f"/organizations/{organization_id}/employees/",
        json={
            "full_name": "Gym Trainer",
            "email": "trainer@example.com",
            "password": "StrongPassword123",
        },
    )
    employee_id = employee.json()["data"]["id"]
    await client.post(
        f"/gyms/{gym_id}/staff/",
        json={"user_id": employee_id, "role": "trainer"},
    )

    await client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": client.cookies.get("csrf_token")},
    )
    login = await client.post(
        "/auth/login",
        json={
            "organization_slug": "test-organization",
            "email": "trainer@example.com",
            "password": "StrongPassword123",
        },
    )
    client.headers["X-CSRF-Token"] = login.json()["data"]["csrf_token"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "New Member", "age": 26},
    )
    assert response.status_code == 403
