from __future__ import annotations

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.features.gyms.models import Gym
from app.features.organizations.models import Organization


class Member(Base):
    __tablename__ = "members"

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_members_id_organization"),
        ForeignKeyConstraint(
            ["gym_id", "organization_id"],
            ["gyms.id", "gyms.organization_id"],
            name="fk_members_gym_organization",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    gym_id: Mapped[int] = mapped_column(
        ForeignKey("gyms.id"),
        nullable=False,
        index=True,
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)

    gym: Mapped[Gym] = relationship(
        back_populates="members",
        foreign_keys=[gym_id],
    )
    organization: Mapped[Organization] = relationship()
