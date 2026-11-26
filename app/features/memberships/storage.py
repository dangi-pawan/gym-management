"""Private membership document storage.

S3-compatible storage is used whenever MEMBERSHIP_S3_BUCKET is configured.
Local private storage is retained for development/test only.
"""
import asyncio
import os
from pathlib import Path, PurePosixPath
from typing import Any

import boto3
from botocore.config import Config

from app.core.config import settings


def _s3_client():
    if not settings.MEMBERSHIP_S3_BUCKET:
        raise RuntimeError("Private S3 storage is not configured")
    kwargs: dict[str, Any] = {
        "region_name": settings.MEMBERSHIP_S3_REGION,
        "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    }
    if settings.MEMBERSHIP_S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.MEMBERSHIP_S3_ENDPOINT_URL
    if settings.MEMBERSHIP_S3_ACCESS_KEY_ID:
        kwargs["aws_access_key_id"] = settings.MEMBERSHIP_S3_ACCESS_KEY_ID
        kwargs["aws_secret_access_key"] = settings.MEMBERSHIP_S3_SECRET_ACCESS_KEY
    return boto3.client("s3", **kwargs)


def _safe_key(key: str) -> str:
    relative = PurePosixPath(key)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("Invalid private document storage key")
    return str(relative)


def upload_private_object(key: str, content: bytes, content_type: str) -> None:
    safe_key = _safe_key(key)
    _s3_client().put_object(
        Bucket=settings.MEMBERSHIP_S3_BUCKET,
        Key=f"{settings.MEMBERSHIP_S3_PREFIX.strip('/')}/{safe_key}",
        Body=content,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )


def download_private_object(key: str) -> bytes:
    safe_key = _safe_key(key)
    response = _s3_client().get_object(
        Bucket=settings.MEMBERSHIP_S3_BUCKET,
        Key=f"{settings.MEMBERSHIP_S3_PREFIX.strip('/')}/{safe_key}",
    )
    return response["Body"].read()


def delete_private_object(key: str) -> None:
    safe_key = _safe_key(key)
    _s3_client().delete_object(
        Bucket=settings.MEMBERSHIP_S3_BUCKET,
        Key=f"{settings.MEMBERSHIP_S3_PREFIX.strip('/')}/{safe_key}",
    )


def private_local_path(key: str) -> Path:
    relative = PurePosixPath(_safe_key(key))
    root = Path(settings.MEMBERSHIP_DOCUMENTS_DIR).expanduser().resolve()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root):
        raise ValueError("Invalid private document storage key")
    return target
