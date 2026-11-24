from __future__ import annotations

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base




class Organization(Base):
    __tablename__ = "organizations"

    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(180),
        nullable=False,
    )

    gyms: Mapped[list["Gym"]] = relationship(
        back_populates="organization"
    )