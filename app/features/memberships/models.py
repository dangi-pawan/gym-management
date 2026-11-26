from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MembershipPlan(Base):
    __tablename__ = "membership_plans"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_membership_plans_id_org"),
        CheckConstraint("duration_value > 0", name="ck_membership_plans_duration_positive"),
        CheckConstraint("base_price >= 0", name="ck_membership_plans_price_nonnegative"),
        CheckConstraint("joining_fee >= 0", name="ck_membership_plans_joining_fee_nonnegative"),
        CheckConstraint("duration_unit IN ('day', 'week', 'month', 'year')", name="ck_membership_plans_duration_unit"),
        CheckConstraint("access_type IN ('home_gym', 'all_gyms', 'selected_gyms')", name="ck_membership_plans_access_type"),
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_membership_plans_status"),
        ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_membership_plans_creator_org",
        ),
        Index("ix_membership_plans_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    duration_value: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_unit: Mapped[str] = mapped_column(String(10), nullable=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    joining_fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="INR")
    access_type: Mapped[str] = mapped_column(String(20), nullable=False)
    terms_id: Mapped[int | None] = mapped_column(ForeignKey("membership_terms.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class GymMembershipPlan(Base):
    __tablename__ = "gym_membership_plans"
    __table_args__ = (
        UniqueConstraint("gym_id", "membership_plan_id", name="uq_gym_membership_plans_gym_plan"),
        ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_gym_membership_plans_gym_org"),
        ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_gym_membership_plans_plan_org"),
        CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_gym_membership_plans_price_nonnegative"),
        CheckConstraint("joining_fee_override IS NULL OR joining_fee_override >= 0", name="ck_gym_membership_plans_fee_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    gym_id: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    price_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    joining_fee_override: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MembershipPlanAccessGym(Base):
    __tablename__ = "membership_plan_access_gyms"
    __table_args__ = (
        UniqueConstraint("membership_plan_id", "gym_id", name="uq_membership_plan_access_plan_gym"),
        ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_membership_plan_access_plan_org"),
        ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_membership_plan_access_gym_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    membership_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gym_id: Mapped[int] = mapped_column(Integer, nullable=False)


class MembershipPlanRules(Base):
    __tablename__ = "membership_plan_rules"
    __table_args__ = (
        CheckConstraint("max_freeze_days IS NULL OR max_freeze_days >= 0", name="ck_membership_plan_rules_freeze_days_nonnegative"),
        CheckConstraint("freeze_allowed OR max_freeze_days IS NULL OR max_freeze_days = 0", name="ck_membership_plan_rules_freeze_disabled"),
        CheckConstraint("transfer_allowed IS FALSE", name="ck_membership_plan_rules_transfer_disabled"),
        CheckConstraint("auto_renew_allowed IS FALSE", name="ck_membership_plan_rules_auto_renew_disabled"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    membership_plan_id: Mapped[int] = mapped_column(ForeignKey("membership_plans.id", ondelete="CASCADE"), nullable=False, unique=True)
    freeze_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    max_freeze_days: Mapped[int | None] = mapped_column(Integer)
    transfer_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    cancellation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    refund_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    auto_renew_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class MembershipTerms(Base):
    __tablename__ = "membership_terms"
    __table_args__ = (
        UniqueConstraint("organization_id", "version", name="uq_membership_terms_org_version"),
        CheckConstraint("version > 0", name="ck_membership_terms_version_positive"),
        CheckConstraint("status IN ('draft', 'published', 'retired')", name="ck_membership_terms_status"),
        ForeignKeyConstraint(["created_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_membership_terms_creator_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MemberGymAssignment(Base):
    __tablename__ = "member_gym_assignments"
    __table_args__ = (
        UniqueConstraint("member_id", "gym_id", name="uq_member_gym_assignments_member_gym"),
        ForeignKeyConstraint(["member_id", "organization_id"], ["members.id", "members.organization_id"], name="fk_member_gym_assignments_member_org"),
        ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_member_gym_assignments_gym_org"),
        CheckConstraint("status IN ('active', 'inactive')", name="ck_member_gym_assignments_status"),
        Index("uq_member_gym_assignments_primary_active", "member_id", unique=True, postgresql_where=text("is_primary IS TRUE AND status = 'active'")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gym_id: Mapped[int] = mapped_column(Integer, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MemberSubscription(Base):
    __tablename__ = "member_subscriptions"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_member_subscriptions_id_org"),
        ForeignKeyConstraint(["member_id", "organization_id"], ["members.id", "members.organization_id"], name="fk_member_subscriptions_member_org"),
        ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_member_subscriptions_plan_org"),
        ForeignKeyConstraint(["purchased_at_gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_member_subscriptions_gym_org"),
        ForeignKeyConstraint(["created_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_member_subscriptions_creator_org"),
        CheckConstraint("status IN ('pending_payment', 'active', 'expired', 'cancelled')", name="ck_member_subscriptions_status"),
        CheckConstraint("end_date > start_date", name="ck_member_subscriptions_date_range"),
        CheckConstraint("plan_price_snapshot >= 0 AND joining_fee_snapshot >= 0", name="ck_member_subscriptions_prices_nonnegative"),
        Index("ix_member_subscriptions_org_member", "organization_id", "member_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    member_id: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    purchased_at_gym_id: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending_payment")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    plan_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_value_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_unit_snapshot: Mapped[str] = mapped_column(String(10), nullable=False)
    plan_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    joining_fee_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency_snapshot: Mapped[str] = mapped_column(String(3), nullable=False)
    access_type_snapshot: Mapped[str] = mapped_column(String(20), nullable=False)
    rules_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    gst_rate_snapshot: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    tax_mode_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, server_default="intra_state")
    gstin_snapshot: Mapped[str | None] = mapped_column(String(15))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SubscriptionAccessGym(Base):
    __tablename__ = "subscription_access_gyms"
    __table_args__ = (
        UniqueConstraint("subscription_id", "gym_id", name="uq_subscription_access_subscription_gym"),
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_access_subscription_org"),
        ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_subscription_access_gym_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    gym_id: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class SubscriptionTermsAcceptance(Base):
    __tablename__ = "subscription_terms_acceptances"
    __table_args__ = (
        UniqueConstraint("subscription_id", name="uq_subscription_terms_acceptances_subscription"),
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_terms_subscription_org"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_terms_id: Mapped[int] = mapped_column(ForeignKey("membership_terms.id"), nullable=False)
    terms_version_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    terms_content_hash_snapshot: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_by_member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"))
    acceptance_method: Mapped[str] = mapped_column(String(30), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(500))


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_payments_id_org"),
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_payments_subscription_org"),
        CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'refunded', 'partially_refunded')", name="ck_payments_status"),
        Index("ix_payments_org_subscription", "organization_id", "subscription_id"),
        Index("uq_payments_provider_reference", "provider", "provider_reference", unique=True, postgresql_where=text("provider_reference IS NOT NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, server_default="manual")
    provider_reference: Mapped[str | None] = mapped_column(String(150))
    provider_order_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, server_default="pending")
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("organization_id", "invoice_number", name="uq_invoices_org_number"),
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_invoices_subscription_org"),
        CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_invoices_amounts_nonnegative"),
        CheckConstraint("status IN ('draft', 'issued', 'void')", name="ck_invoices_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    invoice_number: Mapped[str] = mapped_column(String(50), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    cgst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    sgst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    igst_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, server_default="0")
    gstin_snapshot: Mapped[str | None] = mapped_column(String(15))
    tax_mode_snapshot: Mapped[str] = mapped_column(String(20), nullable=False, server_default="intra_state")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class MembershipDocument(Base):
    __tablename__ = "membership_documents"
    __table_args__ = (
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_membership_documents_subscription_org"),
        CheckConstraint("document_type IN ('agreement', 'invoice', 'receipt', 'other')", name="ck_membership_documents_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(Integer)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


class MembershipTaxSettings(Base):
    __tablename__ = "membership_tax_settings"
    __table_args__ = (
        CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_membership_tax_gst_rate"),
        CheckConstraint("tax_mode IN ('intra_state', 'inter_state')", name="ck_membership_tax_mode"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, unique=True)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    gstin: Mapped[str | None] = mapped_column(String(15))
    tax_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="intra_state")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SubscriptionFreeze(Base):
    __tablename__ = "subscription_freezes"
    __table_args__ = (
        ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_freezes_subscription_org"),
        ForeignKeyConstraint(["created_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_subscription_freezes_creator_org"),
        CheckConstraint("end_date > start_date", name="ck_subscription_freezes_date_range"),
        CheckConstraint("status IN ('applied', 'cancelled')", name="ck_subscription_freezes_status"),
        Index("ix_subscription_freezes_org_subscription", "organization_id", "subscription_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    subscription_id: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="applied")
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PaymentRefund(Base):
    __tablename__ = "payment_refunds"
    __table_args__ = (
        ForeignKeyConstraint(["payment_id", "organization_id"], ["payments.id", "payments.organization_id"], name="fk_payment_refunds_payment_org"),
        ForeignKeyConstraint(["recorded_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_payment_refunds_user_org"),
        CheckConstraint("amount > 0", name="ck_payment_refunds_amount_positive"),
        CheckConstraint("status IN ('pending', 'processed', 'failed')", name="ck_payment_refunds_status"),
        Index("ix_payment_refunds_org_payment", "organization_id", "payment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    payment_id: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    provider_refund_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    reason: Mapped[str | None] = mapped_column(String(500))
    recorded_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaymentWebhookEvent(Base):
    __tablename__ = "payment_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_payment_webhook_provider_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    event_id: Mapped[str] = mapped_column(String(150), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
