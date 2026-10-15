"""Authentication maintenance has its own clock, independent of QQ and shops."""
import asyncio
import logging
from .errors import ShopCheckError

logger = logging.getLogger(__name__)


async def maintain_round(app, group):
    members = await asyncio.to_thread(app.repository.members, group)
    seen = set()
    for member in members:
        key = member['account_key']
        if key in seen:
            continue
        seen.add(key)
        try:
            await asyncio.to_thread(app.maintain_login, group, member['qq_id'])
        except ShopCheckError:
            pass  # The core persists the stage, result code and retry deadline.
        except Exception as error:
            logger.warning('登录维护异常 qq=%s type=%s', member['qq_id'], type(error).__name__)


async def run(app, group, *, interval=300):
    while True:
        await maintain_round(app, group)
        await asyncio.sleep(interval)
