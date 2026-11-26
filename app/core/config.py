import os
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str

    JWT_SECRET_KEY: str = Field(min_length=32)
    CSRF_SECRET_KEY: str | None = Field(default=None, min_length=32)
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=15, gt=0, le=1440)
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=14, gt=0, le=30)
    REFRESH_TOKEN_MAX_DAYS: int = Field(default=30, gt=0, le=90)
    LOGIN_MAX_ATTEMPTS: int = Field(default=5, gt=0, le=20)
    LOGIN_IP_MAX_ATTEMPTS: int = Field(default=50, gt=0, le=500)
    LOGIN_RATE_LIMIT_MINUTES: int = Field(default=15, gt=0, le=1440)
    PASSWORD_RESET_MAX_REQUESTS: int = Field(default=3, gt=0, le=20)
    PASSWORD_RESET_IP_MAX_REQUESTS: int = Field(default=20, gt=0, le=200)
    PASSWORD_RESET_RATE_LIMIT_MINUTES: int = Field(default=60, gt=0, le=1440)
    EMPLOYEE_INVITATION_MAX_PER_HOUR: int = Field(default=20, gt=0, le=200)
    APP_ENV: Literal["development", "test", "production"] = "development"

    ACCESS_TOKEN_COOKIE_NAME: str = "access_token"
    REFRESH_TOKEN_COOKIE_NAME: str = "refresh_token"
    CSRF_TOKEN_COOKIE_NAME: str = "csrf_token"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    COOKIE_DOMAIN: str | None = None
    CORS_ORIGINS: list[str] = Field(default_factory=list)

    SMTP_HOST: str | None = None
    SMTP_PORT: int = Field(default=587, gt=0, le=65535)
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str | None = None
    SMTP_STARTTLS: bool = True
    SMTP_USE_SSL: bool = False

    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    MEMBERSHIP_DOCUMENTS_DIR: str = ".private/membership-documents"

    # Razorpay credentials are intentionally optional for local/test environments.
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_KEY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None
    RAZORPAY_API_BASE_URL: str = "https://api.razorpay.com/v1"

    # S3-compatible private object storage. If no bucket is configured, local
    # private storage remains available for development and tests.
    MEMBERSHIP_S3_BUCKET: str | None = None
    MEMBERSHIP_S3_REGION: str = "ap-south-1"
    MEMBERSHIP_S3_ENDPOINT_URL: str | None = None
    MEMBERSHIP_S3_ACCESS_KEY_ID: str | None = None
    MEMBERSHIP_S3_SECRET_ACCESS_KEY: str | None = None
    MEMBERSHIP_S3_PREFIX: str = "membership-documents"

    # GST is configured at organization level in the membership tax settings table.
    MEMBERSHIP_DEFAULT_GST_RATE: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)

    @model_validator(mode="after")
    def validate_cookie_settings(self):
        if self.COOKIE_SAMESITE == "none" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SECURE must be true when COOKIE_SAMESITE is 'none'")
        if self.APP_ENV == "production" and not self.COOKIE_SECURE:
            raise ValueError("COOKIE_SECURE must be true in production")
        if self.APP_ENV == "production" and not self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must be configured in production")
        if self.REFRESH_TOKEN_MAX_DAYS < self.REFRESH_TOKEN_EXPIRE_DAYS:
            raise ValueError("REFRESH_TOKEN_MAX_DAYS must be >= REFRESH_TOKEN_EXPIRE_DAYS")
        if self.APP_ENV == "production" and not self.MEMBERSHIP_S3_BUCKET:
            raise ValueError("MEMBERSHIP_S3_BUCKET must be configured in production")
        if self.APP_ENV == "production" and not self.RAZORPAY_WEBHOOK_SECRET:
            raise ValueError("RAZORPAY_WEBHOOK_SECRET must be configured in production")
        if self.APP_ENV == "production" and not self.RAZORPAY_KEY_ID:
            raise ValueError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured in production")
        if bool(self.MEMBERSHIP_S3_ACCESS_KEY_ID) != bool(self.MEMBERSHIP_S3_SECRET_ACCESS_KEY):
            raise ValueError("S3 access key ID and secret access key must be configured together")
        if bool(self.RAZORPAY_KEY_ID) != bool(self.RAZORPAY_KEY_SECRET):
            raise ValueError("RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET must be configured together")
        return self

    model_config = SettingsConfigDict(
        env_file=os.getenv("ENV_FILE", ".env"),
        extra="ignore",
    )


settings = Settings()
