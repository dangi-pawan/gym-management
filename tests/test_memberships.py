from datetime import date

import pytest


@pytest.mark.asyncio
async def test_membership_plan_subscription_payment_invoice_and_private_documents(
    client,
    create_gym,
    organization_id,
    monkeypatch,
    tmp_path,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "MEMBERSHIP_DOCUMENTS_DIR", str(tmp_path))

    gym_response = await create_gym("Membership Test Gym")
    gym_id = gym_response.json()["data"]["id"]

    member_response = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Membership Member", "age": 28},
    )
    assert member_response.status_code == 201
    member_id = member_response.json()["data"]["id"]

    terms_response = await client.post(
        f"/organizations/{organization_id}/membership-terms",
        json={
            "title": "Membership Terms",
            "content": "Members must follow gym safety and conduct policies.",
        },
    )
    assert terms_response.status_code == 201
    terms_id = terms_response.json()["data"]["id"]

    publish_response = await client.post(
        f"/organizations/{organization_id}/membership-terms/{terms_id}/publish"
    )
    assert publish_response.status_code == 200
    assert publish_response.json()["data"]["status"] == "published"

    plan_response = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "Monthly Fitness",
            "duration_value": 1,
            "duration_unit": "month",
            "base_price": "1000.00",
            "joining_fee": "100.00",
            "currency": "INR",
            "access_type": "home_gym",
            "terms_id": terms_id,
        },
    )
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["data"]["id"]
    assert plan_response.json()["data"]["status"] == "draft"

    availability_response = await client.put(
        f"/gyms/{gym_id}/membership-plans/{plan_id}",
        json={
            "is_available": True,
            "price_override": "850.00",
            "joining_fee_override": "50.00",
        },
    )
    assert availability_response.status_code == 200

    activate_response = await client.post(
        f"/organizations/{organization_id}/membership-plans/{plan_id}/activate"
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["data"]["status"] == "active"

    subscription_response = await client.post(
        f"/gyms/{gym_id}/members/{member_id}/subscriptions",
        json={
            "member_id": member_id,
            "membership_plan_id": plan_id,
            "start_date": date.today().isoformat(),
            "terms_accepted": True,
            "acceptance_method": "staff_assisted",
        },
    )
    assert subscription_response.status_code == 201
    subscription = subscription_response.json()["data"]
    subscription_id = subscription["id"]
    assert subscription["status"] == "pending_payment"
    assert subscription["plan_price_snapshot"] == "850.00"
    assert subscription["joining_fee_snapshot"] == "50.00"
    assert subscription["access_gym_ids"] == [gym_id]

    access_before_payment = await client.get(
        f"/gyms/{gym_id}/members/{member_id}/membership-access"
    )
    assert access_before_payment.status_code == 200
    assert access_before_payment.json()["data"]["has_access"] is False

    payment_response = await client.post(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/payments/manual",
        json={"payment_method": "upi", "provider_reference": "TEST-UPI-001"},
    )
    assert payment_response.status_code == 200
    assert payment_response.json()["data"]["status"] == "succeeded"
    assert payment_response.json()["data"]["amount"] == "900.00"

    subscription_detail = await client.get(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}"
    )
    assert subscription_detail.status_code == 200
    assert subscription_detail.json()["data"]["status"] == "active"

    access_after_payment = await client.get(
        f"/gyms/{gym_id}/members/{member_id}/membership-access"
    )
    assert access_after_payment.status_code == 200
    assert access_after_payment.json()["data"]["has_access"] is True
    assert access_after_payment.json()["data"]["active_subscription_ids"] == [subscription_id]

    invoice_response = await client.get(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/invoice"
    )
    assert invoice_response.status_code == 200
    assert invoice_response.json()["data"]["total_amount"] == "900.00"
    assert invoice_response.json()["data"]["status"] == "issued"

    documents_response = await client.get(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/documents"
    )
    assert documents_response.status_code == 200
    documents = documents_response.json()["data"]
    assert {item["document_type"] for item in documents} == {
        "agreement",
        "invoice",
        "receipt",
    }

    agreement = next(item for item in documents if item["document_type"] == "agreement")
    download_response = await client.get(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/documents/{agreement['id']}"
    )
    assert download_response.status_code == 200
    assert download_response.headers["content-type"] == "application/pdf"
    assert download_response.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_selected_gym_plan_rejects_purchase_outside_access_list(
    client,
    create_gym,
    organization_id,
):
    gym_one = (await create_gym("Purchase Gym")).json()["data"]["id"]
    gym_two = (await create_gym("Selected Access Gym")).json()["data"]["id"]
    member_response = await client.post(
        f"/gyms/{gym_one}/members/",
        json={"name": "Selected Gym Member", "age": 30},
    )
    member_id = member_response.json()["data"]["id"]

    plan_response = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "Selected Branch Plan",
            "duration_value": 30,
            "duration_unit": "day",
            "base_price": "500.00",
            "access_type": "selected_gyms",
            "selected_gym_ids": [gym_two],
        },
    )
    assert plan_response.status_code == 201
    plan_id = plan_response.json()["data"]["id"]

    availability = await client.put(
        f"/gyms/{gym_one}/membership-plans/{plan_id}",
        json={"is_available": True},
    )
    assert availability.status_code == 200

    activated = await client.post(
        f"/organizations/{organization_id}/membership-plans/{plan_id}/activate"
    )
    assert activated.status_code == 200

    purchase = await client.post(
        f"/gyms/{gym_one}/members/{member_id}/subscriptions",
        json={
            "member_id": member_id,
            "membership_plan_id": plan_id,
            "start_date": date.today().isoformat(),
        },
    )
    assert purchase.status_code == 422
    assert "purchasing gym" in purchase.json()["detail"]


@pytest.mark.asyncio
async def test_member_can_be_assigned_to_multiple_gyms(
    client,
    create_gym,
    organization_id,
):
    gym_one = (await create_gym("Member Home Gym")).json()["data"]["id"]
    gym_two = (await create_gym("Member Second Gym")).json()["data"]["id"]
    member_response = await client.post(
        f"/gyms/{gym_one}/members/",
        json={"name": "Multi Gym Member", "age": 26},
    )
    member_id = member_response.json()["data"]["id"]

    assignment_response = await client.post(
        f"/organizations/{organization_id}/members/{member_id}/gym-assignments",
        json={"gym_id": gym_two, "is_primary": True},
    )
    assert assignment_response.status_code == 201

    list_response = await client.get(
        f"/organizations/{organization_id}/members/{member_id}/gym-assignments"
    )
    assert list_response.status_code == 200
    assignments = list_response.json()["data"]
    assert len(assignments) == 2
    assert {item["gym_id"] for item in assignments} == {gym_one, gym_two}
    assert [item["gym_id"] for item in assignments if item["is_primary"]] == [gym_two]

    remove_response = await client.delete(
        f"/organizations/{organization_id}/members/{member_id}/gym-assignments/{gym_one}"
    )
    assert remove_response.status_code == 200
