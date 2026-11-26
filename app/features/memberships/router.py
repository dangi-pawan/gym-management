import asyncio
import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.db.session import get_db
from app.features.memberships.schemas import (
    GymMembershipPlanUpdate,
    InvoiceResponse,
    ManualPaymentCreate,
    MembershipDocumentListEnvelope,
    MembershipDocumentResponse,
    MembershipAccessEnvelope,
    MemberGymAssignmentCreate,
    MemberGymAssignmentResponse,
    MembershipPlanCreate,
    MembershipPlanListEnvelope,
    MembershipPlanResponse,
    MembershipPlanResponseEnvelope,
    MembershipPlanUpdate,
    MembershipTermsCreate,
    MembershipTermsEnvelope,
    MembershipTermsListEnvelope,
    MembershipTermsResponse,
    PaymentEnvelope,
    PaymentResponse,
    SubscriptionCreate,
    SubscriptionEnvelope,
    SubscriptionListEnvelope,
    SubscriptionResponse,
    SubscriptionRenew,
    InvoiceEnvelope,
)
from app.features.memberships.documents import read_private_document
from app.features.memberships.advanced_service import (
    create_razorpay_order, handle_razorpay_webhook, update_tax_settings,
    freeze_subscription, refund_payment, retry_pending_refund,
)
from app.features.memberships.schemas import (
    MembershipTaxSettingsUpdate, MembershipTaxSettingsResponse,
    SubscriptionFreezeCreate, SubscriptionFreezeResponse,
    RefundCreate, RefundResponse,
)
from app.features.memberships.service import (
    activate_membership_plan,
    assign_member_to_gym,
    list_member_gym_assignments,
    remove_member_gym_assignment,
    archive_membership_plan,
    cancel_subscription,
    create_membership_plan,
    create_membership_terms,
    create_subscription,
    get_gym_subscription,
    get_accessible_subscription,
    get_membership_plan,
    get_subscription_invoice,
    check_member_membership_access,
    get_subscription_document,
    list_subscription_documents,
    list_gym_membership_plans,
    list_member_subscriptions,
    list_membership_plans,
    list_membership_terms,
    publish_membership_terms,
    record_manual_payment,
    renew_subscription,
    set_gym_membership_plan,
    update_membership_plan,
)
from app.features.users.dependencies import get_current_user, require_gym_roles, require_org_roles
from app.features.users.models import User


router = APIRouter(tags=["Membership Management"])


def _ensure_current_organization(path_organization_id: int, user: User) -> None:
    if path_organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Organization not found")


@router.post(
    "/organizations/{organization_id}/membership-plans",
    response_model=MembershipPlanResponseEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def create_plan_endpoint(
    organization_id: int,
    data: MembershipPlanCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    plan = await create_membership_plan(db, organization_id, current_user, data)
    return success_response(message="Membership plan created as draft", data=plan)


@router.get(
    "/organizations/{organization_id}/membership-plans",
    response_model=MembershipPlanListEnvelope,
)
async def list_plans_endpoint(
    organization_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    plans = await list_membership_plans(db, organization_id)
    return success_response(message="Membership plans fetched successfully", data=plans)


@router.get(
    "/organizations/{organization_id}/membership-plans/{plan_id}",
    response_model=MembershipPlanResponseEnvelope,
)
async def get_plan_endpoint(
    organization_id: int,
    plan_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    plan = await get_membership_plan(db, organization_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Membership plan not found")
    return success_response(message="Membership plan fetched successfully", data=plan)


@router.patch(
    "/organizations/{organization_id}/membership-plans/{plan_id}",
    response_model=MembershipPlanResponseEnvelope,
)
async def update_plan_endpoint(
    organization_id: int,
    plan_id: int,
    data: MembershipPlanUpdate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    plan = await update_membership_plan(db, organization_id, plan_id, data)
    if plan is None:
        raise HTTPException(status_code=404, detail="Membership plan not found")
    return success_response(message="Membership plan updated successfully", data=plan)


@router.post(
    "/organizations/{organization_id}/membership-plans/{plan_id}/activate",
    response_model=MembershipPlanResponseEnvelope,
)
async def activate_plan_endpoint(
    organization_id: int,
    plan_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    plan = await activate_membership_plan(db, organization_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Membership plan not found")
    return success_response(message="Membership plan activated", data=plan)


@router.post(
    "/organizations/{organization_id}/membership-plans/{plan_id}/archive",
)
async def archive_plan_endpoint(
    organization_id: int,
    plan_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    archived = await archive_membership_plan(db, organization_id, plan_id)
    if not archived:
        raise HTTPException(status_code=404, detail="Membership plan not found")
    return success_response(message="Membership plan archived")


@router.put("/gyms/{gym_id}/membership-plans/{plan_id}")
async def set_gym_plan_endpoint(
    gym_id: int,
    plan_id: int,
    data: GymMembershipPlanUpdate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    result = await set_gym_membership_plan(
        db, current_user.organization_id, gym_id, plan_id, data
    )
    return success_response(message="Gym membership plan availability updated", data=result)


@router.get(
    "/gyms/{gym_id}/membership-plans",
    response_model=MembershipPlanListEnvelope,
)
async def list_gym_plans_endpoint(
    gym_id: int,
    _: Annotated[User, Depends(require_gym_roles("manager", "trainer", "receptionist"))],
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    plans = await list_gym_membership_plans(db, current_user.organization_id, gym_id)
    return success_response(message="Available gym membership plans fetched", data=plans)


@router.post(
    "/organizations/{organization_id}/membership-terms",
    response_model=MembershipTermsEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def create_terms_endpoint(
    organization_id: int,
    data: MembershipTermsCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    terms = await create_membership_terms(db, organization_id, current_user, data)
    return success_response(
        message="Membership terms draft created",
        data=MembershipTermsResponse.model_validate(terms),
    )


@router.get(
    "/organizations/{organization_id}/membership-terms",
    response_model=MembershipTermsListEnvelope,
)
async def list_terms_endpoint(
    organization_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    terms = await list_membership_terms(db, organization_id)
    return success_response(
        message="Membership terms fetched successfully",
        data=[MembershipTermsResponse.model_validate(item) for item in terms],
    )


@router.post(
    "/organizations/{organization_id}/membership-terms/{terms_id}/publish",
    response_model=MembershipTermsEnvelope,
)
async def publish_terms_endpoint(
    organization_id: int,
    terms_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    terms = await publish_membership_terms(db, organization_id, terms_id)
    if terms is None:
        raise HTTPException(status_code=404, detail="Membership terms not found")
    return success_response(
        message="Membership terms published",
        data=MembershipTermsResponse.model_validate(terms),
    )


@router.post(
    "/gyms/{gym_id}/members/{member_id}/subscriptions",
    response_model=SubscriptionEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription_endpoint(
    gym_id: int,
    member_id: int,
    data: SubscriptionCreate,
    request: Request,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    if data.member_id != member_id:
        raise HTTPException(status_code=422, detail="Member ID in path and body must match")
    subscription = await create_subscription(
        db,
        current_user.organization_id,
        gym_id,
        current_user,
        data,
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )
    return success_response(
        message="Subscription created",
        data=subscription,
    )


@router.get(
    "/gyms/{gym_id}/members/{member_id}/subscriptions",
    response_model=SubscriptionListEnvelope,
)
async def list_member_subscriptions_endpoint(
    gym_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "trainer", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    subscriptions = await list_member_subscriptions(
        db, current_user.organization_id, gym_id, member_id
    )
    return success_response(
        message="Member subscriptions fetched successfully",
        data=subscriptions,
    )


@router.get(
    "/gyms/{gym_id}/subscriptions/{subscription_id}",
    response_model=SubscriptionEnvelope,
)
async def get_subscription_endpoint(
    gym_id: int,
    subscription_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "trainer", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    subscription = await get_accessible_subscription(
        db, current_user.organization_id, gym_id, subscription_id
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    from app.features.memberships.service import _subscription_payload
    return success_response(
        message="Subscription fetched successfully",
        data=await _subscription_payload(db, subscription),
    )


@router.post(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/payments/manual",
    response_model=PaymentEnvelope,
)
async def record_manual_payment_endpoint(
    gym_id: int,
    subscription_id: int,
    data: ManualPaymentCreate,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    payment, _ = await record_manual_payment(
        db, current_user.organization_id, gym_id, subscription_id, current_user, data
    )
    return success_response(
        message="Manual payment recorded and subscription activated",
        data=PaymentResponse.model_validate(payment),
    )


@router.post(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/cancel",
    response_model=SubscriptionEnvelope,
)
async def cancel_subscription_endpoint(
    gym_id: int,
    subscription_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    subscription = await cancel_subscription(
        db, current_user.organization_id, gym_id, subscription_id
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return success_response(message="Subscription cancelled", data=subscription)


@router.get(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/invoice",
    response_model=InvoiceEnvelope,
)
async def get_subscription_invoice_endpoint(
    gym_id: int,
    subscription_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    invoice = await get_subscription_invoice(
        db, current_user.organization_id, gym_id, subscription_id
    )
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return success_response(
        message="Invoice fetched successfully",
        data=InvoiceResponse.model_validate(invoice),
    )


@router.post(
    "/organizations/{organization_id}/members/{member_id}/gym-assignments",
    status_code=status.HTTP_201_CREATED,
)
async def assign_member_gym_endpoint(
    organization_id: int,
    member_id: int,
    data: MemberGymAssignmentCreate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    assignment = await assign_member_to_gym(
        db,
        organization_id,
        member_id,
        data.gym_id,
        data.is_primary,
    )
    return success_response(
        message="Member assigned to gym successfully",
        data=MemberGymAssignmentResponse.model_validate(assignment),
    )


@router.get(
    "/organizations/{organization_id}/members/{member_id}/gym-assignments",
)
async def list_member_gym_assignments_endpoint(
    organization_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    assignments = await list_member_gym_assignments(db, organization_id, member_id)
    return success_response(
        message="Member gym assignments fetched successfully",
        data=[MemberGymAssignmentResponse.model_validate(item) for item in assignments],
    )


@router.delete(
    "/organizations/{organization_id}/members/{member_id}/gym-assignments/{gym_id}",
)
async def remove_member_gym_assignment_endpoint(
    organization_id: int,
    member_id: int,
    gym_id: int,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    removed = await remove_member_gym_assignment(
        db, organization_id, member_id, gym_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="Member gym assignment not found")
    return success_response(message="Member gym assignment removed")


@router.post(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/renew",
    response_model=SubscriptionEnvelope,
    status_code=status.HTTP_201_CREATED,
)
async def renew_subscription_endpoint(
    gym_id: int,
    subscription_id: int,
    data: SubscriptionRenew,
    request: Request,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    subscription = await renew_subscription(
        db,
        current_user.organization_id,
        gym_id,
        current_user,
        subscription_id,
        data.start_date,
        data.terms_accepted,
        data.acceptance_method,
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )
    return success_response(message="Subscription renewal created", data=subscription)


@router.get(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/documents",
    response_model=MembershipDocumentListEnvelope,
)
async def list_subscription_documents_endpoint(
    gym_id: int,
    subscription_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    documents = await list_subscription_documents(
        db, current_user.organization_id, gym_id, subscription_id
    )
    return success_response(
        message="Subscription documents fetched successfully",
        data=[MembershipDocumentResponse.model_validate(item) for item in documents],
    )


@router.get(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/documents/{document_id}",
)
async def download_subscription_document_endpoint(
    gym_id: int,
    subscription_id: int,
    document_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    document = await get_subscription_document(
        db,
        current_user.organization_id,
        gym_id,
        subscription_id,
        document_id,
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        content = await asyncio.to_thread(read_private_document, document.storage_key)
    except (FileNotFoundError, ValueError, OSError):
        raise HTTPException(status_code=404, detail="Document file not found") from None
    if not hashlib.sha256(content).hexdigest() == document.checksum:
        raise HTTPException(status_code=500, detail="Stored document integrity check failed")
    return Response(
        content=content,
        media_type=document.content_type,
        headers={"Content-Disposition": f'attachment; filename="membership-{document.document_type}-{document.id}.pdf"'},
    )


@router.get(
    "/gyms/{gym_id}/members/{member_id}/membership-access",
    response_model=MembershipAccessEnvelope,
)
async def check_member_membership_access_endpoint(
    gym_id: int,
    member_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "trainer", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    access = await check_member_membership_access(
        db, current_user.organization_id, gym_id, member_id
    )
    return success_response(
        message="Membership access evaluated successfully",
        data=access,
    )


@router.put("/organizations/{organization_id}/membership-tax-settings")
async def update_membership_tax_settings_endpoint(
    organization_id: int,
    data: MembershipTaxSettingsUpdate,
    current_user: Annotated[User, Depends(require_org_roles("owner", "admin"))],
    db: AsyncSession = Depends(get_db),
):
    _ensure_current_organization(organization_id, current_user)
    settings = await update_tax_settings(
        db, organization_id, data.gst_rate, data.gstin, data.tax_mode
    )
    return success_response(
        message="Membership GST settings updated",
        data=MembershipTaxSettingsResponse.model_validate(settings),
    )


@router.post("/gyms/{gym_id}/subscriptions/{subscription_id}/payments/razorpay-order")
async def create_razorpay_order_endpoint(
    gym_id: int,
    subscription_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    order = await create_razorpay_order(
        db, current_user.organization_id, gym_id, subscription_id, current_user
    )
    return success_response(message="Razorpay order created", data=order)


@router.post("/payments/razorpay/webhook")
async def razorpay_webhook_endpoint(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    event_id = request.headers.get("X-Razorpay-Event-Id", "")
    if not signature or not event_id:
        raise HTTPException(status_code=400, detail="Missing Razorpay webhook signature or event ID")
    if len(event_id) > 150:
        raise HTTPException(status_code=400, detail="Invalid Razorpay webhook event ID")
    result = await handle_razorpay_webhook(db, raw_body, signature, event_id)
    return success_response(message="Razorpay webhook processed", data=result)


@router.post(
    "/gyms/{gym_id}/subscriptions/{subscription_id}/freeze",
    status_code=status.HTTP_201_CREATED,
)
async def freeze_subscription_endpoint(
    gym_id: int,
    subscription_id: int,
    data: SubscriptionFreezeCreate,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    freeze = await freeze_subscription(
        db, current_user.organization_id, gym_id, subscription_id,
        current_user, data.start_date, data.end_date, data.reason,
    )
    return success_response(
        message="Membership freeze applied",
        data=SubscriptionFreezeResponse.model_validate(freeze),
    )


@router.post(
    "/gyms/{gym_id}/payments/{payment_id}/refunds",
    status_code=status.HTTP_201_CREATED,
)
async def refund_payment_endpoint(
    gym_id: int,
    payment_id: int,
    data: RefundCreate,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    refund = await refund_payment(
        db, current_user.organization_id, gym_id, payment_id,
        current_user, data.amount, data.reason,
    )
    return success_response(
        message="Payment refund processed",
        data=RefundResponse.model_validate(refund),
    )

@router.post(
    "/gyms/{gym_id}/refunds/{refund_id}/retry",
    response_model=APIResponse[RefundResponse],
)
async def retry_pending_refund_endpoint(
    gym_id: int,
    refund_id: int,
    current_user: Annotated[User, Depends(require_gym_roles("manager", "receptionist"))],
    db: AsyncSession = Depends(get_db),
):
    refund = await retry_pending_refund(
        db, current_user.organization_id, gym_id, refund_id,
    )
    return success_response(
        message="Pending refund reconciled with Razorpay",
        data=RefundResponse.model_validate(refund),
    )
