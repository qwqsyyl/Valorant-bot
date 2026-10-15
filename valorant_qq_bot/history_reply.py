"""Card/text presentation and delivery; no credentials or upstream payloads."""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import json
import os
from pathlib import Path
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from .errors import AuthExpiredError, BindingError, ShopCheckError

logger = logging.getLogger(__name__)
_write_lock = threading.Lock()
ZONE = ZoneInfo('Asia/Shanghai')
HELP = '''战绩查询使用指南
请在机器人所在的群发送：
战绩：查看自己的最近 5 场已结束对局。
战绩 @群友：查看本群已绑定成员的最近 5 场。
查询者和目标均需在本群绑定；结果会发在本群并 @ 查询发起人。
每场显示对局时间、模式、地图、英雄、结果、比分和 K/D/A。
仅支持国服端游战绩，不查询手游角色。
战绩可能存在上游同步延迟；成功结果短暂缓存 60 秒，显示原采集时间。
游戏好友查询请发送「游戏好友帮助」。默认发送战绩图片，生成失败时改用文字。单场详情暂未开放。
再次查看说明：战绩帮助'''
USAGE = '请发送「战绩」查看自己，或发送「战绩」并 @ 一位本群已绑定成员。'


def record_timing(record):
    try:
        path = Path(os.environ.get('VALORANT_HISTORY_TIMING_LOG', 'data/history-response-times.jsonl'))
        path.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            handler = RotatingFileHandler(path, maxBytes=1024*1024, backupCount=1, encoding='utf-8')
            try:
                path.chmod(0o600)
                handler.emit(logging.LogRecord('history_latency', logging.INFO, '', 0,
                                              json.dumps(record), (), None))
                rotated = path.with_name(path.name + '.1')
                if rotated.exists():
                    rotated.chmod(0o600)
            finally:
                handler.close()
    except OSError:
        logger.warning('战绩耗时记录写入失败')


def query_target(argument, mentions, requester, bot_id):
    targets = [str(x) for x in mentions if str(x) != str(bot_id)]
    if argument.strip() or len(targets) > 1 or any(not x.isdecimal() for x in targets):
        raise BindingError(USAGE)
    return targets[0] if targets else requester


def stamp(value):
    return datetime.fromtimestamp(value, ZONE).strftime('%Y-%m-%d %H:%M') if value is not None else '时间未知'


def format_history(history):
    lines = [f'{history.display_name} · 最近 {len(history.matches)} 场战绩']
    if not history.matches:
        lines.append('暂无可查询的已结束战绩。')
    for index, row in enumerate(history.matches, 1):
        number = lambda value: str(value) if value is not None else '?'
        lines.extend([f'{index}. {stamp(row.played_at)} · {row.mode} · {row.map_name} · {row.agent}',
                      f'   {row.result} · {number(row.own_score)}:{number(row.opponent_score)}'
                      f' · K/D/A {number(row.kills)}/{number(row.deaths)}/{number(row.assists)}'])
    lines.append(f'数据采集于：{stamp(history.fetched_at)}（北京时间）')
    return '\n'.join(lines)


def present_history(history):
    if history.matches:
        try:
            from .history_card import render_card
            return 'card', render_card(history)
        except Exception:
            # Presentation failures never change query/authentication state.
            logger.warning('战绩卡片生成失败，本次使用文字回复')
    return 'text', format_history(history)


def error_reply(error):
    if getattr(error, 'reason', None) == 'pc_role_missing':
        return '未找到该账号的国服端游角色。战绩查询仅支持端游，不支持手游。'
    if isinstance(error, AuthExpiredError):
        return '该账号的掌瓦登录已失效，请账号本人发送「瓦绑定 重新授权」更新登录后再查询战绩。'
    if isinstance(error, BindingError):
        return str(error) if str(error) == USAGE else '查询者和目标都需要在本群绑定账号。本人请先发送「瓦绑定」。'
    return '暂时无法获取战绩，请稍后再试。若持续失败，请联系群管理员。'


async def respond_history(app, group, requester, target, send, *, received_at=None):
    started = received_at if received_at is not None else time.perf_counter()
    outcome = 'failed'
    ready = None
    kind, render_ms = 'error_text', 0
    try:
        try:
            result = await asyncio.to_thread(app.query, group, requester, target)
            tick = time.perf_counter()
            kind, content = await asyncio.to_thread(present_history, result)
            render_ms = round((time.perf_counter()-tick)*1000)
            # Membership may have changed while the worker was fetching data.
            await asyncio.to_thread(app.access, group, requester, target, account_key=result.account_key)
            ready = time.perf_counter()
        except ShopCheckError as error:
            kind = 'error_text'
            await send(error_reply(error))
            outcome = 'error_api_accepted'
            return
        await send(content)
        outcome = 'history_api_accepted'
    finally:
        end = time.perf_counter()
        metrics = {'timestamp': datetime.now(ZONE).isoformat(), 'outcome': outcome,
                   'presentation': kind, 'render_ms': render_ms,
                   'ready_ms': round((ready-started)*1000) if ready else None,
                   'send_ms': round((end-ready)*1000) if ready else None,
                   'total_ms': round((end-started)*1000)}
        await asyncio.to_thread(record_timing, metrics)
        logger.info('history_reply outcome=%s ready_ms=%s send_ms=%s total_ms=%s', outcome,
                    round((ready-started)*1000) if ready else None,
                    round((end-ready)*1000) if ready else None, round((end-started)*1000))
