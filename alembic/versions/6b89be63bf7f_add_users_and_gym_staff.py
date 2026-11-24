
"""add users and gym staff

Revision ID: 6b89be63bf7f
Revises: 9a927abb80b8
Create Date: 2026-11-23 19:05:49.820062
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b89be63bf7f"
down_revision: Union[str, Sequence[str], None] = "9a927abb80b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Create users table.
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_users_id_organization",
        ),
        sa.UniqueConstraint(
            "organization_id",
            "email",
            name="uq_users_organization_email",
        ),
    )

    # 2. Create users organization index.
    op.create_index(
        op.f("ix_users_organization_id"),
        "users",
        ["organization_id"],
        unique=False,
    )

    # 3. Add composite unique constraint to gyms BEFORE
    # creating the gym_staff foreign key.
    op.create_unique_constraint(
        "uq_gyms_id_organization",
        "gyms",
        ["id", "organization_id"],
    )

    # 4. Create gym_staff table.
    op.create_table(
        "gym_staff",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gym_id", sa.Integer(), nullable=False),
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
            ["gym_id", "organization_id"],
            ["gyms.id", "gyms.organization_id"],
            name="fk_gym_staff_gym_organization",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_gym_staff_user_organization",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "gym_id",
            name="uq_gym_staff_user_gym",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop gym_staff first because it references gyms and users.
    op.drop_table("gym_staff")

    # Remove the composite unique constraint from gyms.
    op.drop_constraint(
        "uq_gyms_id_organization",
        "gyms",
        type_="unique",
    )

    # Remove users index and table.
    op.drop_index(
        op.f("ix_users_organization_id"),
        table_name="users",
    )
    op.drop_table("users")
