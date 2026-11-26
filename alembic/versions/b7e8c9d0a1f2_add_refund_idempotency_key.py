"""Persist provider idempotency keys for safe refund retries.

Revision ID: b7e8c9d0a1f2
Revises: 9d4c2e7a1b63
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e8c9d0a1f2"
down_revision: Union[str, Sequence[str], None] = "9d4c2e7a1b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "payment_refunds",
        sa.Column("idempotency_key", sa.String(length=36), nullable=True),
    )
    op.execute(
        "UPDATE payment_refunds "
        "SET idempotency_key = gen_random_uuid()::text "
        "WHERE idempotency_key IS NULL"
    )
    op.alter_column("payment_refunds", "idempotency_key", nullable=False)
    op.create_unique_constraint(
        "uq_payment_refunds_idempotency_key",
        "payment_refunds",
        ["idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_payment_refunds_idempotency_key",
        "payment_refunds",
        type_="unique",
    )
    op.drop_column("payment_refunds", "idempotency_key")
