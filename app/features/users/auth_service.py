from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions.base import AppException
from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.features.organizations.models import Organization
from app.features.organizations.service import _slugify, get_organization_by_slug
from app.features.users.models import User
from app.features.users.organization_staff import OrganizationStaff
from app.features.users.sessions import AuthSession, RefreshToken
from app.features.users.service import get_user_by_email


class InvalidCredentialsException(AppException):
    def __init__(self):
        super().__init__(
            message="Invalid organization or login credentials",
            status_code=401,
            error_code="INVALID_CREDENTIALS",
        )


class InvalidRefreshTokenException(AppException):
    def __init__(self):
        super().__init__(
            message="Refresh session is invalid or expired",
            status_code=401,
            error_code="INVALID_REFRESH_TOKEN",
        )


class RegistrationConflictException(AppException):
    def __init__(self):
        super().__init__(
            message="Unable to register this organization",
            status_code=409,
            error_code="REGISTRATION_CONFLICT",
        )


async def _issue_session(
    db: AsyncSession,
    user: User,
) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    refresh_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session = AuthSession(
        user_id=user.id,
        organization_id=user.organization_id,
        expires_at=refresh_expires_at,
    )
    db.add(session)
    await db.flush()

    refresh_token = generate_refresh_token()
    db.add(
        RefreshToken(
            session_id=session.id,
            token_hash=hash_token(refresh_token),
            expires_at=refresh_expires_at,
        )
    )
    access_token, access_expires_at = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        session_id=session.id,
    )
    await db.commit()
    return access_token, refresh_token, access_expires_at


async def register_organization_owner(
    db: AsyncSession,
    *,
    organization_name: str,
    full_name: str,
    email: str,
    password: str,
) -> tuple[User, str, str, datetime]:
    base_slug = _slugify(organization_name)
    existing_result = await db.execute(select(Organization.slug))
    used_slugs = set(existing_result.scalars().all())

    slug = base_slug
    suffix_number = 2
    while slug in used_slugs:
        suffix = f"-{suffix_number}"
        slug = f"{base_slug[:180 - len(suffix)]}{suffix}"
        suffix_number += 1

    organization = Organization(name=organization_name, slug=slug)
    db.add(organization)
    await db.flush()

    user = User(
        organization_id=organization.id,
        full_name=full_name,
        email=email,
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()

    db.add(
        OrganizationStaff(
            user_id=user.id,
            organization_id=organization.id,
            role="owner",
            is_active=True,
        )
    )

    try:
        access, refresh, expires_at = await _issue_session(db, user)
    except Exception:
        await db.rollback()
        raise RegistrationConflictException() from None

    return user, access, refresh, expires_at


async def authenticate_employee(
    db: AsyncSession,
    *,
    organization_slug: str,
    email: str,
    password: str,
) -> tuple[User, str, str, datetime]:
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

    access, refresh, expires_at = await _issue_session(db, user)
    return user, access, refresh, expires_at


async def rotate_refresh_token(
    db: AsyncSession,
    raw_token: str | None,
) -> tuple[str, str, datetime]:
    if not raw_token:
        raise InvalidRefreshTokenException()

    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    stored_token = result.scalar_one_or_none()
    if stored_token is None:
        raise InvalidRefreshTokenException()

    session_result = await db.execute(
        select(AuthSession)
        .where(AuthSession.id == stored_token.session_id)
        .with_for_update()
    )
    session = session_result.scalar_one_or_none()
    if session is None:
        raise InvalidRefreshTokenException()

    if stored_token.used_at is not None:
        session.revoked_at = now
        await db.execute(
            RefreshToken.__table__.update()
            .where(RefreshToken.session_id == session.id)
            .values(revoked_at=now)
        )
        await db.commit()
        raise InvalidRefreshTokenException()

    if (
        stored_token.revoked_at is not None
        or session.revoked_at is not None
        or stored_token.expires_at <= now
        or session.expires_at <= now
    ):
        raise InvalidRefreshTokenException()

    stored_token.used_at = now
    new_raw_token = generate_refresh_token()
    new_expiry = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    session.expires_at = new_expiry
    db.add(
        RefreshToken(
            session_id=session.id,
            token_hash=hash_token(new_raw_token),
            expires_at=new_expiry,
        )
    )

    user_result = await db.execute(
        select(User).where(
            User.id == session.user_id,
            User.organization_id == session.organization_id,
            User.is_active.is_(True),
        )
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        session.revoked_at = now
        await db.commit()
        raise InvalidRefreshTokenException()

    access_token, access_expires_at = create_access_token(
        user_id=user.id,
        organization_id=user.organization_id,
        session_id=session.id,
    )
    await db.commit()
    return access_token, new_raw_token, access_expires_at


async def revoke_refresh_session(
    db: AsyncSession,
    raw_token: str | None,
) -> None:
    if not raw_token:
        return
    result = await db.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == hash_token(raw_token)
        )
    )
    token = result.scalar_one_or_none()
    if token is None:
        return
    now = datetime.now(timezone.utc)
    session_result = await db.execute(
        select(AuthSession).where(AuthSession.id == token.session_id)
    )
    session = session_result.scalar_one_or_none()
    if session is not None:
        session.revoked_at = now
    await db.execute(
        RefreshToken.__table__.update()
        .where(RefreshToken.session_id == token.session_id)
        .values(revoked_at=now)
    )
    await db.commit()


def decode_access_token(raw_token: str) -> dict:
    return jwt.decode(
        raw_token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": ["exp", "iat", "sub", "org_id", "sid", "type"]},
    )
