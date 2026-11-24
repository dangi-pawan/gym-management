from datetime import datetime, timezone
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
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


async def require_csrf(
    request: Request,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> None:
    valid = verify_csrf_token(
        request.cookies.get(settings.CSRF_TOKEN_COOKIE_NAME),
        csrf_header,
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF validation failed",
        )


async def get_current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
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

    now = datetime.now(timezone.utc)
    session_result = await db.execute(
        select(AuthSession).where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.organization_id == organization_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    if session_result.scalar_one_or_none() is None:
        raise _unauthorized()

    if request.method not in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        await require_csrf(request, csrf_header)

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
