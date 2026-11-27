from redis.asyncio import Redis

from app.core.config import settings


def create_redis_client() -> Redis:
    return Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
    )


async def check_redis_connection(redis_client: Redis) -> None:
    await redis_client.ping()


async def close_redis_client(redis_client: Redis) -> None:
    await redis_client.aclose()
