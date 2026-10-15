"""Single-group QQ adapter; event identity is the only binding authority."""
import asyncio
import os
import time
from collections import defaultdict
from nonebot import get_driver, on_message
from nonebot.log import logger
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment, GroupMessageEvent, PrivateMessageEvent, ActionFailed
from .errors import ShopCheckError, DeliveryRejected
from .mval_client import HttpClient, fetch_role_name
from .qq_shop_auth import create_qq_qr, complete_qq_login
from .group_binding import GroupBinding
from .login_channels import CHANNELS, parse_binding_arguments
from .qq_reply import addressed_message
from .shop_runtime import application
from .shop_response import respond_shop
from .history_runtime import application as history_application
from .history_reply import HELP as HISTORY_HELP, query_target, respond_history
from .friend_runtime import application as friend_application
from .friend_reply import HELP as FRIEND_HELP, respond_friends, error_reply as friend_error_reply
from .friend_provider import FriendError
from .shop_scheduler import run
from .login_maintenance import run as run_login_maintenance
from . import bot_messages as copy

matcher = on_message(priority=20, block=False)
_task = None
_login_task = None
_bindings = GroupBinding(client_factory=HttpClient, create_qr=create_qq_qr,
    login=complete_qq_login, role_name=fetch_role_name,
    authorize=lambda *args: application().authorize(*args),
    lookup_binding=lambda group, qq: application().repository.member(group, qq),
    channels=CHANNELS, lookup_channel=lambda group, qq: application().binding_channel(group, qq))

def accepts_bot(bot):
    expected = os.environ.get('VALORANT_BOT_QQ')
    return not expected or bot.self_id == expected

def configured_group():
    group = os.environ.get('VALORANT_GROUP_ID', '')
    return group if group.isdecimal() else None

async def check_member(bot, group, qq):
    await bot.get_group_member_info(group_id=int(group), user_id=int(qq), no_cache=True)

async def reply(event, content):
    await matcher.send(addressed_message(str(event.user_id), content,
                                         group=isinstance(event, GroupMessageEvent)))

async def bind(bot, event, group, qq, *, renew=False, channel=None):
    async def emit(content):
        await bot.send_group_msg(group_id=int(group), message=addressed_message(qq, content))
    await _bindings.begin(group, qq, member=lambda: check_member(bot, group, qq), emit=emit, renew=renew, channel=channel)

@matcher.handle()
async def handle(bot: Bot, event: GroupMessageEvent | PrivateMessageEvent):
    received_at = time.perf_counter()
    group = configured_group()
    if not group or not accepts_bot(bot):
        return
    text = event.get_plaintext().strip()
    command, _, argument = text.partition(' ')
    commands = {'瓦绑定','取消绑定','每日商店','商店解绑','皮肤提醒','取消提醒','愿望单','商店帮助','战绩','战绩帮助','游戏好友','好友战绩','游戏好友帮助'}
    if command not in commands:
        return
    if isinstance(event, GroupMessageEvent) and str(event.group_id) != group:
        return
    qq = str(event.user_id)
    try:
        if command == '商店帮助':
            await reply(event, copy.HELP)
        elif command == '战绩帮助':
            await reply(event, HISTORY_HELP)
        elif command == '游戏好友帮助':
            await reply(event, FRIEND_HELP)
        elif command == '瓦绑定':
            if isinstance(event, GroupMessageEvent):
                try:
                    channel, renew = parse_binding_arguments(argument)
                except ShopCheckError:
                    await reply(event, copy.BIND_USAGE)
                    return
                await bind(bot, event, group, qq, renew=renew, channel=channel)
            else:
                await reply(event, copy.PRIVATE_BIND)
        elif isinstance(event, PrivateMessageEvent):
            await reply(event, copy.PRIVATE_COMMAND)
        elif command == '取消绑定':
            _bindings.cancel(group, qq)
            await reply(event, copy.CANCELLED)
        else:
            app = application()
            if command in {'游戏好友', '好友战绩'}:
                mentions = [str(seg.data.get('qq')) for seg in event.message if seg.type == 'at']
                if any(x != str(bot.self_id) for x in mentions):
                    await reply(event, friend_error_reply(FriendError('usage')))
                    return
                async def send_friend(content):
                    await reply(event, content)
                await respond_friends(friend_application(), group, qq, command, argument, send_friend, received_at=received_at)
            elif command == '战绩':
                mentions = [str(seg.data.get('qq')) for seg in event.message if seg.type == 'at']
                try:
                    target = query_target(argument, mentions, qq, bot.self_id)
                except ShopCheckError as error:
                    await reply(event, str(error))
                    return
                async def send_history(content):
                    await reply(event, content)
                await respond_history(history_application(), group, qq, target, send_history, received_at=received_at)
            elif command == '每日商店':
                targets = [str(seg.data.get('qq')) for seg in event.message if seg.type == 'at' and str(seg.data.get('qq')).isdecimal() and str(seg.data.get('qq')) != bot.self_id]
                if len(targets) > 1:
                    await reply(event, copy.ONE_TARGET)
                    return
                target = targets[0] if targets else qq
                async def send_result(kind, content):
                    await reply(event, MessageSegment.image(content) if kind == 'card' else content)
                await respond_shop(app, group, qq, target, send_result, received_at=received_at)
            elif command == '商店解绑':
                _bindings.cancel_if_active(group, qq)
                final = await asyncio.to_thread(app.unlink, group, qq)
                friend_application().invalidate(group, qq)
                await reply(event, copy.unlinked(final))
            elif command == '皮肤提醒':
                await asyncio.to_thread(app.add_wish, group, qq, argument)
                snapshot = app.repository.snapshot(app.repository.require_member(group, qq)['account_key'])
                await reply(event, copy.reminder_added(argument.strip(), enabled=bool(snapshot and snapshot.cycle)))
            elif command == '愿望单':
                wishes = await asyncio.to_thread(app.repository.wishes, group, qq)
                await reply(event, copy.wishlist(wishes))
            elif command == '取消提醒':
                wishes = await asyncio.to_thread(app.repository.wishes, group, qq)
                if not argument.isdecimal() or not 1 <= int(argument) <= len(wishes):
                    await reply(event, copy.REMINDER_NUMBER)
                    return
                await asyncio.to_thread(app.repository.remove_wish, group, qq, wishes[int(argument)-1].key)
                await reply(event, copy.reminder_removed(wishes[int(argument)-1].name))
    except ShopCheckError as error:
        await reply(event, copy.error_reply(error))
    except Exception:
        logger.warning('群命令操作未完成：{}', command)
        await reply(event, copy.OPERATION_FAILED)

@get_driver().on_startup
async def start_login_maintenance():
    global _login_task
    group = configured_group()
    if group and (_login_task is None or _login_task.done()):
        _login_task = asyncio.create_task(run_login_maintenance(application(), group))
        logger.info('独立登录维护已启动：每五分钟检查到期账号，与商店缓存和 QQ 连接状态无关')

@get_driver().on_bot_connect
async def connected(bot: Bot):
    global _task
    group = configured_group()
    if not group or not accepts_bot(bot) or (_task and not _task.done()):
        return
    try:
        status = await asyncio.wait_for(bot.get_status(), timeout=6)
        logger.info('QQ 接入状态：online={} good={}', status.get('online'), status.get('good'))
    except Exception:
        logger.warning('QQ 接入状态请求未完成；连接建立不代表 QQ 客户端可用')
    async def sender(batch):
        messages = defaultdict(list)
        for row in batch:
            messages[row['qq_id']].append(row['name'])
        message = Message(copy.WISH_NOTICE)
        for qq, names in messages.items():
            await check_member(bot, group, qq)
            message += MessageSegment.at(qq) + MessageSegment.text('\n' + '\n'.join(names) + '\n')
        message += MessageSegment.text(copy.WISH_NOTICE_FOOTER)
        try:
            await bot.send_group_msg(group_id=int(group), message=message)
        except ActionFailed:
            raise DeliveryRejected('QQ 接入端明确拒绝发送') from None
    app = application()
    hour = app.provider.reset_hour if app.provider.reset_hour is not None else 8
    logger.info('商店采集策略：北京时间 {:02d}:00；失败一分钟后重试；成功保存至下一商店周期', hour)
    _task = asyncio.create_task(run(app, group, sender, hour=hour))

@get_driver().on_bot_disconnect
async def disconnected(bot: Bot):
    global _task
    if not accepts_bot(bot):
        return
    _bindings.close()
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None

@get_driver().on_shutdown
async def shutdown():
    _bindings.close()
    if _login_task:
        _login_task.cancel()
        try:
            await _login_task
        except asyncio.CancelledError:
            pass
    if _task:
        _task.cancel()
