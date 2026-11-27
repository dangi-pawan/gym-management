from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from prometheus_client import make_asgi_app
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from redis.exceptions import RedisError

import app.db.models

from app.db.session import engine, get_db
from app.core.config import settings
from app.core.metrics import PrometheusMetricsMiddleware
from app.core.redis import (
    check_redis_connection,
    close_redis_client,
    create_redis_client,
)
from app.features.members.router import router as members_router
from app.features.memberships.router import router as memberships_router
from app.features.gyms.router import router as gyms_router

from app.common.exceptions.base import AppException
from app.common.exceptions.handlers import (
    app_exception_handler,
    unexpected_exception_handler,
    validation_exception_handler,
    http_exception_handler,
)

from app.features.organizations.router import router as organizations_router
from app.features.users.auth_router import router as auth_router
from app.features.users.router import router as users_router
from app.features.users.staff_router import router as gym_staff_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = None
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        print("Database connection established successfully!")

        redis_client = create_redis_client()
        await check_redis_connection(redis_client)
        app.state.redis = redis_client
        print("Redis connection established successfully!")

        yield

    finally:
        app.state.redis = None
        try:
            if redis_client is not None:
                await close_redis_client(redis_client)
                print("Redis connection closed.")
        finally:
            await engine.dispose()
            print("Database connection pool disposed.")


app = FastAPI(
    title="Gym Management SaaS",
    description="Multi-tenant Gym Management Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)

# Keep metrics middleware outside the application middleware stack so that
# handled errors and responses are measured consistently.
app.add_middleware(PrometheusMetricsMiddleware)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unexpected_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)

# Prometheus scrapes this ASGI application. Scrape requests are excluded
# from application request metrics by PrometheusMetricsMiddleware.
app.mount("/metrics", make_asgi_app())


@app.get("/")
async def root():
    return {"message": "Welcome to Gym Management SaaS"}


@app.get("/health/database")
async def database_health(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(text("SELECT 1"))
    return {
        "database": "connected",
        "result": result.scalar(),
    }


@app.get("/health/redis")
async def redis_health(request: Request):
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Redis is unavailable")

    try:
        await check_redis_connection(redis_client)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis is unavailable") from exc

    return {"redis": "connected"}


app.include_router(organizations_router)
app.include_router(gyms_router)
app.include_router(members_router)
app.include_router(memberships_router)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(gym_staff_router)
