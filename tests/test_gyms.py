import pytest


@pytest.mark.asyncio
async def test_create_gym(client):
    response = await client.post(
        "/gyms/",
        json={"name": "Automated Test Gym"}
    )

    assert response.status_code == 201

    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Automated Test Gym"


@pytest.mark.asyncio
async def test_get_all_gyms(client):
    await client.post("/gyms/", json={"name": "Gym One"})
    await client.post("/gyms/", json={"name": "Gym Two"})

    response = await client.get("/gyms/")

    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["total"] == 2
    assert len(data["data"]["gyms"]) == 2


@pytest.mark.asyncio
async def test_get_gym_by_id(client):
    create_response = await client.post(
        "/gyms/",
        json={"name": "Gym One"}
    )

    gym_id = create_response.json()["data"]["id"]

    response = await client.get(f"/gyms/{gym_id}")

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Gym One"


@pytest.mark.asyncio
async def test_get_nonexistent_gym(client):
    response = await client.get("/gyms/9999")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_gym(client):
    create_response = await client.post(
        "/gyms/",
        json={"name": "Old Gym"}
    )

    gym_id = create_response.json()["data"]["id"]

    response = await client.put(
        f"/gyms/{gym_id}",
        json={"name": "Updated Gym"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Updated Gym"


@pytest.mark.asyncio
async def test_delete_gym(client):
    create_response = await client.post(
        "/gyms/",
        json={"name": "Gym To Delete"}
    )

    gym_id = create_response.json()["data"]["id"]

    response = await client.delete(f"/gyms/{gym_id}")

    assert response.status_code == 200

    get_response = await client.get(f"/gyms/{gym_id}")
    assert get_response.status_code == 404 





async def test_delete_gym_with_members(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    response = await client.delete(f"/gyms/{gym_id}")

    assert response.status_code == 409
