"""Idempotent expiry job for active memberships.

Run periodically from cron or a scheduler:
    ENV_FILE=.env python3 -m scripts.expire_memberships
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.features.gyms.models import Gym
from app.features.memberships.models import MemberSubscription


async def expire_memberships() -> int:
    expired_count = 0
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(MemberSubscription, Gym.timezone)
            .join(Gym, Gym.id == MemberSubscription.purchased_at_gym_id)
            .where(MemberSubscription.status == "active")
        )
        for subscription, timezone_name in result.all():
            local_today = datetime.now(ZoneInfo(timezone_name)).date()
            if subscription.end_date <= local_today:
                subscription.status = "expired"
                expired_count += 1
        if expired_count:
            await db.commit()
    return expired_count


async def main() -> None:
    try:
        count = await expire_memberships()
        print(f"Expired {count} membership subscription(s).")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
