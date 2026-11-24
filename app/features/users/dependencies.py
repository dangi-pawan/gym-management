from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import verify_csrf_token
from app.db.session import get_db
from app.features.users.auth_service import decode_access_token
from app.features.users.models import User
from app.features.users.sessions import AuthSession


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
    )


async def require_csrf(request: Request) -> None:
    valid = verify_csrf_token(
        request.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME),
        request.headers.get("X-CSRF-Token"),
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    raw_token = request.cookies.get(settings.ACCESS_TOKEN_COOKIE_NAME)
    if not raw_token:
        raise _unauthorized()

    try:
        payload: dict[str, Any] = decode_access_token(raw_token)
    except jwt.InvalidTokenError:
        raise _unauthorized() from None

    if payload.get("type") != "access":
        raise _unauthorized()

    try:
        user_id = int(payload["sub"])
        organization_id = int(payload["org_id"])
        session_id = int(payload["sid"])
    except (TypeError, ValueError):
        raise _unauthorized() from None

    session_result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.organization_id == organization_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        )
    )
    auth_session = session_result.scalar_one_or_none()
    if auth_session is None:
        raise _unauthorized()

    if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        await require_csrf(request)

    user_result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.is_active.is_(True),
        )
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise _unauthorized()
    return user
