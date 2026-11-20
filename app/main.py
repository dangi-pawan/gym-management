from contextlib import asynccontextmanager

from fastapi import FastAPI , Depends
from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession

import app.db.models

from app.db.session import engine , get_db
from app.features.members.router import router as members_router
from app.features.gyms.router import router as gyms_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        # Verify database connectivity during startup
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

        print("Database connection established successfully!")

        yield

    finally:
        # Clean up database connection pool during shutdown
        await engine.dispose()
        print("Database connection pool disposed.")


app = FastAPI(
    title="Gym Management SaaS",
    description="Multi-tenant Gym Management Platform",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Gym Management SaaS"
    }


@app.get("/health/database")
async def database_health(
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(text("SELECT 1"))

    return {
        "database": "connected",
        "result": result.scalar()
    }


app.include_router(members_router)
app.include_router(gyms_router)