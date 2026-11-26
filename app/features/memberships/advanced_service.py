"""Advanced membership workflows: online payment, GST, freezes and refunds."""
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.members.models import Member
from app.features.memberships.models import (
    Invoice, MemberSubscription, MembershipTaxSettings, Payment,
    PaymentRefund, PaymentWebhookEvent, SubscriptionFreeze,
)
from app.features.memberships.razorpay import (
    create_order as razorpay_create_order,
    create_refund as razorpay_create_refund,
    verify_webhook_signature,
    RazorpayConfigurationError, RazorpayError,
)
from app.features.memberships.documents import create_private_pdf_document, delete_private_document
from app.features.users.models import User
from app.core.config import settings


def _error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


async def calculate_tax(db: AsyncSession, organization_id: int, subtotal: Decimal) -> dict:
    settings_result = await db.execute(
        select(MembershipTaxSettings).where(
            MembershipTaxSettings.organization_id == organization_id
        )
    )
    tax_settings = settings_result.scalar_one_or_none()
    rate = tax_settings.gst_rate if tax_settings else settings.MEMBERSHIP_DEFAULT_GST_RATE
    mode = tax_settings.tax_mode if tax_settings else "intra_state"
    gstin = tax_settings.gstin if tax_settings else None
    return calculate_tax_snapshot(subtotal, rate, mode, gstin)


def calculate_tax_snapshot(subtotal: Decimal, rate: Decimal, mode: str, gstin: str | None) -> dict:
    tax = (subtotal * rate / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    zero = Decimal("0.00")
    cgst = (tax / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if mode == "intra_state" else zero
    sgst = tax - cgst if mode == "intra_state" else zero
    igst = tax if mode == "inter_state" else zero
    return {
        "gst_rate": rate,
        "tax_mode": mode,
        "gstin": gstin,
        "tax_amount": tax,
        "cgst_amount": cgst,
        "sgst_amount": sgst,
        "igst_amount": igst,
        "total_amount": subtotal + tax,
    }


async def update_tax_settings(
    db: AsyncSession, organization_id: int, gst_rate: Decimal,
    gstin: str | None, tax_mode: str,
) -> MembershipTaxSettings:
    result = await db.execute(
        select(MembershipTaxSettings).where(
            MembershipTaxSettings.organization_id == organization_id
        )
    )
    record = result.scalar_one_or_none()
    if record is None:
        record = MembershipTaxSettings(
            organization_id=organization_id, gst_rate=gst_rate,
            gstin=gstin, tax_mode=tax_mode,
        )
        db.add(record)
    else:
        record.gst_rate = gst_rate
        record.gstin = gstin
        record.tax_mode = tax_mode
    await db.commit()
    await db.refresh(record)
    return record


async def create_razorpay_order(
    db: AsyncSession, organization_id: int, gym_id: int,
    subscription_id: int, user: User,
) -> dict:
    result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.id == subscription_id,
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.purchased_at_gym_id == gym_id,
        ).with_for_update()
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise _error(404, "Subscription not found")
    if subscription.status != "pending_payment":
        raise _error(409, "Only pending-payment subscriptions can create a payment order")

    existing = await db.scalar(
        select(Payment).where(
            Payment.subscription_id == subscription.id,
            Payment.provider == "razorpay",
            Payment.status == "pending",
        )
    )
    if existing and existing.provider_order_id:
        return {
            "payment_id": existing.id,
            "order_id": existing.provider_order_id,
            "amount": existing.amount,
            "currency": existing.currency,
            "key_id": settings.RAZORPAY_KEY_ID,
        }

    subtotal = subscription.plan_price_snapshot + subscription.joining_fee_snapshot
    tax = calculate_tax_snapshot(
        subtotal, subscription.gst_rate_snapshot, subscription.tax_mode_snapshot,
        subscription.gstin_snapshot,
    )
    amount = tax["total_amount"]
    if amount <= 0:
        raise _error(409, "No payment is due for this subscription")
    try:
        order = await razorpay_create_order(
            amount_paise=int((amount * 100).to_integral_exact()),
            currency=subscription.currency_snapshot,
            receipt=f"membership-{subscription.id}",
            notes={"organization_id": str(organization_id), "subscription_id": str(subscription.id)},
        )
    except RazorpayConfigurationError:
        raise _error(503, "Razorpay is not configured") from None
    except RazorpayError:
        raise _error(502, "Razorpay could not create the payment order") from None
    payment = Payment(
        organization_id=organization_id,
        subscription_id=subscription.id,
        amount=amount,
        currency=subscription.currency_snapshot,
        payment_method="online",
        provider="razorpay",
        provider_order_id=order["id"],
        status="pending",
        recorded_by=user.id,
    )
    db.add(payment)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise _error(409, "A payment order already exists for this subscription") from None
    await db.refresh(payment)
    from app.core.config import settings
    return {
        "payment_id": payment.id,
        "order_id": order["id"],
        "amount": payment.amount,
        "currency": payment.currency,
        "key_id": settings.RAZORPAY_KEY_ID,
    }


async def handle_razorpay_webhook(
    db: AsyncSession, raw_body: bytes, signature: str, event_id: str,
) -> dict:
    try:
        signature_valid = verify_webhook_signature(raw_body, signature)
    except RazorpayConfigurationError:
        raise _error(503, "Razorpay webhook verification is not configured") from None
    if not signature_valid:
        raise _error(400, "Invalid Razorpay webhook signature")
    try:
        payload = json.loads(raw_body)
        event_type = payload.get("event")
        if event_type not in {"payment.captured", "payment.failed"}:
            return {"received": True, "ignored": True}
        entity = payload["payload"]["payment"]["entity"]
        order_id = entity["order_id"]
        provider_payment_id = entity["id"]
        amount_paise = int(entity["amount"])
    except (ValueError, KeyError, TypeError):
        raise _error(400, "Invalid Razorpay payment webhook payload") from None

    duplicate = await db.scalar(
        select(PaymentWebhookEvent.id).where(
            PaymentWebhookEvent.provider == "razorpay",
            PaymentWebhookEvent.event_id == event_id,
        )
    )
    if duplicate:
        return {"received": True, "duplicate": True}

    result = await db.execute(
        select(Payment).where(
            Payment.provider == "razorpay",
            Payment.provider_order_id == order_id,
        ).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise _error(404, "Payment order not found")
    if payment.status == "succeeded":
        db.add(PaymentWebhookEvent(provider="razorpay", event_id=event_id))
        await db.commit()
        return {"received": True, "duplicate": True}
    if payload.get("event") == "payment.failed":
        payment.status = "failed"
        db.add(PaymentWebhookEvent(provider="razorpay", event_id=event_id))
        await db.commit()
        return {"received": True, "failed": True}
    expected_paise = int((payment.amount * 100).to_integral_exact())
    if amount_paise != expected_paise:
        raise _error(400, "Razorpay payment amount does not match the server-side order")

    subscription_result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.id == payment.subscription_id,
            MemberSubscription.organization_id == payment.organization_id,
        )
    )
    subscription = subscription_result.scalar_one_or_none()
    if subscription is None or subscription.status != "pending_payment":
        raise _error(409, "Subscription is not awaiting payment")

    member = await db.get(Member, subscription.member_id)
    now = datetime.now(timezone.utc)
    payment.provider_payment_id = provider_payment_id
    payment.provider_reference = provider_payment_id
    payment.status = "succeeded"
    payment.paid_at = now
    subscription.status = "active"
    subscription.activated_at = now
    db.add(PaymentWebhookEvent(provider="razorpay", event_id=event_id))

    from app.features.memberships.service import _create_invoice
    generated = []
    try:
        await db.flush()
        invoice = await _create_invoice(db, subscription)
        await db.flush()
        generated.append(await create_private_pdf_document(
            db, subscription.organization_id, subscription.id, "invoice",
            "Membership Invoice",
            [
                f"Invoice: {invoice.invoice_number}",
                f"Member: {member.name if member else subscription.member_id}",
                f"Subtotal: {invoice.subtotal} {invoice.currency}",
                f"GST: {invoice.tax_amount} {invoice.currency}",
                f"Total: {invoice.total_amount} {invoice.currency}",
            ],
            {"invoice_id": invoice.id},
        ))
        generated.append(await create_private_pdf_document(
            db, subscription.organization_id, subscription.id, "receipt",
            "Razorpay Payment Receipt",
            [
                f"Subscription: {subscription.id}",
                f"Payment ID: {payment.id}",
                f"Razorpay payment: {provider_payment_id}",
                f"Amount received: {payment.amount} {payment.currency}",
                f"Paid at: {now.isoformat()}",
            ],
            {"payment_id": payment.id, "provider": "razorpay"},
        ))
        await db.commit()
    except Exception:
        await db.rollback()
        for document in generated:
            delete_private_document(document.storage_key)
        raise
    return {"received": True, "duplicate": False}


async def freeze_subscription(
    db: AsyncSession, organization_id: int, gym_id: int,
    subscription_id: int, user: User,
    start_date, end_date, reason: str | None,
) -> SubscriptionFreeze:
    result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.id == subscription_id,
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.purchased_at_gym_id == gym_id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise _error(404, "Subscription not found")
    if subscription.status != "active":
        raise _error(409, "Only active subscriptions can be frozen")
    rules = subscription.rules_snapshot or {}
    if not rules.get("freeze_allowed"):
        raise _error(403, "Freezing is not allowed by this membership plan")
    days = (end_date - start_date).days
    if start_date < subscription.start_date or end_date > subscription.end_date:
        raise _error(422, "Freeze dates must fall within the current subscription period")
    if days <= 0:
        raise _error(422, "Freeze period must contain at least one day")
    maximum = rules.get("max_freeze_days")
    used = await db.scalar(
        select(func.coalesce(func.sum(SubscriptionFreeze.days), 0)).where(
            SubscriptionFreeze.organization_id == organization_id,
            SubscriptionFreeze.subscription_id == subscription_id,
            SubscriptionFreeze.status == "applied",
        )
    )
    if maximum is not None and int(used or 0) + days > int(maximum):
        raise _error(422, "Freeze period exceeds the plan's remaining freeze allowance")
    overlap = await db.scalar(
        select(SubscriptionFreeze.id).where(
            SubscriptionFreeze.organization_id == organization_id,
            SubscriptionFreeze.subscription_id == subscription_id,
            SubscriptionFreeze.status == "applied",
            SubscriptionFreeze.start_date < end_date,
            SubscriptionFreeze.end_date > start_date,
        )
    )
    if overlap:
        raise _error(409, "Freeze period overlaps an existing freeze")
    freeze = SubscriptionFreeze(
        organization_id=organization_id,
        subscription_id=subscription_id,
        start_date=start_date,
        end_date=end_date,
        days=days,
        reason=reason,
        created_by=user.id,
    )
    subscription.end_date = subscription.end_date.fromordinal(subscription.end_date.toordinal() + days)
    db.add(freeze)
    await db.commit()
    await db.refresh(freeze)
    return freeze


async def refund_payment(
    db: AsyncSession, organization_id: int, gym_id: int,
    payment_id: int, user: User, amount: Decimal, reason: str | None,
) -> PaymentRefund:
    result = await db.execute(
        select(Payment)
        .join(MemberSubscription, MemberSubscription.id == Payment.subscription_id)
        .where(
            Payment.id == payment_id,
            Payment.organization_id == organization_id,
            MemberSubscription.purchased_at_gym_id == gym_id,
        ).with_for_update()
    )
    payment = result.scalar_one_or_none()
    if payment is None:
        raise _error(404, "Payment not found")
    if payment.provider != "razorpay" or payment.status not in {"succeeded", "partially_refunded"} or not payment.provider_payment_id:
        raise _error(409, "Only successfully captured Razorpay payments can be refunded automatically")
    linked_subscription = await db.get(MemberSubscription, payment.subscription_id)
    if linked_subscription is None or not (linked_subscription.rules_snapshot or {}).get("refund_allowed", False):
        raise _error(403, "Refunds are not allowed by this membership plan")
    refunded = await db.scalar(
        select(func.coalesce(func.sum(PaymentRefund.amount), 0)).where(
            PaymentRefund.organization_id == organization_id,
            PaymentRefund.payment_id == payment_id,
            PaymentRefund.status.in_(["pending", "processed"]),
        )
    )
    remaining = payment.amount - Decimal(refunded or 0)
    if amount > remaining:
        raise _error(422, "Refund amount exceeds the remaining refundable amount")
    refund = PaymentRefund(
        organization_id=organization_id,
        payment_id=payment_id,
        amount=amount,
        provider="razorpay",
        status="pending",
        reason=reason,
        recorded_by=user.id,
    )
    db.add(refund)
    await db.commit()
    await db.refresh(refund)
    try:
        provider_result = await razorpay_create_refund(
            payment.provider_payment_id,
            int((amount * 100).to_integral_exact()),
            {"internal_refund_id": str(refund.id), "reason": (reason or "Membership refund")[:200]},
        )
    except Exception as exc:
        refund.status = "failed"
        await db.commit()
        if isinstance(exc, RazorpayConfigurationError):
            raise _error(503, "Razorpay is not configured") from None
        if isinstance(exc, RazorpayError):
            raise _error(502, "Razorpay could not process the refund") from None
        raise
    refund.provider_refund_id = provider_result["id"]
    refund.status = "processed"
    refund.processed_at = datetime.now(timezone.utc)
    total_refunded = Decimal(refunded or 0) + amount
    payment.status = "refunded" if total_refunded >= payment.amount else "partially_refunded"
    await db.commit()
    await db.refresh(refund)
    return refund
