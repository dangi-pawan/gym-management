import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings


logger = logging.getLogger(__name__)


class EmailConfigurationError(RuntimeError):
    pass


def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    if not settings.SMTP_HOST or not settings.SMTP_FROM_EMAIL:
        if settings.APP_ENV in {"development", "test"}:
            logger.warning(
                "Development email backend: to=%s subject=%s\n%s",
                to_email,
                subject,
                body,
            )
            return
        raise EmailConfigurationError(
            "SMTP_HOST and SMTP_FROM_EMAIL must be configured"
        )

    message = EmailMessage()
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if settings.SMTP_USE_SSL:
        smtp = smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=15,
        )
    else:
        smtp = smtplib.SMTP(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=15,
        )

    with smtp:
        if settings.SMTP_STARTTLS and not settings.SMTP_USE_SSL:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(message)


async def send_email(to_email: str, subject: str, body: str) -> None:
    await asyncio.to_thread(_send_email_sync, to_email, subject, body)
