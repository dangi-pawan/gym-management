from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses.helpers import success_response
from app.common.responses.schemas import APIResponse
from app.db.session import get_db
from app.features.users.auth_schemas import LoginRequest, TokenResponse
from app.features.users.auth_service import authenticate_employee


router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/login",
    response_model=APIResponse[TokenResponse],
)
async def login(
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    access_token, expires_at = await authenticate_employee(
        db,
        organization_slug=credentials.organization_slug,
        email=str(credentials.email),
        password=credentials.password,
    )

    return success_response(
        message="Login successful",
        data=TokenResponse(
            access_token=access_token,
            expires_at=expires_at,
        ),
    )
