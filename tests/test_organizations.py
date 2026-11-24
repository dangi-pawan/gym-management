import pytest


async def _register(client, organization_name):
    response = await client.post(
        "/auth/register",
        json={
            "organization_name": organization_name,
            "full_name": "Organization Owner",
            "email": "owner@example.com",
            "password": "StrongPassword123",
        },
    )
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["data"]["csrf_token"]
    return response


async def _current_organization(client):
    response = await client.get("/organizations/")
    assert response.status_code == 200
    return response.json()["data"][0]


@pytest.mark.asyncio
async def test_register_organization_creates_owner_and_session(client):
    response = await _register(client, "Test Organization")
    assert response.json()["success"] is True
    assert response.json()["data"]["csrf_token"]

    organization = await _current_organization(client)
    assert organization["name"] == "Test Organization"
    assert organization["slug"] == "test-organization"


@pytest.mark.asyncio
async def test_organization_listing_is_tenant_scoped(client):
    await _register(client, "Organization One")
    first = await _current_organization(client)
    await _register(client, "Organization Two")
    second = await _current_organization(client)

    assert first["name"] == "Organization One"
    assert second["name"] == "Organization Two"
    assert first["id"] != second["id"]


@pytest.mark.asyncio
async def test_get_organization_by_id(client):
    await _register(client, "Get Organization")
    organization = await _current_organization(client)

    response = await client.get(f"/organizations/{organization['id']}")
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Get Organization"


@pytest.mark.asyncio
async def test_update_organization(client):
    await _register(client, "Old Organization")
    organization = await _current_organization(client)

    response = await client.put(
        f"/organizations/{organization['id']}",
        json={"name": "Updated Organization"},
    )
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Updated Organization"
    assert response.json()["data"]["slug"] == "old-organization"


@pytest.mark.asyncio
async def test_delete_organization(client):
    await _register(client, "Delete Organization")
    organization = await _current_organization(client)

    response = await client.delete(f"/organizations/{organization['id']}")
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"] is None


@pytest.mark.asyncio
async def test_cannot_delete_organization_with_gyms(
    client,
    organization_id,
    create_gym,
):
    await create_gym("Test Gym")

    response = await client.delete(f"/organizations/{organization_id}")
    assert response.status_code == 409
    assert response.json()["success"] is False


@pytest.mark.asyncio
async def test_cross_tenant_organization_access_is_hidden(client):
    await _register(client, "Organization One")
    first = await _current_organization(client)
    await _register(client, "Organization Two")

    response = await client.get(f"/organizations/{first['id']}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_organization_access_is_rejected(client):
    response = await client.get("/organizations/")
    assert response.status_code == 401
