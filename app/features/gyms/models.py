from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Gym(Base):
    __tablename__ = "gyms"

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", name="fk_gyms_organization_id_organizations"),
        nullable=False,
        index=True,
    )

    organization: Mapped["Organization"] = relationship(
        back_populates="gyms"
    )

    members: Mapped[list["Member"]] = relationship(
        back_populates="gym",
        foreign_keys="Member.gym_id",
    )

    __table_args__ = (
    UniqueConstraint(
        "id",
        "organization_id",
        name="uq_gyms_id_organization",
    ),
    )