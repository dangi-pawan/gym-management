import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.common.responses.schemas import APIResponse
from app.core.config import settings
from app.core.email import send_email
from app.core.security import create_csrf_token, hash_password, verify_password
from app.db.session import get_db
from app.features.users.auth_schemas import (
    LoginRequest,
    LoginResponse,
    RefreshResponse,
    RegisterOrganizationRequest,
    PasswordChangeRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    AuthenticatedUserResponse,
    GymRoleInfo,
)
from app.features.users.auth_service import (
    authenticate_employee,
    create_password_reset_token,
    register_organization_owner,
    reset_password_with_token,
    revoke_refresh_session,
    revoke_user_sessions,
    rotate_refresh_token,
)
from app.features.users.dependencies import get_current_user, require_csrf
from app.features.users.models import User
from app.features.users.gym_staff import GymStaff
from app.features.users.organization_staff import OrganizationStaff
from app.features.users.schemas import UserResponse
from app.features.organizations.service import get_organization_by_slug
from app.features.users.service import get_user_by_email


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    csrf_token: str,
) -> None:
    common = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
    }
    response.set_cookie(
        key=settings.ACCESS_TOKEN_COOKIE_NAME,
        value=access_token,
        httponly=True,
        path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **common,
    )
    response.set_cookie(
        key=settings.REFRESH_TOKEN_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        path="/auth",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **common,
    )
    response.set_cookie(
        key=settings.CSRF_TOKEN_COOKIE_NAME,
        value=csrf_token,
        httponly=False,
        path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    common = {
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
    }
    response.delete_cookie(settings.ACCESS_TOKEN_COOKIE_NAME, path="/", **common)
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE_NAME, path="/auth", **common)
    response.delete_cookie(settings.CSRF_TOKEN_COOKIE_NAME, path="/", **common)


def _login_response(
    response: Response,
    access_token: str,
    refresh_token: str,
    expires_at,
):
    csrf_token = create_csrf_token()
    _set_auth_cookies(response, access_token, refresh_token, csrf_token)
    return success_response(
        message="Authentication successful",
        data=LoginResponse(
            csrf_token=csrf_token,
            access_expires_at=expires_at,
        ),
    )


@router.post("/register", response_model=APIResponse[LoginResponse])
async def register_organization(
    registration: RegisterOrganizationRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _user, access_token, refresh_token, expires_at = await register_organization_owner(
        db,
        organization_name=registration.organization_name,
        full_name=registration.full_name,
        email=str(registration.email),
        password=registration.password,
    )
    return _login_response(
        response, access_token, refresh_token, expires_at
    )


@router.post("/login", response_model=APIResponse[LoginResponse])
async def login(
    credentials: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    _user, access_token, refresh_token, expires_at = await authenticate_employee(
        db,
        organization_slug=credentials.organization_slug,
        email=str(credentials.email),
        password=credentials.password,
    )
    return _login_response(
        response, access_token, refresh_token, expires_at
    )


@router.post(
    "/refresh",
    response_model=APIResponse[RefreshResponse],
    dependencies=[Depends(require_csrf)],
)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    try:
        access_token, refresh_token, expires_at = await rotate_refresh_token(
            db,
            request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME),
        )
    except Exception:
        _clear_auth_cookies(response)
        raise
    csrf_token = create_csrf_token()
    _set_auth_cookies(response, access_token, refresh_token, csrf_token)
    return success_response(
        message="Session refreshed successfully",
        data=RefreshResponse(
            csrf_token=csrf_token,
            access_expires_at=expires_at,
        ),
    )


@router.post(
    "/logout",
    response_model=APIResponse[None],
    dependencies=[Depends(require_csrf)],
)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    await revoke_refresh_session(
        db,
        request.cookies.get(settings.REFRESH_TOKEN_COOKIE_NAME),
    )
    _clear_auth_cookies(response)
    return success_response(message="Logged out successfully")





@router.post("/forgot-password", response_model=APIResponse[None])
async def forgot_password(
    request_data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        raise HTTPException(
            status_code=503,
            detail="Password reset email delivery is not configured",
        )

    organization = await get_organization_by_slug(
        db, request_data.organization_slug
    )
    if organization is not None:
        user = await get_user_by_email(
            db, organization.id, str(request_data.email)
        )
        if user is not None and user.is_active:
            raw_token = await create_password_reset_token(db, user.id)
            try:
                await send_email(
                    str(user.email),
                    "Gym Management password reset",
                    (
                        "A password reset was requested for your account.\n\n"
                        f"One-time reset token: {raw_token}\n\n"
                        "Submit this token to POST /auth/reset-password in the API "
                        "documentation. It expires in 30 minutes. If you did not "
                        "request this, ignore this email."
                    ),
                )
            except Exception:
                logger.exception("Password reset email delivery failed")

    return success_response(
        message="If the account exists, password reset instructions have been sent."
    )


@router.post("/reset-password", response_model=APIResponse[None])
async def reset_password(
    reset_data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    await reset_password_with_token(
        db,
        raw_token=reset_data.token,
        new_password=reset_data.new_password,
    )
    return success_response(
        message="Password reset successfully. Please sign in again."
    )

@router.post("/change-password", response_model=APIResponse[None])
async def change_password(
    password_data: PasswordChangeRequest,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect",
        )
    current_user.password_hash = hash_password(password_data.new_password)
    await revoke_user_sessions(db, current_user.id)
    _clear_auth_cookies(response)
    return success_response(
        message="Password changed. Please sign in again.",
    )

@router.post("/logout-all", response_model=APIResponse[None])
async def logout_all_sessions(
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    await revoke_user_sessions(db, current_user.id)
    _clear_auth_cookies(response)
    return success_response(message="All sessions have been revoked")


@router.get("/me", response_model=APIResponse[AuthenticatedUserResponse])
async def get_authenticated_employee(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    organization_role_result = await db.execute(
        select(OrganizationStaff.role).where(
            OrganizationStaff.user_id == current_user.id,
            OrganizationStaff.organization_id == current_user.organization_id,
            OrganizationStaff.is_active.is_(True),
        )
    )
    gym_roles_result = await db.execute(
        select(GymStaff.gym_id, GymStaff.role).where(
            GymStaff.user_id == current_user.id,
            GymStaff.organization_id == current_user.organization_id,
            GymStaff.is_active.is_(True),
        ).order_by(GymStaff.gym_id)
    )
    return success_response(
        message="Authenticated employee fetched successfully",
        data=AuthenticatedUserResponse(
            user=UserResponse.model_validate(current_user).model_dump(),
            organization_role=organization_role_result.scalar_one_or_none(),
            gym_roles=[
                GymRoleInfo(gym_id=gym_id, role=role)
                for gym_id, role in gym_roles_result.all()
            ],
        ),
    )
