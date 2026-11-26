from unittest.mock import AsyncMock, Mock

import pytest

from app.core import redis as redis_module
from app.core.config import settings


def test_create_redis_client_uses_configured_url(monkeypatch):
    fake_client = Mock()
    from_url = Mock(return_value=fake_client)
    monkeypatch.setattr(redis_module.Redis, "from_url", from_url)

    client = redis_module.create_redis_client()

    assert client is fake_client
    from_url.assert_called_once_with(
        settings.REDIS_URL,
        decode_responses=True,
    )


@pytest.mark.asyncio
async def test_check_redis_connection_pings_client():
    redis_client = Mock()
    redis_client.ping = AsyncMock(return_value=True)

    await redis_module.check_redis_connection(redis_client)

    redis_client.ping.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_close_redis_client_closes_connection():
    redis_client = Mock()
    redis_client.aclose = AsyncMock()

    await redis_module.close_redis_client(redis_client)

    redis_client.aclose.assert_awaited_once_with()
