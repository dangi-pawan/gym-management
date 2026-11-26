"""add organization-owned members and membership management domain

Revision ID: e41b7c9d2a60
Revises: c92d4f8a61b3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e41b7c9d2a60"
down_revision: Union[str, Sequence[str], None] = "c92d4f8a61b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Gym-local dates are evaluated in this configured IANA timezone.
    op.add_column(
        "gyms",
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Kolkata", nullable=False),
    )

    # Expand/backfill/contract: preserve existing member IDs and gym links.
    op.add_column("members", sa.Column("organization_id", sa.Integer(), nullable=True))
    op.execute(
        """
        UPDATE members
        SET organization_id = gyms.organization_id
        FROM gyms
        WHERE members.gym_id = gyms.id
          AND members.organization_id IS NULL
        """
    )
    op.alter_column("members", "organization_id", nullable=False)
    op.create_foreign_key(
        "fk_members_organization_id_organizations",
        "members",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_members_id_organization", "members", ["id", "organization_id"]
    )
    op.create_foreign_key(
        "fk_members_gym_organization",
        "members",
        "gyms",
        ["gym_id", "organization_id"],
        ["id", "organization_id"],
    )
    op.create_index("ix_members_organization_id", "members", ["organization_id"])

    op.create_table(
        "membership_terms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_membership_terms_organization"),
        sa.ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_membership_terms_creator_org",
        ),
        sa.UniqueConstraint("organization_id", "version", name="uq_membership_terms_org_version"),
        sa.CheckConstraint("version > 0", name="ck_membership_terms_version_positive"),
        sa.CheckConstraint("status IN ('draft', 'published', 'retired')", name="ck_membership_terms_status"),
    )

    op.create_table(
        "membership_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("duration_value", sa.Integer(), nullable=False),
        sa.Column("duration_unit", sa.String(10), nullable=False),
        sa.Column("base_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("joining_fee", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(3), server_default="INR", nullable=False),
        sa.Column("access_type", sa.String(20), nullable=False),
        sa.Column("terms_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_membership_plans_organization"),
        sa.ForeignKeyConstraint(["terms_id"], ["membership_terms.id"], name="fk_membership_plans_terms"),
        sa.ForeignKeyConstraint(
            ["created_by", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_membership_plans_creator_org",
        ),
        sa.UniqueConstraint("id", "organization_id", name="uq_membership_plans_id_org"),
        sa.CheckConstraint("duration_value > 0", name="ck_membership_plans_duration_positive"),
        sa.CheckConstraint("base_price >= 0", name="ck_membership_plans_price_nonnegative"),
        sa.CheckConstraint("joining_fee >= 0", name="ck_membership_plans_joining_fee_nonnegative"),
        sa.CheckConstraint("duration_unit IN ('day', 'week', 'month', 'year')", name="ck_membership_plans_duration_unit"),
        sa.CheckConstraint("access_type IN ('home_gym', 'all_gyms', 'selected_gyms')", name="ck_membership_plans_access_type"),
        sa.CheckConstraint("status IN ('draft', 'active', 'archived')", name="ck_membership_plans_status"),
    )
    op.create_index("ix_membership_plans_org_status", "membership_plans", ["organization_id", "status"])

    op.create_table(
        "gym_membership_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("membership_plan_id", sa.Integer(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("price_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("joining_fee_override", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_gym_membership_plans_organization"),
        sa.ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_gym_membership_plans_gym_org"),
        sa.ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_gym_membership_plans_plan_org"),
        sa.UniqueConstraint("gym_id", "membership_plan_id", name="uq_gym_membership_plans_gym_plan"),
        sa.CheckConstraint("price_override IS NULL OR price_override >= 0", name="ck_gym_membership_plans_price_nonnegative"),
        sa.CheckConstraint("joining_fee_override IS NULL OR joining_fee_override >= 0", name="ck_gym_membership_plans_fee_nonnegative"),
    )

    op.create_table(
        "membership_plan_access_gyms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("membership_plan_id", sa.Integer(), nullable=False),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_membership_plan_access_gyms_organization"),
        sa.ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_membership_plan_access_plan_org"),
        sa.ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_membership_plan_access_gym_org"),
        sa.UniqueConstraint("membership_plan_id", "gym_id", name="uq_membership_plan_access_plan_gym"),
    )

    op.create_table(
        "membership_plan_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("membership_plan_id", sa.Integer(), nullable=False),
        sa.Column("freeze_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("max_freeze_days", sa.Integer(), nullable=True),
        sa.Column("transfer_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cancellation_allowed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("refund_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("auto_renew_allowed", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["membership_plan_id"], ["membership_plans.id"], ondelete="CASCADE", name="fk_membership_plan_rules_plan"),
        sa.UniqueConstraint("membership_plan_id", name="uq_membership_plan_rules_membership_plan_id"),
        sa.CheckConstraint("max_freeze_days IS NULL OR max_freeze_days >= 0", name="ck_membership_plan_rules_freeze_days_nonnegative"),
        sa.CheckConstraint("freeze_allowed OR max_freeze_days IS NULL OR max_freeze_days = 0", name="ck_membership_plan_rules_freeze_disabled"),
    )

    op.create_table(
        "member_gym_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_member_gym_assignments_organization"),
        sa.ForeignKeyConstraint(["member_id", "organization_id"], ["members.id", "members.organization_id"], name="fk_member_gym_assignments_member_org"),
        sa.ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_member_gym_assignments_gym_org"),
        sa.UniqueConstraint("member_id", "gym_id", name="uq_member_gym_assignments_member_gym"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_member_gym_assignments_status"),
    )
    op.create_index(
        "uq_member_gym_assignments_primary_active",
        "member_gym_assignments",
        ["member_id"],
        unique=True,
        postgresql_where=sa.text("is_primary IS TRUE AND status = 'active'"),
    )
    op.execute(
        """
        INSERT INTO member_gym_assignments
            (organization_id, member_id, gym_id, is_primary, status)
        SELECT organization_id, id, gym_id, true, 'active'
        FROM members
        """
    )

    op.create_table(
        "member_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("membership_plan_id", sa.Integer(), nullable=False),
        sa.Column("purchased_at_gym_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending_payment", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("plan_name_snapshot", sa.String(100), nullable=False),
        sa.Column("duration_value_snapshot", sa.Integer(), nullable=False),
        sa.Column("duration_unit_snapshot", sa.String(10), nullable=False),
        sa.Column("plan_price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("joining_fee_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency_snapshot", sa.String(3), nullable=False),
        sa.Column("access_type_snapshot", sa.String(20), nullable=False),
        sa.Column("rules_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_member_subscriptions_organization"),
        sa.ForeignKeyConstraint(["member_id", "organization_id"], ["members.id", "members.organization_id"], name="fk_member_subscriptions_member_org"),
        sa.ForeignKeyConstraint(["membership_plan_id", "organization_id"], ["membership_plans.id", "membership_plans.organization_id"], name="fk_member_subscriptions_plan_org"),
        sa.ForeignKeyConstraint(["purchased_at_gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_member_subscriptions_gym_org"),
        sa.ForeignKeyConstraint(["created_by", "organization_id"], ["users.id", "users.organization_id"], name="fk_member_subscriptions_creator_org"),
        sa.UniqueConstraint("id", "organization_id", name="uq_member_subscriptions_id_org"),
        sa.CheckConstraint("status IN ('pending_payment', 'active', 'expired', 'cancelled')", name="ck_member_subscriptions_status"),
        sa.CheckConstraint("end_date > start_date", name="ck_member_subscriptions_date_range"),
        sa.CheckConstraint("plan_price_snapshot >= 0 AND joining_fee_snapshot >= 0", name="ck_member_subscriptions_prices_nonnegative"),
    )
    op.create_index("ix_member_subscriptions_org_member", "member_subscriptions", ["organization_id", "member_id"])

    op.create_table(
        "subscription_access_gyms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("gym_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_subscription_access_gyms_organization"),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_access_subscription_org"),
        sa.ForeignKeyConstraint(["gym_id", "organization_id"], ["gyms.id", "gyms.organization_id"], name="fk_subscription_access_gym_org"),
        sa.UniqueConstraint("subscription_id", "gym_id", name="uq_subscription_access_subscription_gym"),
    )

    op.create_table(
        "subscription_terms_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("membership_terms_id", sa.Integer(), nullable=False),
        sa.Column("terms_version_snapshot", sa.Integer(), nullable=False),
        sa.Column("terms_content_hash_snapshot", sa.String(64), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_by_member_id", sa.Integer(), nullable=True),
        sa.Column("acceptance_method", sa.String(30), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_subscription_terms_acceptances_organization"),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_subscription_terms_subscription_org"),
        sa.ForeignKeyConstraint(["membership_terms_id"], ["membership_terms.id"], name="fk_subscription_terms_acceptances_terms"),
        sa.ForeignKeyConstraint(["accepted_by_member_id"], ["members.id"], name="fk_subscription_terms_acceptances_member"),
        sa.UniqueConstraint("subscription_id", name="uq_subscription_terms_acceptances_subscription"),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_method", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), server_default="manual", nullable=False),
        sa.Column("provider_reference", sa.String(150), nullable=True),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("recorded_by", sa.Integer(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_payments_organization"),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_payments_subscription_org"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], name="fk_payments_recorded_by_user"),
        sa.CheckConstraint("amount > 0", name="ck_payments_amount_positive"),
        sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed', 'refunded', 'partially_refunded')", name="ck_payments_status"),
    )
    op.create_index("ix_payments_org_subscription", "payments", ["organization_id", "subscription_id"])
    op.create_index(
        "uq_payments_provider_reference",
        "payments",
        ["provider", "provider_reference"],
        unique=True,
        postgresql_where=sa.text("provider_reference IS NOT NULL"),
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_invoices_organization"),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_invoices_subscription_org"),
        sa.UniqueConstraint("organization_id", "invoice_number", name="uq_invoices_org_number"),
        sa.CheckConstraint("subtotal >= 0 AND tax_amount >= 0 AND total_amount >= 0", name="ck_invoices_amounts_nonnegative"),
        sa.CheckConstraint("status IN ('draft', 'issued', 'void')", name="ck_invoices_status"),
    )

    op.create_table(
        "membership_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name="fk_membership_documents_organization"),
        sa.ForeignKeyConstraint(["subscription_id", "organization_id"], ["member_subscriptions.id", "member_subscriptions.organization_id"], name="fk_membership_documents_subscription_org"),
        sa.UniqueConstraint("storage_key", name="uq_membership_documents_storage_key"),
        sa.CheckConstraint("document_type IN ('agreement', 'invoice', 'receipt', 'other')", name="ck_membership_documents_type"),
    )


def downgrade() -> None:
    op.drop_table("membership_documents")
    op.drop_table("invoices")
    op.drop_index("uq_payments_provider_reference", table_name="payments")
    op.drop_index("ix_payments_org_subscription", table_name="payments")
    op.drop_table("payments")
    op.drop_table("subscription_terms_acceptances")
    op.drop_table("subscription_access_gyms")
    op.drop_index("ix_member_subscriptions_org_member", table_name="member_subscriptions")
    op.drop_table("member_subscriptions")
    op.drop_index("uq_member_gym_assignments_primary_active", table_name="member_gym_assignments")
    op.drop_table("member_gym_assignments")
    op.drop_table("membership_plan_rules")
    op.drop_table("membership_plan_access_gyms")
    op.drop_table("gym_membership_plans")
    op.drop_index("ix_membership_plans_org_status", table_name="membership_plans")
    op.drop_table("membership_plans")
    op.drop_table("membership_terms")
    op.drop_index("ix_members_organization_id", table_name="members")
    op.drop_constraint("fk_members_gym_organization", "members", type_="foreignkey")
    op.drop_constraint("uq_members_id_organization", "members", type_="unique")
    op.drop_constraint("fk_members_organization_id_organizations", "members", type_="foreignkey")
    op.drop_column("members", "organization_id")
    op.drop_column("gyms", "timezone")
