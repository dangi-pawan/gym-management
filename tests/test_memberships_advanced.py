from datetime import date, timedelta

import pytest


@pytest.mark.asyncio
async def test_gst_is_snapshotted_when_subscription_is_created(
    client, create_gym, organization_id,
):
    gym_id = (await create_gym("GST Snapshot Gym")).json()["data"]["id"]
    member = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "GST Member", "age": 29},
    )
    member_id = member.json()["data"]["id"]

    tax = await client.put(
        f"/organizations/{organization_id}/membership-tax-settings",
        json={"gst_rate": "18.00", "tax_mode": "intra_state"},
    )
    assert tax.status_code == 200

    plan = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "GST Test Plan",
            "duration_value": 1,
            "duration_unit": "month",
            "base_price": "1000.00",
            "access_type": "home_gym",
        },
    )
    plan_id = plan.json()["data"]["id"]
    await client.put(
        f"/gyms/{gym_id}/membership-plans/{plan_id}",
        json={"is_available": True},
    )
    await client.post(
        f"/organizations/{organization_id}/membership-plans/{plan_id}/activate"
    )

    created = await client.post(
        f"/gyms/{gym_id}/members/{member_id}/subscriptions",
        json={
            "member_id": member_id,
            "membership_plan_id": plan_id,
            "start_date": date.today().isoformat(),
        },
    )
    assert created.status_code == 201
    subscription_id = created.json()["data"]["id"]

    # Changing the organization's tax settings must not alter an existing quote.
    await client.put(
        f"/organizations/{organization_id}/membership-tax-settings",
        json={"gst_rate": "5.00", "tax_mode": "inter_state"},
    )
    payment = await client.post(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/payments/manual",
        json={"payment_method": "upi", "provider_reference": "GST-SNAPSHOT-01"},
    )
    assert payment.status_code == 200
    assert payment.json()["data"]["amount"] == "1180.00"

    invoice = await client.get(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/invoice"
    )
    assert invoice.status_code == 200
    assert invoice.json()["data"]["tax_amount"] == "180.00"
    assert invoice.json()["data"]["total_amount"] == "1180.00"


@pytest.mark.asyncio
async def test_freeze_blocks_access_and_extends_subscription(
    client, create_gym, organization_id,
):
    gym_id = (await create_gym("Freeze Test Gym")).json()["data"]["id"]
    member = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Freeze Member", "age": 31},
    )
    member_id = member.json()["data"]["id"]

    plan = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "Freeze Enabled Plan",
            "duration_value": 30,
            "duration_unit": "day",
            "base_price": "500.00",
            "access_type": "home_gym",
            "rules": {
                "freeze_allowed": True,
                "max_freeze_days": 7,
                "transfer_allowed": False,
            },
        },
    )
    plan_id = plan.json()["data"]["id"]
    await client.put(
        f"/gyms/{gym_id}/membership-plans/{plan_id}",
        json={"is_available": True},
    )
    await client.post(
        f"/organizations/{organization_id}/membership-plans/{plan_id}/activate"
    )
    created = await client.post(
        f"/gyms/{gym_id}/members/{member_id}/subscriptions",
        json={
            "member_id": member_id,
            "membership_plan_id": plan_id,
            "start_date": date.today().isoformat(),
        },
    )
    subscription_id = created.json()["data"]["id"]
    payment = await client.post(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/payments/manual",
        json={"payment_method": "cash"},
    )
    assert payment.status_code == 200

    freeze = await client.post(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/freeze",
        json={
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=3)).isoformat(),
            "reason": "Member travel",
        },
    )
    assert freeze.status_code == 201
    assert freeze.json()["data"]["days"] == 3

    access = await client.get(
        f"/gyms/{gym_id}/members/{member_id}/membership-access"
    )
    assert access.status_code == 200
    assert access.json()["data"]["has_access"] is False


@pytest.mark.asyncio
async def test_membership_transfer_between_people_is_rejected(
    client, create_gym, organization_id,
):
    await create_gym("No Transfer Gym")
    response = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "No Transfer Plan",
            "duration_value": 1,
            "duration_unit": "month",
            "base_price": "100.00",
            "access_type": "home_gym",
            "rules": {"transfer_allowed": True},
        },
    )
    assert response.status_code == 422



@pytest.mark.asyncio
async def test_auto_renew_is_rejected_until_recurring_mandates_are_supported(
    client, create_gym, organization_id,
):
    await create_gym("No Auto Renew Gym")
    response = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "No Auto Renew Plan",
            "duration_value": 1,
            "duration_unit": "month",
            "base_price": "100.00",
            "access_type": "home_gym",
            "rules": {"auto_renew_allowed": True},
        },
    )
    assert response.status_code == 422



def test_gst_calculation_splits_intra_state_and_inter_state_tax():
    from decimal import Decimal

    from app.features.memberships.advanced_service import calculate_tax_snapshot

    intra = calculate_tax_snapshot(
        Decimal("1000.00"), Decimal("18.00"), "intra_state", "GSTIN",
    )
    assert intra["cgst_amount"] == Decimal("90.00")
    assert intra["sgst_amount"] == Decimal("90.00")
    assert intra["igst_amount"] == Decimal("0.00")
    assert intra["total_amount"] == Decimal("1180.00")

    inter = calculate_tax_snapshot(
        Decimal("1000.00"), Decimal("18.00"), "inter_state", "GSTIN",
    )
    assert inter["cgst_amount"] == Decimal("0.00")
    assert inter["sgst_amount"] == Decimal("0.00")
    assert inter["igst_amount"] == Decimal("180.00")


def test_razorpay_webhook_signature_uses_constant_time_hmac(monkeypatch):
    import hashlib
    import hmac

    from app.core.config import settings
    from app.features.memberships.razorpay import verify_webhook_signature

    secret = "test-webhook-secret"
    body = b'{"event":"payment.captured"}'
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", secret)
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(body, signature) is True
    assert verify_webhook_signature(body, "invalid") is False
