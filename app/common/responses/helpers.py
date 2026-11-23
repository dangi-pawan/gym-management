from typing import Any

from app.common.responses.schemas import APIResponse


def success_response(
    message: str,
    data: Any = None,
) -> APIResponse:
    return APIResponse(
        success=True,
        message=message,
        data=data,
    )