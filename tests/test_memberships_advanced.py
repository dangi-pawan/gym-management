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


@pytest.mark.asyncio
async def test_refund_webhook_recovers_missing_provider_id_and_deduplicates(
    client, create_gym, organization_id, db_connection, monkeypatch,
):
    import json

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.features.memberships.advanced_service as membership_service
    from app.core.config import settings
    from app.features.memberships.models import Payment, PaymentRefund

    gym_id = (await create_gym("Refund Recovery Gym")).json()["data"]["id"]
    member = await client.post(
        f"/gyms/{gym_id}/members/",
        json={"name": "Refund Recovery Member", "age": 28},
    )
    member_id = member.json()["data"]["id"]

    plan = await client.post(
        f"/organizations/{organization_id}/membership-plans",
        json={
            "name": "Refund Enabled Plan",
            "duration_value": 1,
            "duration_unit": "month",
            "base_price": "100.00",
            "access_type": "home_gym",
            "rules": {"refund_allowed": True, "transfer_allowed": False},
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
    subscription = await client.post(
        f"/gyms/{gym_id}/members/{member_id}/subscriptions",
        json={
            "member_id": member_id,
            "membership_plan_id": plan_id,
            "start_date": date.today().isoformat(),
        },
    )
    subscription_id = subscription.json()["data"]["id"]

    async def fake_create_order(**kwargs):
        return {"id": "order_refund_recovery"}

    monkeypatch.setattr(membership_service, "razorpay_create_order", fake_create_order)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_key")
    order = await client.post(
        f"/gyms/{gym_id}/subscriptions/{subscription_id}/payments/razorpay-order"
    )
    assert order.status_code == 200
    payment_id = order.json()["data"]["payment_id"]

    Session = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    async with Session() as session:
        payment = await session.scalar(
            select(Payment).where(Payment.id == payment_id)
        )
        payment.status = "succeeded"
        payment.provider_payment_id = "pay_refund_recovery"
        await session.commit()

    async def uncertain_refund(*args, **kwargs):
        raise membership_service.RazorpayError("simulated provider timeout")

    monkeypatch.setattr(membership_service, "razorpay_create_refund", uncertain_refund)
    response = await client.post(
        f"/gyms/{gym_id}/payments/{payment_id}/refunds",
        json={"amount": "50.00", "reason": "Test refund"},
    )
    assert response.status_code == 502

    async with Session() as session:
        refund = await session.scalar(
            select(PaymentRefund).where(PaymentRefund.payment_id == payment_id)
        )
        refund_id = refund.id
        assert refund.status == "pending"
        assert refund.provider_refund_id is None
        assert len(refund.idempotency_key) == 36

    monkeypatch.setattr(membership_service, "verify_webhook_signature", lambda *_: True)
    event_payload = {
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": "rfnd_refund_recovery",
                    "payment_id": "pay_refund_recovery",
                    "amount": 5000,
                    "currency": "INR",
                    "status": "processed",
                    "notes": {"internal_refund_id": str(refund_id)},
                }
            }
        },
    }
    headers = {
        "X-Razorpay-Signature": "test-signature",
        "X-Razorpay-Event-Id": "evt_refund_recovery",
    }

    # A mismatched amount must not consume the event ID or update the refund.
    invalid_payload = json.loads(json.dumps(event_payload))
    invalid_payload["payload"]["refund"]["entity"]["amount"] = 4000
    invalid = await client.post(
        "/payments/razorpay/webhook",
        content=json.dumps(invalid_payload),
        headers=headers,
    )
    assert invalid.status_code == 400

    processed = await client.post(
        "/payments/razorpay/webhook",
        content=json.dumps(event_payload),
        headers=headers,
    )
    assert processed.status_code == 200
    assert processed.json()["data"]["refund_status"] == "processed"

    duplicate = await client.post(
        "/payments/razorpay/webhook",
        content=json.dumps(event_payload),
        headers=headers,
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["data"]["duplicate"] is True

    # A delayed failure event must not downgrade a refund already processed.
    failed_payload = json.loads(json.dumps(event_payload))
    failed_payload["event"] = "refund.failed"
    failed_headers = {
        "X-Razorpay-Signature": "test-signature",
        "X-Razorpay-Event-Id": "evt_refund_late_failure",
    }
    late_failure = await client.post(
        "/payments/razorpay/webhook",
        content=json.dumps(failed_payload),
        headers=failed_headers,
    )
    assert late_failure.status_code == 200
    assert late_failure.json()["data"]["refund_status"] == "processed"

    async with Session() as session:
        refund = await session.get(PaymentRefund, refund_id)
        payment = await session.get(Payment, payment_id)
        assert refund.status == "processed"
        assert refund.provider_refund_id == "rfnd_refund_recovery"
        assert payment.status == "partially_refunded"

    # A second ambiguous refund can be reconciled by retrying the same
    # persisted operation, not by creating a new provider refund.
    monkeypatch.setattr(membership_service, "razorpay_create_refund", uncertain_refund)
    second = await client.post(
        f"/gyms/{gym_id}/payments/{payment_id}/refunds",
        json={"amount": "25.00", "reason": "Retry test"},
    )
    assert second.status_code == 502
    async with Session() as session:
        second_refund = await session.scalar(
            select(PaymentRefund)
            .where(PaymentRefund.payment_id == payment_id)
            .order_by(PaymentRefund.id.desc())
        )
        second_refund_id = second_refund.id
        persisted_key = second_refund.idempotency_key

    retry_call = {}

    async def accepted_refund(provider_payment_id, amount_paise, notes, idempotency_key):
        retry_call.update(
            payment_id=provider_payment_id,
            amount_paise=amount_paise,
            notes=notes,
            idempotency_key=idempotency_key,
        )
        return {"id": "rfnd_retry_recovered", "status": "pending"}

    monkeypatch.setattr(membership_service, "razorpay_create_refund", accepted_refund)
    retried = await client.post(
        f"/gyms/{gym_id}/refunds/{second_refund_id}/retry"
    )
    assert retried.status_code == 200
    assert retry_call["idempotency_key"] == persisted_key
    assert retry_call["amount_paise"] == 2500
    assert retried.json()["data"]["provider_refund_id"] == "rfnd_retry_recovered"


def test_razorpay_refund_request_sends_stable_idempotency_header(monkeypatch):
    import asyncio

    from app.features.memberships import razorpay

    captured = {}

    async def fake_request(method, path, payload=None, extra_headers=None):
        captured.update(
            method=method,
            path=path,
            payload=payload,
            headers=extra_headers,
        )
        return {"id": "rfnd_idempotent", "status": "pending"}

    monkeypatch.setattr(razorpay, "_request", fake_request)
    result = asyncio.run(
        razorpay.create_refund(
            "pay_idempotent",
            2500,
            {"internal_refund_id": "42"},
            "12345678-1234-5678-1234-567812345678",
        )
    )
    assert result["id"] == "rfnd_idempotent"
    assert captured["headers"]["X-Refund-Idempotency"] == (
        "12345678-1234-5678-1234-567812345678"
    )
