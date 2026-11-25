"""complete auth verification, invitation, rate limits and session lifetime

Revision ID: c92d4f8a61b3
Revises: 8c1f3a7d5e20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c92d4f8a61b3"
down_revision: Union[str, Sequence[str], None] = "8c1f3a7d5e20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing accounts predate email verification; preserve their access.
    op.execute(
        "UPDATE users SET email_verified_at = now() WHERE email_verified_at IS NULL"
    )
    op.add_column(
        "auth_sessions",
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE auth_sessions SET absolute_expires_at = expires_at "
        "WHERE absolute_expires_at IS NULL"
    )
    op.alter_column("auth_sessions", "absolute_expires_at", nullable=False)

    for table_name in ("email_verification_tokens", "employee_invitation_tokens"):
        columns = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        ]
        if table_name == "employee_invitation_tokens":
            columns.insert(3, sa.Column("organization_role", sa.String(length=30), nullable=True))
        op.create_table(
            table_name,
            *columns,
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("token_hash", name=f"uq_{table_name}_token_hash"),
        )
        op.create_index(
            f"ix_{table_name}_user_id", table_name, ["user_id"]
        )

    op.create_table(
        "auth_rate_limits",
        sa.Column("key_hash", sa.String(length=64), primary_key=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("auth_rate_limits")
    for table_name in ("employee_invitation_tokens", "email_verification_tokens"):
        op.drop_index(f"ix_{table_name}_user_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_column("auth_sessions", "absolute_expires_at")
    op.drop_column("users", "email_verified_at")
