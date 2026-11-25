"""add organization-level staff roles

Revision ID: 7b6c2a9d1e4f
Revises: 4a8f2c91d6e3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7b6c2a9d1e4f"
down_revision: Union[str, Sequence[str], None] = "4a8f2c91d6e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organization_staff",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_organization_staff_user_org",
        ),
        sa.UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_organization_staff_user_org",
        ),
    )
    op.create_index(
        "ix_organization_staff_organization_id",
        "organization_staff",
        ["organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_organization_staff_organization_id",
        table_name="organization_staff",
    )
    op.drop_table("organization_staff")
