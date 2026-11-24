from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings


password_hasher = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plain-text password using the recommended algorithm."""
    return password_hasher.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Verify a plain-text password against its stored hash."""
    return password_hasher.verify(plain_password, hashed_password)


def create_access_token(
    *,
    user_id: int,
    organization_id: int,
) -> tuple[str, datetime]:
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    now = datetime.now(timezone.utc)

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": organization_id,
        "iat": now,
        "exp": expires_at,
        "type": "access",
    }

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token, expires_at
