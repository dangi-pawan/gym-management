from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.features.users.models import User


bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Validate an access token and return its active organization user."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "org_id", "type"]},
        )
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    if payload.get("type") != "access":
        raise _unauthorized()

    try:
        user_id = int(payload["sub"])
        organization_id = int(payload["org_id"])
    except (TypeError, ValueError):
        raise _unauthorized() from None

    result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
        )
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise _unauthorized()

    return user
