"""Complete membership billing, GST, freeze and refund foundations.

Revision ID: 9d4c2e7a1b63
Revises: e41b7c9d2a60
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d4c2e7a1b63"
down_revision: Union[str, Sequence[str], None] = "e41b7c9d2a60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE membership_plan_rules SET transfer_allowed = false WHERE transfer_allowed IS TRUE")
    op.create_check_constraint("ck_membership_plan_rules_transfer_disabled", "membership_plan_rules", "transfer_allowed IS FALSE")
    op.add_column("member_subscriptions", sa.Column("gst_rate_snapshot", sa.Numeric(5, 2), server_default="0", nullable=False))
    op.add_column("member_subscriptions", sa.Column("tax_mode_snapshot", sa.String(20), server_default="intra_state", nullable=False))
    op.add_column("member_subscriptions", sa.Column("gstin_snapshot", sa.String(15), nullable=True))
    op.add_column("member_subscriptions", sa.Column("auto_renew_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("member_subscriptions", sa.Column("razorpay_subscription_id", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_member_subscriptions_razorpay_subscription", "member_subscriptions", ["razorpay_subscription_id"])

    op.add_column("payments", sa.Column("provider_order_id", sa.String(100), nullable=True))
    op.add_column("payments", sa.Column("provider_payment_id", sa.String(100), nullable=True))
    op.create_unique_constraint("uq_payments_id_org", "payments", ["id", "organization_id"])
    op.create_unique_constraint("uq_payments_provider_order_id", "payments", ["provider_order_id"])
    op.create_unique_constraint("uq_payments_provider_payment_id", "payments", ["provider_payment_id"])

    op.add_column("invoices", sa.Column("gst_rate", sa.Numeric(5, 2), server_default="0", nullable=False))
    op.add_column("invoices", sa.Column("cgst_amount", sa.Numeric(12, 2), server_default="0", nullable=False))
    op.add_column("invoices", sa.Column("sgst_amount", sa.Numeric(12, 2), server_default="0", nullable=False))
    op.add_column("invoices", sa.Column("igst_amount", sa.Numeric(12, 2), server_default="0", nullable=False))
    op.add_column("invoices", sa.Column("gstin_snapshot", sa.String(15), nullable=True))
    op.add_column("invoices", sa.Column("tax_mode_snapshot", sa.String(20), server_default="intra_state", nullable=False))

    op.create_table(
        "membership_tax_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False, unique=True),
        sa.Column("gst_rate", sa.Numeric(5, 2), server_default="0", nullable=False),
        sa.Column("gstin", sa.String(15), nullable=True),
        sa.Column("tax_mode", sa.String(20), server_default="intra_state", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("gst_rate >= 0 AND gst_rate <= 100", name="ck_membership_tax_gst_rate"),
        sa.CheckConstraint("tax_mode IN ('intra_state', 'inter_state')", name="ck_membership_tax_mode"),
    )

    op.create_table(
        "subscription_freezes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="applied", nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_freezes_subscription_org"),
        sa.ForeignKeyConstraint(["created_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_subscription_freezes_creator_org"),
        sa.CheckConstraint("end_date > start_date", name="ck_subscription_freezes_date_range"),
        sa.CheckConstraint("days > 0", name="ck_subscription_freezes_days_positive"),
        sa.CheckConstraint("status IN ('applied', 'cancelled')", name="ck_subscription_freezes_status"),
    )
    op.create_index("ix_subscription_freezes_org_subscription", "subscription_freezes", ["organization_id", "subscription_id"])

    op.create_table(
        "payment_refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("payment_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("provider_refund_id", sa.String(100), nullable=True, unique=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["payment_id", "organization_id"], ["payments.id", "payments.organization_id"], name="fk_payment_refunds_payment_org"),
        sa.ForeignKeyConstraint(["recorded_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_payment_refunds_user_org"),
        sa.CheckConstraint("amount > 0", name="ck_payment_refunds_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'processed', 'failed')", name="ck_payment_refunds_status"),
    )
    op.create_index("ix_payment_refunds_org_payment", "payment_refunds", ["organization_id", "payment_id"])

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("event_id", sa.String(150), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_payment_webhook_provider_event"),
    )


def downgrade() -> None:
    op.drop_constraint("ck_membership_plan_rules_transfer_disabled", "membership_plan_rules", type_="check")
    op.drop_table("payment_webhook_events")
    op.drop_index("ix_payment_refunds_org_payment", table_name="payment_refunds")
    op.drop_table("payment_refunds")
    op.drop_index("ix_subscription_freezes_org_subscription", table_name="subscription_freezes")
    op.drop_table("subscription_freezes")
    op.drop_table("membership_tax_settings")
    op.drop_column("invoices", "tax_mode_snapshot")
    op.drop_column("invoices", "gstin_snapshot")
    op.drop_column("invoices", "igst_amount")
    op.drop_column("invoices", "sgst_amount")
    op.drop_column("invoices", "cgst_amount")
    op.drop_column("invoices", "gst_rate")
    op.drop_constraint("uq_payments_provider_payment_id", "payments", type_="unique")
    op.drop_constraint("uq_payments_provider_order_id", "payments", type_="unique")
    op.drop_constraint("uq_payments_id_org", "payments", type_="unique")
    op.drop_column("payments", "provider_payment_id")
    op.drop_column("payments", "provider_order_id")
    op.drop_column("member_subscriptions", "gstin_snapshot")
    op.drop_column("member_subscriptions", "tax_mode_snapshot")
    op.drop_column("member_subscriptions", "gst_rate_snapshot")
    op.drop_constraint("uq_member_subscriptions_razorpay_subscription", "member_subscriptions", type_="unique")
    op.drop_column("member_subscriptions", "razorpay_subscription_id")
    op.drop_column("member_subscriptions", "auto_renew_enabled")
