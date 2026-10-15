"""One timed shop request; send callback acknowledges OneBot API acceptance."""
import asyncio
from datetime import datetime
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import threading
import time
import uuid
from zoneinfo import ZoneInfo
from .errors import ShopCheckError
from .shop_images import load_offer_images
from .shop_card import render_card, shop_text

_write_lock=threading.Lock()


def record_timing(record):
    try:
        path=Path(os.environ.get('VALORANT_SHOP_TIMING_LOG','data/shop-response-times.jsonl'))
        path.parent.mkdir(parents=True,exist_ok=True)
        with _write_lock:
            handler=RotatingFileHandler(path,maxBytes=1024*1024,backupCount=1,encoding='utf-8')
            try:
                path.chmod(0o600)
                handler.emit(logging.LogRecord('shop_latency',logging.INFO,'',0,
                             json.dumps(record,ensure_ascii=False),(),None))
                rotated=path.with_name(path.name+'.1')
                if rotated.exists(): rotated.chmod(0o600)
            finally:
                handler.close()
    except OSError:
        logging.getLogger(__name__).warning('商店耗时记录写入失败')


async def respond_shop(app, group, qq, target, send, *, received_at=None, delivery_scope='onebot_api'):
    start=received_at if received_at is not None else time.perf_counter()
    metrics={'timestamp':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),
             'request_id':uuid.uuid4().hex[:12], 'outcome':'error',
             'background_mode':'local_random', 'delivery':'not_sent', 'delivery_scope':delivery_scope}
    def elapsed(stamp): return round((time.perf_counter()-stamp)*1000,2)
    try:
        tick=time.perf_counter()
        shop=await asyncio.to_thread(app.query,group,qq,target)
        member=await asyncio.to_thread(app.repository.require_member,group,target)
        metrics['shop_ms']=elapsed(tick)
        async def skins():
            tick=time.perf_counter()
            try:
                return await asyncio.to_thread(load_offer_images,shop.offers)
            finally:
                metrics['skin_images_ms']=elapsed(tick)
        render_started=None
        try:
            images=await skins()
            render_started=time.perf_counter()
            card=await asyncio.to_thread(render_card,shop,member['display_name'],images)
            kind,content='card',card
        except (ShopCheckError,ImportError,OSError):
            kind,content='text',shop_text(shop,member['display_name'])
        metrics['render_ms']=elapsed(render_started) if render_started is not None else 0
        metrics['card_ready_ms']=elapsed(start)
        metrics['outcome']=kind
        tick=time.perf_counter()
        try:
            await send(kind,content)
            metrics['delivery']='api_accepted' if delivery_scope == 'onebot_api' else 'sink_accepted'
        except Exception:
            metrics['delivery']='failed_or_unknown'
            raise
        finally:
            metrics['send_ms']=elapsed(tick)
        return metrics
    finally:
        metrics['total_ms']=elapsed(start)
        await asyncio.to_thread(record_timing,metrics)
