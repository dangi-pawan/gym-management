"""Minimal async Razorpay REST client with signature verification.

No payment is considered successful from a browser redirect. Only a verified
Razorpay webhook (or a server-side verified payment fetch) may activate access.
"""
import hashlib
import hmac
from typing import Any

import httpx

from app.core.config import settings


class RazorpayConfigurationError(RuntimeError):
    pass


class RazorpayError(RuntimeError):
    pass


def _credentials() -> tuple[str, str]:
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise RazorpayConfigurationError("Razorpay credentials are not configured")
    return settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    _, secret = _credentials()
    message = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not secret:
        raise RazorpayConfigurationError("Razorpay webhook secret is not configured")
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    credentials = _credentials()
    url = f"{settings.RAZORPAY_API_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        response = await client.request(
            method,
            url,
            auth=credentials,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
    if response.is_error:
        raise RazorpayError(f"Razorpay request failed with HTTP {response.status_code}")
    return response.json()


async def create_order(amount_paise: int, currency: str, receipt: str, notes: dict[str, str]) -> dict[str, Any]:
    if amount_paise <= 0:
        raise ValueError("Razorpay order amount must be positive")
    return await _request("POST", "/orders", {
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt[:40],
        "notes": notes,
    })


async def create_refund(payment_id: str, amount_paise: int, notes: dict[str, str]) -> dict[str, Any]:
    if amount_paise <= 0:
        raise ValueError("Refund amount must be positive")
    return await _request("POST", f"/payments/{payment_id}/refund", {
        "amount": amount_paise,
        "notes": notes,
    })
