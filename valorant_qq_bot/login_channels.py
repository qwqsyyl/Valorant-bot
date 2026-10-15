"""Channel selection shared by group binding and the real-account CLI."""
from dataclasses import dataclass
from typing import Callable
from .errors import ShopCheckError
from .mval_client import create_qr, wait_for_scan, exchange_login
from .qq_shop_auth import create_qq_qr, complete_qq_login


def create_wechat_qr(client):
    uuid, image = create_qr(client)
    return {'uuid': uuid}, image


def complete_wechat_login(client, session, *, cancelled=None):
    code = wait_for_scan(client, session['uuid'], cancelled=cancelled)
    if cancelled is not None and cancelled():
        raise ShopCheckError('扫码任务已取消')
    return exchange_login(client, code)


@dataclass(frozen=True)
class LoginChannel:
    label: str
    create_qr: Callable
    login: Callable


CHANNELS = {
    'qq': LoginChannel('QQ', create_qq_qr, complete_qq_login),
    'wechat': LoginChannel('微信', create_wechat_qr, complete_wechat_login),
}


def account_channel(account):
    if account.get('auth_channel') in CHANNELS:
        return account['auth_channel']
    return 'wechat' if account.get('acctype') == 'wx' else 'qq'


def parse_binding_arguments(argument):
    """None means default QQ on first bind, saved channel on reauthorization."""
    parts = argument.lower().split()
    renew = '重新授权' in parts
    if renew:
        parts.remove('重新授权')
    if not parts:
        return None, renew
    if parts == ['qq']:
        return 'qq', renew
    if parts == ['微信']:
        return 'wechat', renew
    raise ShopCheckError('绑定参数无效')
