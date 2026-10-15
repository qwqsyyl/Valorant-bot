"""Daily collection and durable outbox delivery, without protocol-specific fetches."""
import asyncio
from datetime import datetime, timedelta
import logging
import time
from zoneinfo import ZoneInfo
from .errors import ShopCheckError, DeliveryRejected

logger = logging.getLogger(__name__)

def next_check(now, hour=8, minute=0):
    local = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai'))
    target = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return target.timestamp()

def next_collection(app, group, now, hour=8, minute=0):
    for member in app.repository.members(group):
        if app.needs_reauthorization(member['account_key']):
            continue
        shop = app.repository.snapshot(member['account_key'])
        if not app.cached_shop_is_current(shop, now):
            return now + 60
    return next_check(now, hour, minute)

async def collect(app, group):
    members = await asyncio.to_thread(app.repository.members, group)
    for member in members:
        if app.needs_reauthorization(member['account_key']):
            continue
        try:
            # The shared service skips successful accounts, including after restart.
            await asyncio.to_thread(app.query, group, member['qq_id'])
        except ShopCheckError:
            logger.warning('每日商店采集未完成；一分钟后重试，登录失效需本人重新授权')

async def deliver(app, group, sender):
    batch = await asyncio.to_thread(app.repository.claim, group)
    if not batch:
        return
    ids = [item['id'] for item in batch]
    try:
        await sender(batch)
    except DeliveryRejected:
        await asyncio.to_thread(app.repository.finish, ids, 'pending')
        logger.warning('商店提醒被明确拒绝，最多重试三次')
    except asyncio.CancelledError:
        await asyncio.to_thread(app.repository.finish, ids, 'unknown')
        raise
    except Exception:
        # Timeout/connection loss can mean delivered but acknowledgement lost.
        await asyncio.to_thread(app.repository.finish, ids, 'unknown')
        logger.warning('商店提醒发送结果不确定，已保留记录供检查')
    else:
        await asyncio.to_thread(app.repository.finish, ids, 'sent')

async def run(app, group, sender, *, hour=8, minute=0):
    await asyncio.to_thread(app.repository.recover_interrupted)
    due = 0.0 # Startup catch-up; only registered real accounts are collected.
    while True:
        if time.time() >= due:
            await collect(app, group)
            due = await asyncio.to_thread(next_collection, app, group, time.time(), hour, minute)
        await deliver(app, group, sender)
        await asyncio.sleep(max(0, min(30, due-time.time())))
