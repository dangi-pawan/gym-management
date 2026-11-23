
"""add organizations and gym organization relationship

Revision ID: 9a927abb80b8
Revises: d6a4008a4d32
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9a927abb80b8"
down_revision: Union[str, Sequence[str], None] = "d6a4008a4d32"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
    )

    op.add_column(
        "gyms",
        sa.Column("organization_id", sa.Integer(), nullable=True),
    )

    op.create_index(
        "ix_gyms_organization_id",
        "gyms",
        ["organization_id"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_gyms_organization_id_organizations",
        "gyms",
        "organizations",
        ["organization_id"],
        ["id"],
    )

    bind = op.get_bind()

    gym_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM gyms")
    ).scalar_one()

    if gym_count:
        organization_id = bind.execute(
            sa.text(
                "INSERT INTO organizations (name) "
                "VALUES (:name) RETURNING id"
            ),
            {"name": "Migrated Organization"},
        ).scalar_one()

        bind.execute(
            sa.text(
                "UPDATE gyms SET organization_id = :organization_id"
            ),
            {"organization_id": organization_id},
        )

    op.alter_column(
        "gyms",
        "organization_id",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_gyms_organization_id_organizations",
        "gyms",
        type_="foreignkey",
    )

    op.drop_index("ix_gyms_organization_id", table_name="gyms")
    op.drop_column("gyms", "organization_id")
    op.drop_table("organizations")
