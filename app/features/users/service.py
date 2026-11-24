
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.features.users.models import User
from app.features.users.schemas import UserCreate


async def get_user_by_email(
    db: AsyncSession,
    organization_id: int,
    email: str,
) -> User | None:
    result = await db.execute(
        select(User).where(
            User.organization_id == organization_id,
            User.email == email,
        )
    )

    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    organization_id: int,
    user_data: UserCreate,
) -> User | None:
    # Check whether this email already exists in this organization.
    existing_user = await get_user_by_email(
        db,
        organization_id,
        str(user_data.email),
    )

    if existing_user is not None:
        return None

    new_user = User(
        organization_id=organization_id,
        full_name=user_data.full_name,
        email=str(user_data.email),
        password_hash=hash_password(user_data.password),
    )

    db.add(new_user)

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise

    await db.refresh(new_user)

    return new_user
