import pytest


@pytest.mark.asyncio
async def test_create_member(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )

    gym_id = gym_response.json()["data"]["id"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={
            "name": "Rahul",
            "age": 25
        }
    )

    assert response.status_code == 201

    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "Rahul"
    assert data["data"]["age"] == 25
    assert data["data"]["gym_id"] == gym_id


@pytest.mark.asyncio
async def test_get_all_members(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )

    gym_id = gym_response.json()["data"]["id"]

    await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Amit", "age": 26}
    )

    response = await client.get(
        f"/gyms/{gym_id}/members/"
    )

    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 2
    assert len(data["data"]) == 2


@pytest.mark.asyncio
async def test_get_member_by_id(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )

    gym_id = gym_response.json()["data"]["id"]

    member_response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    member_id = member_response.json()["data"]["id"]

    response = await client.get(
        f"/gyms/{gym_id}/members/{member_id}"
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Rahul"


@pytest.mark.asyncio
async def test_update_member(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )

    gym_id = gym_response.json()["data"]["id"]

    member_response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    member_id = member_response.json()["data"]["id"]

    response = await client.put(
        f"/gyms/{gym_id}/members/{member_id}",
        json={"name": "Rahul Kumar", "age": 26}
    )

    assert response.status_code == 200
    assert response.json()["data"]["name"] == "Rahul Kumar"
    assert response.json()["data"]["age"] == 26


@pytest.mark.asyncio
async def test_delete_member(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )

    gym_id = gym_response.json()["data"]["id"]

    member_response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    member_id = member_response.json()["data"]["id"]

    response = await client.delete(
        f"/gyms/{gym_id}/members/{member_id}"
    )

    assert response.status_code == 200

    get_response = await client.get(
        f"/gyms/{gym_id}/members/{member_id}"
    )

    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_member_tenant_isolation(client):
    gym1_response = await client.post(
        "/gyms/",
        json={"name": "Gym One"}
    )

    gym2_response = await client.post(
        "/gyms/",
        json={"name": "Gym Two"}
    )

    gym1_id = gym1_response.json()["data"]["id"]
    gym2_id = gym2_response.json()["data"]["id"]

    member_response = await client.post(
        f"/gyms/{gym1_id}/members/",
        json={"name": "Rahul", "age": 25}
    )

    member_id = member_response.json()["data"]["id"]

    response = await client.get(
        f"/gyms/{gym2_id}/members/{member_id}"
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_member_for_nonexistent_gym(client):
    response = await client.post(
        "/gyms/9999/members/",
        json={"name": "Rahul", "age": 25}
    )

    assert response.status_code == 404 






async def test_create_member_with_short_name(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "A", "age": 25}
    )

    assert response.status_code == 422


async def test_create_member_with_zero_age(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 0}
    )

    assert response.status_code == 422


async def test_create_member_with_age_above_limit(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Rahul", "age": 121}
    )

    assert response.status_code == 422


async def test_create_member_with_whitespace_name(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "   ", "age": 25}
    )

    assert response.status_code == 422




async def test_update_nonexistent_member(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.put(
        f"/gyms/{gym_id}/members/999999",
        json={"name": "Rahul", "age": 25}
    )

    assert response.status_code == 404


async def test_delete_nonexistent_member(client):
    gym_response = await client.post(
        "/gyms/",
        json={"name": "Test Gym"}
    )
    gym_id = gym_response.json()["data"]["id"]

    response = await client.delete(
        f"/gyms/{gym_id}/members/999999"
    )

    assert response.status_code == 404
