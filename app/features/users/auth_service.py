import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import and_, case, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
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
from app.features.users.password_reset import PasswordResetToken
from app.features.users.account_tokens import (
    AuthRateLimit,
    EmailVerificationToken,
    EmployeeInvitationToken,
)
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


class InvalidPasswordResetTokenException(AppException):
    def __init__(self):
        super().__init__(
            message="Password reset token is invalid or expired",
            status_code=400,
            error_code="INVALID_PASSWORD_RESET_TOKEN",
        )


class AuthenticationRateLimitException(AppException):
    def __init__(self):
        super().__init__(
            message="Too many attempts. Please try again later.",
            status_code=429,
            error_code="AUTH_RATE_LIMITED",
        )


class InvalidActionTokenException(AppException):
    def __init__(self):
        super().__init__(
            message="The action token is invalid or expired",
            status_code=400,
            error_code="INVALID_ACTION_TOKEN",
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
    absolute_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_MAX_DAYS)
    session = AuthSession(
        user_id=user.id,
        organization_id=user.organization_id,
        expires_at=refresh_expires_at,
        absolute_expires_at=absolute_expires_at,
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
) -> User:
    base_slug = _slugify(organization_name)
    existing_result = await db.execute(select(Organization.slug))
    used_slugs = set(existing_result.scalars().all())
    slug = base_slug
    suffix_number = 2
    while slug in used_slugs:
        suffix = f"-{suffix_number}"
        slug = f"{base_slug[:180 - len(suffix)]}{suffix}"
        suffix_number += 1
    try:
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
        db.add(OrganizationStaff(
            user_id=user.id,
            organization_id=organization.id,
            role="owner",
            is_active=True,
        ))
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise RegistrationConflictException() from None
    return user


async def authenticate_employee(
    db: AsyncSession,
    *,
    organization_slug: str,
    email: str,
    password: str,
    client_ip: str,
) -> tuple[User, str, str, datetime]:
    rate_key = f"login:{client_ip}:{organization_slug}:{email}"
    organization = await get_organization_by_slug(db, organization_slug)
    if organization is None:
        verify_password(password, _DUMMY_PASSWORD_HASH)
        if await increment_auth_rate_limit(
            db,
            key=rate_key,
            max_attempts=settings.LOGIN_MAX_ATTEMPTS,
            window_minutes=settings.LOGIN_RATE_LIMIT_MINUTES,
        ):
            raise AuthenticationRateLimitException()
        raise InvalidCredentialsException()

    user = await get_user_by_email(db, organization.id, email)
    password_valid = verify_password(
        password,
        user.password_hash if user is not None else _DUMMY_PASSWORD_HASH,
    )
    if (
        user is None
        or not user.is_active
        or user.email_verified_at is None
        or not password_valid
    ):
        if await increment_auth_rate_limit(
            db,
            key=rate_key,
            max_attempts=settings.LOGIN_MAX_ATTEMPTS,
            window_minutes=settings.LOGIN_RATE_LIMIT_MINUTES,
        ):
            raise AuthenticationRateLimitException()
        raise InvalidCredentialsException()

    await clear_auth_rate_limit(db, key=rate_key)
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
    new_expiry = min(
        now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        session.absolute_expires_at,
    )
    if new_expiry <= now:
        session.revoked_at = now
        await db.commit()
        raise InvalidRefreshTokenException()
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


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: int,
) -> None:
    now = datetime.now(timezone.utc)
    session_ids = select(AuthSession.id).where(AuthSession.user_id == user_id)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id.in_(session_ids))
        .values(revoked_at=now)
    )
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()


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


async def create_password_reset_token(
    db: AsyncSession,
    user_id: int,
) -> str:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    db.add(
        PasswordResetToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(minutes=30),
        )
    )
    await db.commit()
    return raw_token


async def reset_password_with_token(
    db: AsyncSession,
    *,
    raw_token: str,
    new_password: str,
) -> None:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordResetToken)
        .where(PasswordResetToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    token = result.scalar_one_or_none()
    if (
        token is None
        or token.used_at is not None
        or token.expires_at <= now
    ):
        raise InvalidPasswordResetTokenException()

    user_result = await db.execute(
        select(User).where(User.id == token.user_id, User.is_active.is_(True))
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise InvalidPasswordResetTokenException()

    token.used_at = now
    user.password_hash = hash_password(new_password)
    session_ids = select(AuthSession.id).where(AuthSession.user_id == user.id)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id.in_(session_ids))
        .values(revoked_at=now)
    )
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    await db.commit()


# A fixed Argon2 hash keeps unknown-user login attempts close to the same
# verification cost as known-user attempts.
_DUMMY_PASSWORD_HASH = hash_password("dummy-authentication-password-not-for-use")


def _rate_limit_hash(key: str) -> str:
    return hashlib.sha256(
        f"{settings.JWT_SECRET_KEY}:{key}".encode("utf-8")
    ).hexdigest()


async def increment_auth_rate_limit(
    db: AsyncSession,
    *,
    key: str,
    max_attempts: int,
    window_minutes: int,
) -> bool:
    """Atomically count an attempt in PostgreSQL; return True when blocked."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=window_minutes)
    blocked_until = now + timedelta(minutes=window_minutes)
    key_hash = _rate_limit_hash(key)
    statement = (
        pg_insert(AuthRateLimit)
        .values(
            key_hash=key_hash,
            window_started_at=now,
            attempts=1,
            blocked_until=None,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[AuthRateLimit.key_hash],
            set_={
                "attempts": case(
                    (AuthRateLimit.window_started_at <= cutoff, 1),
                    else_=AuthRateLimit.attempts + 1,
                ),
                "window_started_at": case(
                    (AuthRateLimit.window_started_at <= cutoff, now),
                    else_=AuthRateLimit.window_started_at,
                ),
                "blocked_until": case(
                    (AuthRateLimit.blocked_until > now, AuthRateLimit.blocked_until),
                    (
                        and_(
                            AuthRateLimit.window_started_at > cutoff,
                            AuthRateLimit.attempts >= max_attempts,
                        ),
                        blocked_until,
                    ),
                    else_=AuthRateLimit.blocked_until,
                ),
                "updated_at": now,
            },
        )
        .returning(AuthRateLimit.blocked_until)
    )
    result = await db.execute(statement)
    blocked = result.scalar_one_or_none()
    await db.commit()
    return blocked is not None and blocked > now


async def clear_auth_rate_limit(db: AsyncSession, *, key: str) -> None:
    await db.execute(
        delete(AuthRateLimit).where(
            AuthRateLimit.key_hash == _rate_limit_hash(key)
        )
    )
    await db.commit()


async def create_email_verification_token(
    db: AsyncSession,
    user_id: int,
) -> str:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user_id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    db.add(
        EmailVerificationToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            expires_at=now + timedelta(hours=24),
        )
    )
    await db.commit()
    return raw_token


async def verify_email_and_issue_session(
    db: AsyncSession,
    raw_token: str,
) -> tuple[User, str, str, datetime]:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    token = result.scalar_one_or_none()
    if token is None or token.used_at is not None or token.expires_at <= now:
        raise InvalidActionTokenException()

    user_result = await db.execute(
        select(User).where(
            User.id == token.user_id,
            User.is_active.is_(True),
        ).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise InvalidActionTokenException()

    token.used_at = now
    user.email_verified_at = now
    access, refresh, expires_at = await _issue_session(db, user)
    return user, access, refresh, expires_at


async def create_employee_invitation(
    db: AsyncSession,
    *,
    organization_id: int,
    full_name: str,
    email: str,
    organization_role: str | None,
) -> tuple[User, str]:
    existing = await get_user_by_email(db, organization_id, email)
    if existing is not None:
        raise RegistrationConflictException()

    # The unusable random password is replaced only when the invite is accepted.
    user = User(
        organization_id=organization_id,
        full_name=full_name,
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        is_active=False,
    )
    db.add(user)
    await db.flush()
    raw_token = secrets.token_urlsafe(48)
    db.add(
        EmployeeInvitationToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            organization_role=organization_role,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        )
    )
    await db.commit()
    await db.refresh(user)
    return user, raw_token


async def accept_employee_invitation(
    db: AsyncSession,
    *,
    raw_token: str,
    password: str,
) -> User:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(EmployeeInvitationToken)
        .where(EmployeeInvitationToken.token_hash == hash_token(raw_token))
        .with_for_update()
    )
    invitation = result.scalar_one_or_none()
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.expires_at <= now
    ):
        raise InvalidActionTokenException()

    user_result = await db.execute(
        select(User).where(
            User.id == invitation.user_id,
            User.is_active.is_(False),
        ).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise InvalidActionTokenException()

    invitation.used_at = now
    user.password_hash = hash_password(password)
    user.is_active = True
    user.email_verified_at = now

    if invitation.organization_role == "admin":
        db.add(
            OrganizationStaff(
                user_id=user.id,
                organization_id=user.organization_id,
                role="admin",
                is_active=True,
            )
        )

    await db.commit()
    await db.refresh(user)
    return user


async def resend_employee_invitation(
    db: AsyncSession,
    *,
    organization_id: int,
    user_id: int,
) -> tuple[User, str, str | None]:
    now = datetime.now(timezone.utc)
    user_result = await db.execute(
        select(User).where(
            User.id == user_id,
            User.organization_id == organization_id,
            User.is_active.is_(False),
            User.email_verified_at.is_(None),
        ).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise InvalidActionTokenException()

    token_result = await db.execute(
        select(EmployeeInvitationToken)
        .where(EmployeeInvitationToken.user_id == user_id)
        .order_by(EmployeeInvitationToken.id.desc())
        .limit(1)
        .with_for_update()
    )
    previous = token_result.scalar_one_or_none()
    if previous is None or previous.used_at is not None:
        raise InvalidActionTokenException()

    organization_role = previous.organization_role
    await db.execute(
        update(EmployeeInvitationToken)
        .where(
            EmployeeInvitationToken.user_id == user_id,
            EmployeeInvitationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw_token = secrets.token_urlsafe(48)
    db.add(
        EmployeeInvitationToken(
            user_id=user_id,
            token_hash=hash_token(raw_token),
            organization_role=organization_role,
            expires_at=now + timedelta(hours=48),
        )
    )
    await db.commit()
    return user, raw_token, organization_role
