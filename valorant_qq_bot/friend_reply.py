"""Group text queries, always using the initiating member's own account."""
import asyncio
import time
from datetime import datetime
from .errors import AuthExpiredError, BindingError, ShopCheckError
from .history_reply import present_history, record_timing, ZONE

HELP = '''游戏好友战绩使用指南
游戏好友：列出自己账号的端游好友。
游戏好友 昵称关键词：按昵称筛选，最多显示 20 位。
好友战绩 选择码：复制列表中的完整选择码，查询该好友最近 5 场。
例如：好友战绩 A1B2C3-1（请使用实际列表中的选择码）。
选择码仅限你在本群使用，5 分钟内有效；刷新列表、重新授权或重启后需重新获取。
只有查询者需要在本群绑定；目标必须是查询者的游戏好友，无需同群或绑定机器人。
每次实际查询并核对好友关系，不使用旧战绩缓存；仅支持国服端游。
战绩默认发图片，生成失败时改用文字。结果会发在本群并 @ 发起人。再次查看说明：游戏好友帮助'''


def format_friends(selection):
    lines = [f'端游好友共 {selection.total} 位，匹配 {selection.matched} 位']
    for i, friend in enumerate(selection.friends, 1):
        lines.append(f'{selection.code}-{i}  {friend.name}')
    if not selection.friends:
        lines.append('没有匹配的端游好友，可发送「游戏好友」刷新完整列表。')
    elif selection.matched > len(selection.friends):
        lines.append('本次显示前 20 位，请发送「游戏好友 昵称关键词」缩小范围。')
    if selection.friends:
        lines.append(f'发送「好友战绩 {selection.code}-1」查询第 1 位，其他选择码同理。')
    lines.append('选择码 5 分钟内有效，仅限你在本群使用；结果将在本群展示。')
    return '\n'.join(lines)


def error_reply(error):
    reason = getattr(error, 'reason', '')
    replies = {
        'usage': '请先发送「游戏好友 昵称关键词」，再复制列表中的选择码发送「好友战绩 选择码」。此功能使用发起人自己的账号，无需 @ 群友。',
        'selection_expired': '好友选择码已失效，请重新发送「游戏好友 昵称关键词」获取列表。',
        'not_friend': '当前已无法确认这位玩家是你的游戏好友，请重新获取好友列表。',
        'pc_role_missing': '未找到可查询的国服端游角色，仅支持端游好友。',
        'not_visible': '掌瓦暂未允许读取这位好友的战绩，请确认游戏好友关系后稍后重试。',
        'cooldown': '刚才查询暂未成功，请一分钟后再试。',
    }
    if reason in replies:
        return replies[reason]
    if isinstance(error, AuthExpiredError):
        return '你的掌瓦登录已失效，请发送「瓦绑定 重新授权」后重新获取好友列表。'
    if isinstance(error, BindingError):
        return '你需要先在本群发送「瓦绑定」绑定自己的游戏账号，再查询游戏好友。'
    return '暂时无法获取游戏好友或战绩，请稍后重试。'


async def respond_friends(app, group, requester, command, argument, send, *, received_at=None):
    started = received_at if received_at is not None else time.perf_counter()
    ready, outcome = None, 'friend_failed'
    kind, render_ms = 'text', 0
    try:
        try:
            if command == '游戏好友':
                value = await asyncio.to_thread(app.list, group, requester, argument)
                content = format_friends(value)
                await asyncio.to_thread(app.validate_list, group, requester, value)
                outcome = 'friend_list_api_accepted'
            else:
                value = await asyncio.to_thread(app.query, group, requester, argument)
                tick = time.perf_counter()
                kind, content = await asyncio.to_thread(present_history, value.history)
                render_ms = round((time.perf_counter()-tick)*1000)
                await asyncio.to_thread(app.validate_delivery, group, requester, value)
                outcome = 'friend_history_api_accepted'
            ready = time.perf_counter()
        except ShopCheckError as error:
            content, outcome = error_reply(error), 'friend_error_api_accepted'
            kind = 'error_text'
        try:
            await send(content)
        except Exception:
            outcome = 'friend_failed'
            raise
    finally:
        end = time.perf_counter()
        await asyncio.to_thread(record_timing, {'timestamp': datetime.now(ZONE).isoformat(),
            'outcome': outcome, 'presentation': kind, 'render_ms': render_ms, 'ready_ms': round((ready-started)*1000) if ready else None,
            'send_ms': round((end-ready)*1000) if ready else None, 'total_ms': round((end-started)*1000)})
