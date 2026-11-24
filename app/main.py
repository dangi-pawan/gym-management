from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models

from app.db.session import engine, get_db
from app.features.members.router import router as members_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        print("Database connection established successfully!")

        yield

    finally:
        await engine.dispose()
        print("Database connection pool disposed.")


app = FastAPI(
    title="Gym Management SaaS",
    description="Multi-tenant Gym Management Platform",
    version="1.0.0",
    lifespan=lifespan,
)


app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unexpected_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)


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


app.include_router(organizations_router)
app.include_router(gyms_router)
app.include_router(members_router)
app.include_router(auth_router)
