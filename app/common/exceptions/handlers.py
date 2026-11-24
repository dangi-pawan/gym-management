import logging

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

from fastapi.exceptions import RequestValidationError

from app.common.exceptions.base import AppException

logger = logging.getLogger(__name__)


async def app_exception_handler(
    request: Request,
    exc: AppException
):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "error": {
                "code": exc.error_code,
                "details": exc.details
            }
        }
    )


async def unexpected_exception_handler(
    request: Request,
    exc: Exception
):
    logger.exception(
        "Unhandled exception occurred: %s %s",
        request.method,
        request.url.path
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "An unexpected error occurred",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "details": None
            }
        }
    )



async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError
):
    errors = [
        {
            "field": ".".join(str(item) for item in error["loc"][1:]),
            "message": error["msg"],
            "type": error["type"]
        }
        for error in exc.errors()
    ]

    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed",
            "error": {
                "code": "VALIDATION_ERROR",
                "details": errors
            }
        }
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "success": False,
            "message": str(exc.detail),
            "error": {
                "code": "HTTP_ERROR",
                "details": None
            }
        },
    )
