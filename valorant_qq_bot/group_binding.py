"""Group QR flow; chat identity is supplied only by the QQ adapter.

A successful scan is verified against the real shop before persistent storage.
Candidate credentials are kept in memory until validation completes.
"""
import asyncio
from dataclasses import dataclass, field
from threading import Event
from .errors import ShopCheckError
from . import bot_messages as copy


@dataclass
class Request:
    cancelled: Event = field(default_factory=Event)
    state: str = 'scanning'


class GroupBinding:
    def __init__(self, *, client_factory, create_qr, login, role_name, authorize, lookup_binding, limit=16, channels=None, lookup_channel=None):
        self.client_factory, self.create_qr, self.login = client_factory, create_qr, login
        self.role_name, self.authorize = role_name, authorize
        self.lookup_binding = lookup_binding
        self.limit = limit
        self.channels = channels or {}
        self.lookup_channel = lookup_channel
        self.requests = {}

    def _release(self, key, request):
        request.cancelled.set()
        if self.requests.get(key) is request:
            del self.requests[key]

    async def begin(self, group, qq, *, member, emit, renew=False, channel=None):
        key = (group, qq)
        if key in self.requests:
            if self.requests[key].cancelled.is_set():
                raise ShopCheckError('上一次扫码正在结束，请稍后再发送「瓦绑定」。')
            raise ShopCheckError('已有绑定任务，请先扫码或等待超时。也可发送「取消绑定」。')
        if len(self.requests) >= self.limit:
            raise ShopCheckError('当前扫码人数较多，请两分钟后重试。')
        request = Request()
        self.requests[key] = request
        session, account = {}, {}
        retry = '瓦绑定 重新授权' if renew else '瓦绑定'
        try:
            await member()
            bound = await asyncio.to_thread(self.lookup_binding, group, qq)
            if bound and not renew:
                role = bound.get('display_name') or '未识别角色'
                await emit(copy.already_bound(role))
                return
            if channel is None and renew and self.lookup_channel:
                channel = await asyncio.to_thread(self.lookup_channel, group, qq)
            channel = channel or 'qq'
            selected = self.channels.get(channel)
            if channel != 'qq' and selected is None:
                raise ShopCheckError('不支持的登录方式')
            create_qr = selected.create_qr if selected else self.create_qr
            login = selected.login if selected else self.login
            label = selected.label if selected else 'QQ'
            retry = '瓦绑定' + (' 微信' if channel == 'wechat' else '') + (' 重新授权' if renew else '')
            await emit(copy.scan_intro(renew=renew, channel=label))
            client = self.client_factory()
            session, image = await asyncio.to_thread(create_qr, client)
            if request.cancelled.is_set():
                return
            await emit(image)
            account = await asyncio.to_thread(login, client, session,
                                              cancelled=request.cancelled.is_set)
            if request.cancelled.is_set():
                return
            try:
                role = await asyncio.to_thread(self.role_name, client, account) or '未识别角色'
            except ShopCheckError:
                role = '未识别角色'
            await member()
            if request.cancelled.is_set():
                return
            account['auth_channel'] = channel
            request.state = 'saving'
            await asyncio.to_thread(self.authorize, group, qq, account, str(role))
            await emit(copy.binding_success(role, renew=renew))
        except ShopCheckError as error:
            if not request.cancelled.is_set():
                await emit(copy.error_reply(error, binding_command=retry))
        finally:
            session.clear()
            account.clear()
            self._release(key, request)

    def cancel(self, group, qq):
        request = self.requests.get((group, qq))
        if request is None:
            raise ShopCheckError('没有进行中的绑定任务。')
        if request.state == 'saving':
            raise ShopCheckError('绑定正在保存，请稍候；保存完成后可发送「商店解绑」。')
        request.cancelled.set()
        # Retain the slot until the polling thread has stopped, so a replacement
        # request can never overlap a late response from this request.

    def close(self):
        for request in self.requests.values():
            if request.state != 'saving':
                request.cancelled.set()

    def cancel_if_active(self, group, qq):
        if (group, qq) not in self.requests:
            return False
        self.cancel(group, qq)
        return True
