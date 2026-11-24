from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GymStaff(Base):
    __tablename__ = "gym_staff"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "gym_id",
            name="uq_gym_staff_user_gym",
        ),
        ForeignKeyConstraint(
            ["user_id", "organization_id"],
            ["users.id", "users.organization_id"],
            name="fk_gym_staff_user_organization",
        ),
        ForeignKeyConstraint(
            ["gym_id", "organization_id"],
            ["gyms.id", "gyms.organization_id"],
            name="fk_gym_staff_gym_organization",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False)
    gym_id: Mapped[int] = mapped_column(nullable=False)
    organization_id: Mapped[int] = mapped_column(nullable=False)

    role: Mapped[str] = mapped_column(String(30), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )