
import pytest


@pytest.mark.asyncio
async def test_create_organization(client):
    response = await client.post(
        "/organizations/",
        json={"name": "Test Organization"},
    )

    assert response.status_code == 201

    data = response.json()

    assert data["success"] is True
    assert data["data"]["name"] == "Test Organization"
    assert data["data"]["id"] is not None


@pytest.mark.asyncio
async def test_get_all_organizations(client):
    await client.post(
        "/organizations/",
        json={"name": "Organization One"},
    )

    await client.post(
        "/organizations/",
        json={"name": "Organization Two"},
    )

    response = await client.get("/organizations/")

    assert response.status_code == 200

    data = response.json()["data"]
    names = [organization["name"] for organization in data]

    assert "Organization One" in names
    assert "Organization Two" in names


@pytest.mark.asyncio
async def test_get_organization_by_id(client):
    create_response = await client.post(
        "/organizations/",
        json={"name": "Get Organization"},
    )

    organization_id = create_response.json()["data"]["id"]

    response = await client.get(
        f"/organizations/{organization_id}"
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Get Organization"


@pytest.mark.asyncio
async def test_update_organization(client):
    create_response = await client.post(
        "/organizations/",
        json={"name": "Old Organization"},
    )

    organization_id = create_response.json()["data"]["id"]

    response = await client.put(
        f"/organizations/{organization_id}",
        json={"name": "Updated Organization"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Updated Organization"


@pytest.mark.asyncio
async def test_delete_organization(client):
    create_response = await client.post(
        "/organizations/",
        json={"name": "Delete Organization"},
    )

    organization_id = create_response.json()["data"]["id"]

    response = await client.delete(
        f"/organizations/{organization_id}"
    )

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

    response = await client.delete(
        f"/organizations/{organization_id}"
    )

    assert response.status_code == 409
    assert response.json()["success"] is False


@pytest.mark.asyncio
async def test_get_nonexistent_organization(client):
    response = await client.get("/organizations/99999999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_nonexistent_organization(client):
    response = await client.put(
        "/organizations/99999999",
        json={"name": "Updated Organization"},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_nonexistent_organization(client):
    response = await client.delete("/organizations/99999999")

    assert response.status_code == 404
