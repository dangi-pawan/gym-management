import logging

import pytest

from app.core.config import settings
from app.core.email import EmailConfigurationError, send_email


@pytest.mark.asyncio
async def test_development_email_backend_logs_email_when_smtp_is_missing(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(settings, "APP_ENV", "development")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", None)

    with caplog.at_level(logging.WARNING, logger="app.core.email"):
        await send_email(
            "owner@example.test",
            "Verify your account",
            "Verification token: local-test-token",
        )

    assert "owner@example.test" in caplog.text
    assert "Verification token: local-test-token" in caplog.text


@pytest.mark.asyncio
async def test_production_email_backend_rejects_missing_smtp(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "SMTP_FROM_EMAIL", None)

    with pytest.raises(EmailConfigurationError):
        await send_email(
            "owner@example.test",
            "Verify your account",
            "Verification token: production-token",
        )
