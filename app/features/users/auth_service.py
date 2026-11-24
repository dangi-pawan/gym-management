from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions.base import AppException
from app.core.security import create_access_token, verify_password
from app.features.organizations.service import get_organization_by_slug
from app.features.users.service import get_user_by_email


class InvalidCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            message="Invalid organization or login credentials",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )


async def authenticate_employee(
    db: AsyncSession,
    *,
    organization_slug: str,
    email: str,
    password: str,
) -> tuple[str, datetime]:
    organization = await get_organization_by_slug(db, organization_slug)
    if organization is None:
        raise InvalidCredentialsException()

    user = await get_user_by_email(db, organization.id, email)
    if (
        user is None
        or not user.is_active
        or not verify_password(password, user.password_hash)
    ):
        raise InvalidCredentialsException()

    access_token, expires_at = create_access_token(
        user_id=user.id,
        organization_id=organization.id,
    )
    return access_token, expires_at
