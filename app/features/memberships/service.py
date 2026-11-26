import calendar
import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.gyms.models import Gym
from app.features.members.models import Member
from app.features.memberships.models import (
    GymMembershipPlan,
    Invoice,
    MemberGymAssignment,
    MemberSubscription,
    MembershipPlan,
    MembershipPlanAccessGym,
    MembershipPlanRules,
    MembershipTerms,
    MembershipDocument,
    Payment,
    SubscriptionAccessGym,
    SubscriptionTermsAcceptance,
    SubscriptionFreeze,
)
from app.features.memberships.documents import create_private_pdf_document, delete_private_document
from app.features.memberships.advanced_service import calculate_tax
from app.features.memberships.schemas import (
    GymMembershipPlanUpdate,
    ManualPaymentCreate,
    MembershipPlanCreate,
    MembershipPlanUpdate,
    MembershipTermsCreate,
    SubscriptionCreate,
)
from app.features.users.models import User


def _http_error(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def _add_duration(start: date, value: int, unit: str) -> date:
    if unit == "day":
        from datetime import timedelta
        return start + timedelta(days=value)
    if unit == "week":
        from datetime import timedelta
        return start + timedelta(weeks=value)
    months = value if unit == "month" else value * 12
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


async def _validate_terms(
    db: AsyncSession,
    organization_id: int,
    terms_id: int | None,
) -> MembershipTerms | None:
    if terms_id is None:
        return None
    result = await db.execute(
        select(MembershipTerms).where(
            MembershipTerms.id == terms_id,
            MembershipTerms.organization_id == organization_id,
            MembershipTerms.status == "published",
        )
    )
    terms = result.scalar_one_or_none()
    if terms is None:
        raise _http_error(422, "Published membership terms not found in this organization")
    return terms


async def _validate_gym_ids(
    db: AsyncSession,
    organization_id: int,
    gym_ids: list[int],
) -> None:
    if not gym_ids:
        return
    result = await db.execute(
        select(Gym.id).where(
            Gym.organization_id == organization_id,
            Gym.id.in_(gym_ids),
        )
    )
    found = set(result.scalars().all())
    if found != set(gym_ids):
        raise _http_error(422, "One or more gyms do not belong to this organization")


async def _plan_payload(db: AsyncSession, plan: MembershipPlan) -> dict:
    gym_result = await db.execute(
        select(MembershipPlanAccessGym.gym_id).where(
            MembershipPlanAccessGym.membership_plan_id == plan.id,
            MembershipPlanAccessGym.organization_id == plan.organization_id,
        ).order_by(MembershipPlanAccessGym.gym_id)
    )
    rules_result = await db.execute(
        select(MembershipPlanRules).where(
            MembershipPlanRules.membership_plan_id == plan.id
        )
    )
    rules = rules_result.scalar_one_or_none()
    if rules is None:
        rules_data = {
            "freeze_allowed": False,
            "max_freeze_days": None,
            "transfer_allowed": False,
            "cancellation_allowed": True,
            "refund_allowed": False,
            "auto_renew_allowed": False,
        }
    else:
        rules_data = {
            "freeze_allowed": rules.freeze_allowed,
            "max_freeze_days": rules.max_freeze_days,
            "transfer_allowed": rules.transfer_allowed,
            "cancellation_allowed": rules.cancellation_allowed,
            "refund_allowed": rules.refund_allowed,
            "auto_renew_allowed": rules.auto_renew_allowed,
        }
    return {
        "id": plan.id,
        "organization_id": plan.organization_id,
        "name": plan.name,
        "description": plan.description,
        "duration_value": plan.duration_value,
        "duration_unit": plan.duration_unit,
        "base_price": plan.base_price,
        "joining_fee": plan.joining_fee,
        "currency": plan.currency,
        "access_type": plan.access_type,
        "terms_id": plan.terms_id,
        "status": plan.status,
        "selected_gym_ids": list(gym_result.scalars().all()),
        "rules": rules_data,
    }


async def create_membership_plan(
    db: AsyncSession,
    organization_id: int,
    user: User,
    data: MembershipPlanCreate,
) -> dict:
    await _validate_terms(db, organization_id, data.terms_id)
    if data.access_type == "selected_gyms":
        await _validate_gym_ids(db, organization_id, data.selected_gym_ids)
    elif data.selected_gym_ids:
        raise _http_error(422, "selected_gym_ids is only valid for selected_gyms access")

    plan = MembershipPlan(
        organization_id=organization_id,
        name=data.name,
        description=data.description,
        duration_value=data.duration_value,
        duration_unit=data.duration_unit,
        base_price=data.base_price,
        joining_fee=data.joining_fee,
        currency=data.currency,
        access_type=data.access_type,
        terms_id=data.terms_id,
        status="draft",
        created_by=user.id,
    )
    db.add(plan)
    await db.flush()
    db.add(
        MembershipPlanRules(
            membership_plan_id=plan.id,
            **data.rules.model_dump(),
        )
    )
    for gym_id in data.selected_gym_ids:
        db.add(
            MembershipPlanAccessGym(
                organization_id=organization_id,
                membership_plan_id=plan.id,
                gym_id=gym_id,
            )
        )
    await db.commit()
    await db.refresh(plan)
    return await _plan_payload(db, plan)


async def list_membership_plans(
    db: AsyncSession,
    organization_id: int,
) -> list[dict]:
    result = await db.execute(
        select(MembershipPlan)
        .where(MembershipPlan.organization_id == organization_id)
        .order_by(MembershipPlan.id.desc())
    )
    return [await _plan_payload(db, plan) for plan in result.scalars().all()]


async def get_membership_plan(
    db: AsyncSession,
    organization_id: int,
    plan_id: int,
) -> dict | None:
    result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == plan_id,
            MembershipPlan.organization_id == organization_id,
        )
    )
    plan = result.scalar_one_or_none()
    return None if plan is None else await _plan_payload(db, plan)


async def update_membership_plan(
    db: AsyncSession,
    organization_id: int,
    plan_id: int,
    data: MembershipPlanUpdate,
) -> dict | None:
    result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == plan_id,
            MembershipPlan.organization_id == organization_id,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return None
    if plan.status == "archived":
        raise _http_error(409, "Archived plans cannot be updated")

    changes = data.model_dump(exclude_unset=True)
    selected_gym_ids = changes.pop("selected_gym_ids", None)
    rules_data = changes.pop("rules", None)
    if "terms_id" in changes:
        await _validate_terms(db, organization_id, changes["terms_id"])

    new_access_type = changes.get("access_type", plan.access_type)
    if selected_gym_ids is not None:
        if new_access_type != "selected_gyms":
            raise _http_error(422, "selected_gym_ids is only valid for selected_gyms access")
        await _validate_gym_ids(db, organization_id, selected_gym_ids)
        await db.execute(
            MembershipPlanAccessGym.__table__.delete().where(
                MembershipPlanAccessGym.membership_plan_id == plan.id
            )
        )
        for gym_id in selected_gym_ids:
            db.add(MembershipPlanAccessGym(
                organization_id=organization_id,
                membership_plan_id=plan.id,
                gym_id=gym_id,
            ))
    elif new_access_type == "selected_gyms" and plan.access_type != "selected_gyms":
        raise _http_error(422, "Provide selected_gym_ids when changing access_type to selected_gyms")
    for key, value in changes.items():
        setattr(plan, key, value)

    if rules_data is not None:
        rules_result = await db.execute(
            select(MembershipPlanRules).where(
                MembershipPlanRules.membership_plan_id == plan.id
            )
        )
        rules = rules_result.scalar_one_or_none()
        if rules is None:
            db.add(MembershipPlanRules(
                membership_plan_id=plan.id,
                **rules_data.model_dump(),
            ))
        else:
            for key, value in rules_data.model_dump().items():
                setattr(rules, key, value)

    await db.commit()
    await db.refresh(plan)
    return await _plan_payload(db, plan)


async def activate_membership_plan(
    db: AsyncSession,
    organization_id: int,
    plan_id: int,
) -> dict | None:
    result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == plan_id,
            MembershipPlan.organization_id == organization_id,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return None
    if plan.status == "archived":
        raise _http_error(409, "Archived plans cannot be activated")
    if plan.access_type == "selected_gyms":
        count = await db.scalar(
            select(func.count()).select_from(MembershipPlanAccessGym).where(
                MembershipPlanAccessGym.membership_plan_id == plan.id
            )
        )
        if not count:
            raise _http_error(422, "Configure at least one eligible gym before activation")
    if plan.terms_id is not None:
        await _validate_terms(db, organization_id, plan.terms_id)
    plan.status = "active"
    await db.commit()
    await db.refresh(plan)
    return await _plan_payload(db, plan)


async def archive_membership_plan(
    db: AsyncSession,
    organization_id: int,
    plan_id: int,
) -> bool:
    result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == plan_id,
            MembershipPlan.organization_id == organization_id,
        )
    )
    plan = result.scalar_one_or_none()
    if plan is None:
        return False
    plan.status = "archived"
    await db.commit()
    return True


async def set_gym_membership_plan(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    plan_id: int,
    data: GymMembershipPlanUpdate,
) -> dict:
    gym_result = await db.execute(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.organization_id == organization_id,
        )
    )
    if gym_result.scalar_one_or_none() is None:
        raise _http_error(404, "Gym not found")
    plan_result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == plan_id,
            MembershipPlan.organization_id == organization_id,
        )
    )
    if plan_result.scalar_one_or_none() is None:
        raise _http_error(404, "Membership plan not found")
    result = await db.execute(
        select(GymMembershipPlan).where(
            GymMembershipPlan.gym_id == gym_id,
            GymMembershipPlan.membership_plan_id == plan_id,
            GymMembershipPlan.organization_id == organization_id,
        )
    )
    association = result.scalar_one_or_none()
    if association is None:
        association = GymMembershipPlan(
            organization_id=organization_id,
            gym_id=gym_id,
            membership_plan_id=plan_id,
        )
        db.add(association)
    association.is_available = data.is_available
    association.price_override = data.price_override
    association.joining_fee_override = data.joining_fee_override
    await db.commit()
    return {
        "gym_id": gym_id,
        "membership_plan_id": plan_id,
        "is_available": association.is_available,
        "price_override": association.price_override,
        "joining_fee_override": association.joining_fee_override,
    }


async def list_gym_membership_plans(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
) -> list[dict]:
    result = await db.execute(
        select(MembershipPlan, GymMembershipPlan)
        .join(
            GymMembershipPlan,
            GymMembershipPlan.membership_plan_id == MembershipPlan.id,
        )
        .where(
            GymMembershipPlan.organization_id == organization_id,
            GymMembershipPlan.gym_id == gym_id,
            GymMembershipPlan.is_available.is_(True),
            MembershipPlan.organization_id == organization_id,
            MembershipPlan.status == "active",
        )
        .order_by(MembershipPlan.name)
    )
    payloads = []
    for plan, availability in result.all():
        payload = await _plan_payload(db, plan)
        payload["effective_price"] = availability.price_override if availability.price_override is not None else plan.base_price
        payload["effective_joining_fee"] = availability.joining_fee_override if availability.joining_fee_override is not None else plan.joining_fee
        payloads.append(payload)
    return payloads


async def create_membership_terms(
    db: AsyncSession,
    organization_id: int,
    user: User,
    data: MembershipTermsCreate,
) -> MembershipTerms:
    latest_version = await db.scalar(
        select(func.max(MembershipTerms.version)).where(
            MembershipTerms.organization_id == organization_id
        )
    )
    terms = MembershipTerms(
        organization_id=organization_id,
        version=(latest_version or 0) + 1,
        title=data.title,
        content=data.content,
        content_hash=hashlib.sha256(data.content.encode("utf-8")).hexdigest(),
        status="draft",
        created_by=user.id,
    )
    db.add(terms)
    await db.commit()
    await db.refresh(terms)
    return terms


async def list_membership_terms(
    db: AsyncSession,
    organization_id: int,
) -> list[MembershipTerms]:
    result = await db.execute(
        select(MembershipTerms)
        .where(MembershipTerms.organization_id == organization_id)
        .order_by(MembershipTerms.version.desc())
    )
    return list(result.scalars().all())


async def publish_membership_terms(
    db: AsyncSession,
    organization_id: int,
    terms_id: int,
) -> MembershipTerms | None:
    result = await db.execute(
        select(MembershipTerms).where(
            MembershipTerms.id == terms_id,
            MembershipTerms.organization_id == organization_id,
        )
    )
    terms = result.scalar_one_or_none()
    if terms is None:
        return None
    if terms.status != "draft":
        raise _http_error(409, "Only draft terms can be published")
    terms.status = "published"
    terms.effective_from = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(terms)
    return terms


async def _subscription_payload(
    db: AsyncSession,
    subscription: MemberSubscription,
) -> dict:
    result = await db.execute(
        select(SubscriptionAccessGym.gym_id).where(
            SubscriptionAccessGym.subscription_id == subscription.id,
            SubscriptionAccessGym.organization_id == subscription.organization_id,
        ).order_by(SubscriptionAccessGym.gym_id)
    )
    return {
        "id": subscription.id,
        "organization_id": subscription.organization_id,
        "member_id": subscription.member_id,
        "membership_plan_id": subscription.membership_plan_id,
        "purchased_at_gym_id": subscription.purchased_at_gym_id,
        "status": subscription.status,
        "start_date": subscription.start_date,
        "end_date": subscription.end_date,
        "plan_name_snapshot": subscription.plan_name_snapshot,
        "duration_value_snapshot": subscription.duration_value_snapshot,
        "duration_unit_snapshot": subscription.duration_unit_snapshot,
        "plan_price_snapshot": subscription.plan_price_snapshot,
        "joining_fee_snapshot": subscription.joining_fee_snapshot,
        "currency_snapshot": subscription.currency_snapshot,
        "access_type_snapshot": subscription.access_type_snapshot,
        "created_at": subscription.created_at,
        "activated_at": subscription.activated_at,
        "cancelled_at": subscription.cancelled_at,
        "access_gym_ids": list(result.scalars().all()),
    }


async def create_subscription(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    user: User,
    data: SubscriptionCreate,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    gym_result = await db.execute(
        select(Gym).where(Gym.id == gym_id, Gym.organization_id == organization_id)
    )
    gym = gym_result.scalar_one_or_none()
    if gym is None:
        raise _http_error(404, "Gym not found")

    member_result = await db.execute(
        select(Member).where(
            Member.id == data.member_id,
            Member.organization_id == organization_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise _http_error(404, "Member not found")
    assignment_result = await db.execute(
        select(MemberGymAssignment.id).where(
            MemberGymAssignment.member_id == member.id,
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.organization_id == organization_id,
            MemberGymAssignment.status == "active",
        )
    )
    if assignment_result.scalar_one_or_none() is None:
        raise _http_error(422, "Member must have an active assignment at the purchasing gym")

    plan_result = await db.execute(
        select(MembershipPlan).where(
            MembershipPlan.id == data.membership_plan_id,
            MembershipPlan.organization_id == organization_id,
            MembershipPlan.status == "active",
        )
    )
    plan = plan_result.scalar_one_or_none()
    if plan is None:
        raise _http_error(404, "Active membership plan not found")

    availability_result = await db.execute(
        select(GymMembershipPlan).where(
            GymMembershipPlan.organization_id == organization_id,
            GymMembershipPlan.gym_id == gym_id,
            GymMembershipPlan.membership_plan_id == plan.id,
            GymMembershipPlan.is_available.is_(True),
        )
    )
    availability = availability_result.scalar_one_or_none()
    if availability is None:
        raise _http_error(422, "Membership plan is not available at this gym")

    rules_result = await db.execute(
        select(MembershipPlanRules).where(
            MembershipPlanRules.membership_plan_id == plan.id
        )
    )
    rules = rules_result.scalar_one_or_none()
    rules_snapshot = {
        "freeze_allowed": bool(rules and rules.freeze_allowed),
        "max_freeze_days": rules.max_freeze_days if rules else None,
        "transfer_allowed": False,
        "cancellation_allowed": rules.cancellation_allowed if rules else True,
        "refund_allowed": bool(rules and rules.refund_allowed),
        "auto_renew_allowed": bool(rules and rules.auto_renew_allowed),
    }

    if plan.access_type == "home_gym":
        access_gym_ids = [gym_id]
    elif plan.access_type == "all_gyms":
        gyms_result = await db.execute(
            select(Gym.id).where(Gym.organization_id == organization_id).order_by(Gym.id)
        )
        access_gym_ids = list(gyms_result.scalars().all())
    else:
        access_result = await db.execute(
            select(MembershipPlanAccessGym.gym_id).where(
                MembershipPlanAccessGym.organization_id == organization_id,
                MembershipPlanAccessGym.membership_plan_id == plan.id,
            )
        )
        access_gym_ids = list(access_result.scalars().all())
        if gym_id not in access_gym_ids:
            raise _http_error(422, "Selected-gym plan must include the purchasing gym")
    if not access_gym_ids:
        raise _http_error(422, "Membership plan has no eligible gyms")

    terms = None
    if plan.terms_id is not None:
        terms = await _validate_terms(db, organization_id, plan.terms_id)
        if not data.terms_accepted:
            raise _http_error(422, "Membership terms must be accepted before purchase")

    price = availability.price_override if availability.price_override is not None else plan.base_price
    joining_fee = availability.joining_fee_override if availability.joining_fee_override is not None else plan.joining_fee
    end_date = _add_duration(data.start_date, plan.duration_value, plan.duration_unit)
    subtotal = price + joining_fee
    tax = await calculate_tax(db, organization_id, subtotal)
    total_due = tax["total_amount"]
    now = datetime.now(timezone.utc)

    subscription = MemberSubscription(
        organization_id=organization_id,
        member_id=member.id,
        membership_plan_id=plan.id,
        purchased_at_gym_id=gym_id,
        status="active" if total_due == Decimal("0.00") else "pending_payment",
        start_date=data.start_date,
        end_date=end_date,
        plan_name_snapshot=plan.name,
        duration_value_snapshot=plan.duration_value,
        duration_unit_snapshot=plan.duration_unit,
        plan_price_snapshot=price,
        joining_fee_snapshot=joining_fee,
        currency_snapshot=plan.currency,
        access_type_snapshot=plan.access_type,
        rules_snapshot=rules_snapshot,
        created_by=user.id,
        activated_at=now if total_due == Decimal("0.00") else None,
    )
    db.add(subscription)
    await db.flush()

    for access_gym_id in access_gym_ids:
        db.add(SubscriptionAccessGym(
            organization_id=organization_id,
            subscription_id=subscription.id,
            gym_id=access_gym_id,
        ))
    generated_documents = []
    if terms is not None:
        db.add(SubscriptionTermsAcceptance(
            organization_id=organization_id,
            subscription_id=subscription.id,
            membership_terms_id=terms.id,
            terms_version_snapshot=terms.version,
            terms_content_hash_snapshot=terms.content_hash,
            accepted_at=now,
            accepted_by_member_id=member.id,
            acceptance_method=data.acceptance_method,
            ip_address=ip_address,
            user_agent=user_agent,
        ))
        generated_documents.append(
            await create_private_pdf_document(
                db,
                organization_id,
                subscription.id,
                "agreement",
                "Membership Agreement",
                [
                    f"Member: {member.name}",
                    f"Plan: {plan.name}",
                    f"Start date: {data.start_date.isoformat()}",
                    f"Exclusive end date: {end_date.isoformat()}",
                    f"Accepted terms: {terms.title} (version {terms.version})",
                    "",
                    terms.content,
                ],
                {"terms_id": terms.id, "terms_version": terms.version},
            )
        )
    if total_due == Decimal("0.00"):
        invoice = await _create_invoice(db, subscription)
        await db.flush()
        generated_documents.append(
            await create_private_pdf_document(
                db,
                organization_id,
                subscription.id,
                "invoice",
                "Membership Invoice",
                [
                    f"Invoice: {invoice.invoice_number}",
                    f"Plan: {plan.name}",
                    f"Member: {member.name}",
                    f"Subtotal: {invoice.subtotal} {invoice.currency}",
                    f"Tax: {invoice.tax_amount} {invoice.currency}",
                    f"Total: {invoice.total_amount} {invoice.currency}",
                ],
                {"invoice_id": invoice.id},
            )
        )
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        for document in generated_documents:
            delete_private_document(document.storage_key)
        raise
    await db.refresh(subscription)
    return await _subscription_payload(db, subscription)


async def _create_invoice(
    db: AsyncSession,
    subscription: MemberSubscription,
) -> Invoice:
    existing = await db.execute(
        select(Invoice).where(
            Invoice.organization_id == subscription.organization_id,
            Invoice.subscription_id == subscription.id,
            Invoice.status == "issued",
        )
    )
    invoice = existing.scalar_one_or_none()
    if invoice is not None:
        return invoice
    invoice_number = f"INV-{subscription.organization_id}-{subscription.id:08d}"
    subtotal = subscription.plan_price_snapshot + subscription.joining_fee_snapshot
    tax = await calculate_tax(db, subscription.organization_id, subtotal)
    invoice = Invoice(
        organization_id=subscription.organization_id,
        subscription_id=subscription.id,
        invoice_number=invoice_number,
        subtotal=subtotal,
        tax_amount=tax["tax_amount"],
        gst_rate=tax["gst_rate"],
        cgst_amount=tax["cgst_amount"],
        sgst_amount=tax["sgst_amount"],
        igst_amount=tax["igst_amount"],
        gstin_snapshot=tax["gstin"],
        tax_mode_snapshot=tax["tax_mode"],
        total_amount=tax["total_amount"],
        currency=subscription.currency_snapshot,
        status="issued",
        issued_at=datetime.now(timezone.utc),
    )
    db.add(invoice)
    return invoice


async def record_manual_payment(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
    user: User,
    data: ManualPaymentCreate,
) -> tuple[Payment, MemberSubscription]:
    result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.id == subscription_id,
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.purchased_at_gym_id == gym_id,
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        raise _http_error(404, "Subscription not found")
    if subscription.status != "pending_payment":
        raise _http_error(409, "Only pending-payment subscriptions can receive this payment")

    subtotal = subscription.plan_price_snapshot + subscription.joining_fee_snapshot
    tax = await calculate_tax(db, organization_id, subtotal)
    amount_due = tax["total_amount"]
    if amount_due <= Decimal("0.00"):
        raise _http_error(409, "No payment is due for this subscription")

    payment = Payment(
        organization_id=organization_id,
        subscription_id=subscription.id,
        amount=amount_due,
        currency=subscription.currency_snapshot,
        payment_method=data.payment_method,
        provider="manual",
        provider_reference=data.provider_reference,
        status="succeeded",
        recorded_by=user.id,
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    subscription.status = "active"
    subscription.activated_at = datetime.now(timezone.utc)
    generated_documents = []
    try:
        await db.flush()
        invoice = await _create_invoice(db, subscription)
        await db.flush()
        generated_documents.append(
            await create_private_pdf_document(
                db,
                organization_id,
                subscription.id,
                "invoice",
                "Membership Invoice",
                [
                    f"Invoice: {invoice.invoice_number}",
                    f"Subscription: {subscription.id}",
                    f"Member ID: {subscription.member_id}",
                    f"Subtotal: {invoice.subtotal} {invoice.currency}",
                    f"Tax: {invoice.tax_amount} {invoice.currency}",
                    f"Total: {invoice.total_amount} {invoice.currency}",
                ],
                {"invoice_id": invoice.id},
            )
        )
        generated_documents.append(
            await create_private_pdf_document(
                db,
                organization_id,
                subscription.id,
                "receipt",
                "Membership Payment Receipt",
                [
                    f"Subscription: {subscription.id}",
                    f"Payment ID: {payment.id}",
                    f"Amount received: {payment.amount} {payment.currency}",
                    f"Payment method: {payment.payment_method}",
                    f"Reference: {payment.provider_reference or 'Not provided'}",
                    f"Paid at: {payment.paid_at.isoformat()}",
                ],
                {"payment_id": payment.id},
            )
        )
        await db.commit()
    except Exception as exc:
        await db.rollback()
        for document in generated_documents:
            delete_private_document(document.storage_key)
        if isinstance(exc, IntegrityError):
            raise _http_error(409, "Payment reference has already been recorded") from None
        raise
    await db.refresh(payment)
    await db.refresh(subscription)
    return payment, subscription


async def list_member_subscriptions(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    member_id: int,
) -> list[dict]:
    result = await db.execute(
        select(MemberSubscription)
        .join(
            SubscriptionAccessGym,
            SubscriptionAccessGym.subscription_id == MemberSubscription.id,
        )
        .where(
            MemberSubscription.organization_id == organization_id,
            SubscriptionAccessGym.organization_id == organization_id,
            SubscriptionAccessGym.gym_id == gym_id,
            MemberSubscription.member_id == member_id,
        )
        .order_by(MemberSubscription.created_at.desc())
    )
    return [await _subscription_payload(db, item) for item in result.scalars().all()]


async def get_gym_subscription(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
) -> MemberSubscription | None:
    result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.id == subscription_id,
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.purchased_at_gym_id == gym_id,
        )
    )
    return result.scalar_one_or_none()


async def get_accessible_subscription(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
) -> MemberSubscription | None:
    result = await db.execute(
        select(MemberSubscription)
        .join(
            SubscriptionAccessGym,
            SubscriptionAccessGym.subscription_id == MemberSubscription.id,
        )
        .where(
            MemberSubscription.id == subscription_id,
            MemberSubscription.organization_id == organization_id,
            SubscriptionAccessGym.organization_id == organization_id,
            SubscriptionAccessGym.gym_id == gym_id,
        )
    )
    return result.scalar_one_or_none()


async def cancel_subscription(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
) -> dict | None:
    subscription = await get_gym_subscription(db, organization_id, gym_id, subscription_id)
    if subscription is None:
        return None
    if subscription.status not in {"active", "pending_payment"}:
        raise _http_error(409, "Only active or pending subscriptions can be cancelled")
    rules = subscription.rules_snapshot or {}
    if not rules.get("cancellation_allowed", True):
        raise _http_error(403, "Cancellation is not allowed by this membership plan")
    subscription.status = "cancelled"
    subscription.cancelled_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(subscription)
    return await _subscription_payload(db, subscription)


async def get_subscription_invoice(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
) -> Invoice | None:
    subscription = await get_accessible_subscription(db, organization_id, gym_id, subscription_id)
    if subscription is None:
        return None
    result = await db.execute(
        select(Invoice).where(
            Invoice.organization_id == organization_id,
            Invoice.subscription_id == subscription_id,
        )
    )
    return result.scalar_one_or_none()


async def assign_member_to_gym(
    db: AsyncSession,
    organization_id: int,
    member_id: int,
    gym_id: int,
    is_primary: bool = False,
) -> MemberGymAssignment:
    member_result = await db.execute(
        select(Member).where(
            Member.id == member_id,
            Member.organization_id == organization_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise _http_error(404, "Member not found")

    gym_result = await db.execute(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.organization_id == organization_id,
        )
    )
    if gym_result.scalar_one_or_none() is None:
        raise _http_error(404, "Gym not found")

    existing_result = await db.execute(
        select(MemberGymAssignment).where(
            MemberGymAssignment.member_id == member_id,
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.organization_id == organization_id,
        )
    )
    assignment = existing_result.scalar_one_or_none()
    if assignment is not None and assignment.status == "active":
        raise _http_error(409, "Member is already assigned to this gym")

    if is_primary:
        primary_result = await db.execute(
            select(MemberGymAssignment).where(
                MemberGymAssignment.member_id == member_id,
                MemberGymAssignment.organization_id == organization_id,
                MemberGymAssignment.status == "active",
                MemberGymAssignment.is_primary.is_(True),
            )
        )
        for current_primary in primary_result.scalars().all():
            current_primary.is_primary = False

    if assignment is None:
        assignment = MemberGymAssignment(
            organization_id=organization_id,
            member_id=member_id,
            gym_id=gym_id,
            is_primary=is_primary,
            status="active",
        )
        db.add(assignment)
    else:
        assignment.status = "active"
        assignment.is_primary = is_primary

    if is_primary or member.gym_id == gym_id:
        member.gym_id = gym_id
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def list_member_gym_assignments(
    db: AsyncSession,
    organization_id: int,
    member_id: int,
) -> list[MemberGymAssignment]:
    member_result = await db.execute(
        select(Member.id).where(
            Member.id == member_id,
            Member.organization_id == organization_id,
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise _http_error(404, "Member not found")
    result = await db.execute(
        select(MemberGymAssignment)
        .where(
            MemberGymAssignment.organization_id == organization_id,
            MemberGymAssignment.member_id == member_id,
        )
        .order_by(MemberGymAssignment.is_primary.desc(), MemberGymAssignment.id)
    )
    return list(result.scalars().all())


async def remove_member_gym_assignment(
    db: AsyncSession,
    organization_id: int,
    member_id: int,
    gym_id: int,
) -> bool:
    member_result = await db.execute(
        select(Member).where(
            Member.id == member_id,
            Member.organization_id == organization_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        return False

    result = await db.execute(
        select(MemberGymAssignment).where(
            MemberGymAssignment.organization_id == organization_id,
            MemberGymAssignment.member_id == member_id,
            MemberGymAssignment.gym_id == gym_id,
            MemberGymAssignment.status == "active",
        )
    )
    assignment = result.scalar_one_or_none()
    if assignment is None:
        return False

    was_primary = assignment.is_primary
    assignment.status = "inactive"
    assignment.is_primary = False
    if member.gym_id == gym_id or was_primary:
        remaining_result = await db.execute(
            select(MemberGymAssignment).where(
                MemberGymAssignment.organization_id == organization_id,
                MemberGymAssignment.member_id == member_id,
                MemberGymAssignment.status == "active",
                MemberGymAssignment.gym_id != gym_id,
            ).order_by(MemberGymAssignment.id)
        )
        remaining = remaining_result.scalars().all()
        if remaining:
            remaining[0].is_primary = True
            member.gym_id = remaining[0].gym_id
    await db.commit()
    return True


async def renew_subscription(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    user: User,
    subscription_id: int,
    start_date: date | None,
    terms_accepted: bool,
    acceptance_method: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> dict:
    previous = await get_gym_subscription(
        db, organization_id, gym_id, subscription_id
    )
    if previous is None:
        raise _http_error(404, "Subscription not found")
    if previous.status not in {"active", "expired"}:
        raise _http_error(409, "Only active or expired subscriptions can be renewed")

    from zoneinfo import ZoneInfo

    gym_result = await db.execute(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.organization_id == organization_id,
        )
    )
    gym = gym_result.scalar_one_or_none()
    if gym is None:
        raise _http_error(404, "Gym not found")
    local_today = datetime.now(ZoneInfo(gym.timezone)).date()
    earliest_start = max(local_today, previous.end_date)
    renewal_start = start_date or earliest_start
    if renewal_start < earliest_start:
        raise _http_error(422, "Renewal cannot overlap the previous subscription or start in the past")

    renewal = SubscriptionCreate(
        member_id=previous.member_id,
        membership_plan_id=previous.membership_plan_id,
        start_date=renewal_start,
        terms_accepted=terms_accepted,
        acceptance_method=acceptance_method,
    )
    return await create_subscription(
        db, organization_id, gym_id, user, renewal, ip_address, user_agent
    )


async def list_subscription_documents(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
) -> list[MembershipDocument]:
    subscription = await get_accessible_subscription(
        db, organization_id, gym_id, subscription_id
    )
    if subscription is None:
        raise _http_error(404, "Subscription not found")
    result = await db.execute(
        select(MembershipDocument)
        .where(
            MembershipDocument.organization_id == organization_id,
            MembershipDocument.subscription_id == subscription_id,
        )
        .order_by(MembershipDocument.generated_at.desc())
    )
    return list(result.scalars().all())


async def get_subscription_document(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    subscription_id: int,
    document_id: int,
) -> MembershipDocument | None:
    subscription = await get_accessible_subscription(
        db, organization_id, gym_id, subscription_id
    )
    if subscription is None:
        return None
    result = await db.execute(
        select(MembershipDocument).where(
            MembershipDocument.id == document_id,
            MembershipDocument.organization_id == organization_id,
            MembershipDocument.subscription_id == subscription_id,
        )
    )
    return result.scalar_one_or_none()


async def check_member_membership_access(
    db: AsyncSession,
    organization_id: int,
    gym_id: int,
    member_id: int,
) -> dict:
    from zoneinfo import ZoneInfo

    gym_result = await db.execute(
        select(Gym).where(
            Gym.id == gym_id,
            Gym.organization_id == organization_id,
        )
    )
    gym = gym_result.scalar_one_or_none()
    if gym is None:
        raise _http_error(404, "Gym not found")

    member_result = await db.execute(
        select(Member.id).where(
            Member.id == member_id,
            Member.organization_id == organization_id,
        )
    )
    if member_result.scalar_one_or_none() is None:
        raise _http_error(404, "Member not found")

    checked_on = datetime.now(ZoneInfo(gym.timezone)).date()
    expired_result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.member_id == member_id,
            MemberSubscription.status == "active",
            MemberSubscription.end_date <= checked_on,
        )
    )
    expired_subscriptions = expired_result.scalars().all()
    for subscription in expired_subscriptions:
        subscription.status = "expired"
    if expired_subscriptions:
        await db.commit()

    access_result = await db.execute(
        select(MemberSubscription.id)
        .join(
            SubscriptionAccessGym,
            SubscriptionAccessGym.subscription_id == MemberSubscription.id,
        )
        .where(
            MemberSubscription.organization_id == organization_id,
            MemberSubscription.member_id == member_id,
            MemberSubscription.status == "active",
            MemberSubscription.start_date <= checked_on,
            MemberSubscription.end_date > checked_on,
            ~select(SubscriptionFreeze.id).where(
                SubscriptionFreeze.organization_id == organization_id,
                SubscriptionFreeze.subscription_id == MemberSubscription.id,
                SubscriptionFreeze.status == "applied",
                SubscriptionFreeze.start_date <= checked_on,
                SubscriptionFreeze.end_date > checked_on,
            ).exists(),
            SubscriptionAccessGym.organization_id == organization_id,
            SubscriptionAccessGym.gym_id == gym_id,
        )
        .order_by(MemberSubscription.end_date.desc())
    )
    active_ids = list(access_result.scalars().all())
    return {
        "member_id": member_id,
        "gym_id": gym_id,
        "has_access": bool(active_ids),
        "checked_on": checked_on,
        "active_subscription_ids": active_ids,
    }
