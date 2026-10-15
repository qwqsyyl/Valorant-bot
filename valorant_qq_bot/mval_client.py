"""Personal CN daily-shop check via 掌瓦 QR login or a saved Keychain login."""

import base64
import hashlib
import http.cookiejar
import http.cookies
import json
import os
import re
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


APP_ID = "wxcbb49f1f39656c2a"
BASE = "https://app.mval.qq.com"
TICKET_URL = BASE + "/go/auth/get_sdk_ticket"
LOGIN_URL = BASE + "/go/auth/login_by_wechat"
SHOP_URL = BASE + "/go/mlol_store/agame/user_store"
ROLE_URL = BASE + "/go/account/get_main_role_raw"
QR_URL = "https://open.weixin.qq.com/connect/sdk/qrconnect"
POLL_URL = "https://long.open.weixin.qq.com/connect/l/qrconnect"

# Protocol identifiers from the public reference project. No user credential is embedded.
DEVICE = "22041216C"
MCODE = "69028af6dca2c107f4f58290100011b1a303"
APP_UA = (
    "mval/2.10062 Channel/3 Manufacturer/Redmi "
    "Mozilla/5.0 (Linux; Android 12; 22041216C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/110.0.5481.154 Mobile Safari/537.36"
)
WX_UA = (
    "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)
SHOP_UA = (
    "mval/2.3.0.10050 Channel/5 Manufacturer/Xiaomi "
    "Mozilla/5.0 (Linux; Android 14; 23078RKD5C Build/UP1A.230905.011; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/140.0.7339.207 Mobile Safari/537.36"
)


from .errors import ShopCheckError, AuthExpiredError, RenewalError


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, message: str,
                         headers: Any, newurl: str) -> None:
        return None


def decode_json_copies(text):
    """Accept observed identical copies, reject trailing or conflicting data."""
    decoder = json.JSONDecoder()
    text = text.strip()
    value, end = decoder.raw_decode(text)
    rest = text[end:].strip()
    copies = 1
    while rest:
        extra, end = decoder.raw_decode(rest)
        if extra != value or copies >= 3:
            raise ValueError('conflicting JSON response')
        copies += 1
        rest = rest[end:].strip()
    return value


class HttpClient:
    def __init__(self) -> None:
        mac_ca = Path("/etc/ssl/cert.pem")
        tls = ssl.create_default_context(cafile=str(mac_ca)) if sys.platform == "darwin" and mac_ca.exists() else ssl.create_default_context()
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=tls),
        )
        self.no_redirect_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=tls),
            _NoRedirect(),
        )

    def cookie(self, name: str) -> str:
        for cookie in self.cookies:
            if cookie.name == name:
                return cookie.value
        return ""

    def raw(self, url: str, *, payload: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None, timeout: int = 20,
            follow_redirects: bool = True) -> tuple[int, Any, bytes]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=headers or {})
        opener = self.opener if follow_redirects else self.no_redirect_opener
        try:
            with opener.open(request, timeout=timeout) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            if not follow_redirects and 300 <= error.code < 400:
                return error.code, error.headers, error.read()
            raise ShopCheckError(f"上游 HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            raise ShopCheckError(f"网络请求失败：{type(error).__name__}") from None

    def text(self, url: str, *, payload: dict[str, Any] | None = None,
             headers: dict[str, str] | None = None, timeout: int = 20) -> str:
        _, _, body = self.raw(url, payload=payload, headers=headers, timeout=timeout)
        return body.decode("utf-8", "replace")

    def json(self, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            result = decode_json_copies(self.text(url, **kwargs))
        except (ValueError, TypeError):
            raise ShopCheckError("上游返回了无法解析的数据") from None
        if not isinstance(result, dict):
            raise ShopCheckError("上游返回结构异常")
        return result


def _auth_payload() -> dict[str, Any]:
    return {
        "clienttype": 9,
        "config_params": {"client_dev_name": DEVICE, "lang_type": 0},
        "mappid": 10200,
        "mcode": MCODE,
        "source_game_zone": "agame",
        "game_zone": "agame",
    }


def create_qr(client: HttpClient) -> tuple[str, bytes]:
    ticket_request = {**_auth_payload(), "sdk_appid": APP_ID}
    ticket_reply = client.json(
        TICKET_URL, payload=ticket_request,
        headers={"User-Agent": APP_UA, "Content-Type": "application/json"},
    )
    data = ticket_reply.get("data")
    ticket = data.get("ticket") if isinstance(data, dict) else None
    if str(ticket_reply.get("result")) != "0" or not isinstance(ticket, str) or not ticket:
        raise ShopCheckError("获取掌瓦微信扫码票据失败")

    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(6)
    signing_text = f"appid={APP_ID}&noncestr={nonce}&sdk_ticket={ticket}&timestamp={timestamp}"
    signature = hashlib.sha1(signing_text.encode("utf-8")).hexdigest()
    params = {
        "f": "json", "appid": APP_ID, "noncestr": nonce, "timestamp": timestamp,
        "scope": "snsapi_userinfo", "signature": signature,
    }
    reply = client.json(
        QR_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": WX_UA, "Accept": "*/*"},
    )
    if str(reply.get("errcode")) != "0":
        raise ShopCheckError("微信二维码申请失败")
    uuid = reply.get("uuid")
    qr = reply.get("qrcode")
    image_b64 = qr.get("qrcodebase64") if isinstance(qr, dict) else None
    if not isinstance(uuid, str) or not uuid or not isinstance(image_b64, str):
        raise ShopCheckError("扫码二维码响应缺少必要字段")
    try:
        image = base64.b64decode(image_b64.split(",", 1)[-1], validate=True)
    except ValueError:
        raise ShopCheckError("扫码二维码图片无效") from None
    if not (image.startswith(b"\x89PNG") or image.startswith(b"\xff\xd8\xff") or image.startswith(b"GIF8")):
        raise ShopCheckError("扫码二维码图片格式异常")
    return uuid, image


def parse_poll(text: str) -> tuple[int, str]:
    try:
        reply = json.loads(text)
        if isinstance(reply, dict):
            if "wx_errcode" not in reply:
                raise ShopCheckError("扫码状态响应缺少状态码")
            auth_code = reply.get("wx_code", "")
            if auth_code is None:
                auth_code = ""
            if not isinstance(auth_code, str):
                raise ShopCheckError("扫码授权码格式异常")
            return int(reply["wx_errcode"]), auth_code
    except (ValueError, TypeError):
        pass
    code = re.search(r"wx_errcode\s*=\s*(\d+)", text)
    auth_code = re.search(r"wx_code\s*=\s*['\"]([^'\"]+)['\"]", text)
    if code:
        return int(code.group(1)), auth_code.group(1) if auth_code else ""
    raise ShopCheckError("扫码状态响应无法解析")


def wait_for_scan(client: HttpClient, uuid: str, *, seconds: int = 120, cancelled=None) -> str:
    deadline = time.monotonic() + seconds
    last: int | None = None
    network_errors = 0

    def check_cancelled():
        if cancelled is not None and cancelled():
            raise ShopCheckError("扫码任务已取消")

    while time.monotonic() < deadline:
        check_cancelled()
        params = {"f": "json", "uuid": uuid, "_": str(int(time.time() * 1000))}
        if last is not None:
            params["last"] = str(last)
        try:
            reply = client.text(
                POLL_URL + "?" + urllib.parse.urlencode(params),
                headers={"User-Agent": WX_UA, "Accept": "*/*"},
                timeout=max(1, min(35, int(deadline - time.monotonic()))),
            )
        except ShopCheckError:
            check_cancelled()
            network_errors += 1
            if network_errors >= 3:
                raise ShopCheckError("微信扫码状态接口连续失败") from None
            time.sleep(min(1, max(0, deadline - time.monotonic())))
            continue
        check_cancelled()
        network_errors = 0
        if time.monotonic() >= deadline:
            break
        status, auth_code = parse_poll(reply)
        if status in (0, 405):
            if auth_code:
                return auth_code
            raise ShopCheckError("微信扫码已确认但缺少授权码")
        if status == 402:
            raise ShopCheckError("微信登录二维码已过期")
        if status == 403:
            raise ShopCheckError("微信授权已取消")
        if status not in (404, 408):
            raise ShopCheckError("微信扫码状态异常")
        last = status
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    raise ShopCheckError("微信扫码超时")


def exchange_login(client: HttpClient, auth_code: str) -> dict[str, str]:
    payload = {
        **_auth_payload(),
        "login_info": {
            "appid": APP_ID, "check_third_type": 1,
            "code": auth_code, "wx_info_type": 1,
        },
    }
    reply = client.json(
        LOGIN_URL, payload=payload,
        headers={
            "User-Agent": APP_UA, "Content-Type": "application/json",
            "Cookie": "clientType=9; openid=null; access_token=null;",
        },
    )
    data = reply.get("data")
    info = data.get("login_info") if isinstance(data, dict) else None
    if (str(reply.get("result")) != "0" or not isinstance(info, dict)
            or str(info.get("result", 0)) != "0"):
        raise ShopCheckError("掌瓦微信登录失败")
    if any(not isinstance(info.get(field), str) or not info[field]
           for field in ("wt", "openid", "ct")):
        raise ShopCheckError("掌瓦微信登录响应缺少必要票据")
    if not isinstance(info.get("user_id"), (str, int)) or not info["user_id"]:
        raise ShopCheckError("掌瓦微信登录响应缺少账号标识")
    account = {
        "user_id": str(info.get("user_id") or ""),
        "ticket": str(info.get("wt") or ""),
        "openid": str(info.get("openid") or ""),
        # This endpoint identifies the channel; numeric third_type is not
        # the textual acctype expected by the app Cookie protocol.
        "acctype": "wx",
        "auth_channel": "wechat",
        "uin": "0",
        "ct": str(info.get("ct") or ""),
        "refresh_wt_span": str(info.get("refresh_wt_span") or "1800"),
        "refresh_ct_span": str(info.get("refresh_ct_span") or "0"),
        "expires": str(info.get("expires") or "0"),
    }
    # Real WeChat replies can omit access_token while returning WT/CT/CTT/SK.
    # Preserve optional values actually returned; never manufacture a token.
    for field in ("access_token", "ctt", "sk"):
        value = info.get(field)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            raise ShopCheckError("掌瓦微信登录响应票据类型异常")
        account[field] = value
    return account


def parse_goods(reply: dict[str, Any]) -> list[tuple[str, str]]:
    if str(reply.get("result")) != "0":
        message = str(reply.get("errMsg") or reply.get("msg") or "").lower()
        if str(reply.get("result")) in {"1001", "1003", "999999"} or "ticket expire" in message or "auth web ticket fail" in message:
            raise AuthExpiredError("掌瓦登录票据已失效")
        raise ShopCheckError(f"商店查询失败（结果码 {reply.get('result')}）")
    data = reply.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict) or not isinstance(data.get("list"), list):
        raise ShopCheckError("商店回包缺少商品列表")
    goods = []
    for item in data["list"]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("goods_name") or "").strip()
        if name:
            goods.append((name, str(item.get("rmb_price") or "价格未知")))
    return goods


def _account_cookie(account: dict[str, str]) -> str:
    return "; ".join([
        "clientType=9", "uin=o" + account.get("uin", "0"), "appid=102061775",
        "acctype=" + account["acctype"],
        "openid=" + (account["openid"] or "null"),
        "access_token=" + (account.get("access_token") or "null"),
        "userId=" + account["user_id"], "accountType=5",
        "tid=" + account["ticket"],
    ] + [f"{name}={account[name]}" for name in ("ctt", "sk") if account.get(name)])


def _refresh_reply(client: HttpClient, path: str, account: dict[str, str],
                   payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    stage = path.rsplit('/', 1)[-1]
    try:
        status, headers, body = client.raw(
            BASE + path + "?source_game_zone=agame&game_zone=agame",
            payload=payload,
            headers={"User-Agent": SHOP_UA, "Content-Type": "application/json",
                     "Accept": "*/*", "Cookie": _account_cookie(account)},
        )
    except ShopCheckError:
        raise RenewalError(stage, 'transport', reason='network') from None
    try:
        # Observed upstream sometimes repeats the identical JSON twice. Accept
        # only identical complete copies, never ignore a conflicting payload.
        reply = decode_json_copies(body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise RenewalError(stage, 'invalid_json', reason='format') from None
    if status != 200 or not isinstance(reply, dict) or str(reply.get("result", reply.get("ret", ""))) != "0":
        value = str(reply.get('result', reply.get('ret', 'missing'))) if isinstance(reply, dict) else 'missing'
        code = value if re.fullmatch(r'-?\d{1,12}', value) else 'invalid_result'
        reason = ' '.join(str(reply.get(key, '')) for key in ('msg', 'errMsg', 'err_msg')).lower() if isinstance(reply, dict) else ''
        rejected = any(phrase in reason for phrase in ('auth web ticket fail', 'ticket expire', 'client ticket expired', 'invalid client ticket'))
        raise RenewalError(stage, code, rejected=rejected)
    cookies: dict[str, str] = {}
    for value in headers.get_all("Set-Cookie", []):
        parsed = http.cookies.SimpleCookie()
        try:
            parsed.load(value)
        except http.cookies.CookieError:
            continue
        for name in ("tid", "ctt", "sk"):
            if name in parsed:
                cookies[name] = parsed[name].value
    return reply, cookies


def get_web_ticket(client, account, *, checkpoint=None):
    """Obtain a WT candidate; the shared application validates before promotion."""
    if not account.get('ct'):
        raise RenewalError('get_web_ticket', 'missing_ct', reason='fields')
    reply, cookies = _refresh_reply(client, '/go/auth/get_web_ticket', account, {
        'config_params': {'lang_type': 0}, 'ct': account['ct'],
        'user_id': account['user_id'], 'source_game_zone': 'agame', 'game_zone': 'agame',
    })
    data = reply.get('data')
    if not isinstance(data, dict):
        raise RenewalError('get_web_ticket', 'missing_data', reason='fields')
    info = data.get('ct_info') if isinstance(data.get('ct_info'), dict) else data
    wt = cookies.get('tid') or info.get('wt')
    if not isinstance(wt, str) or not wt:
        raise RenewalError('get_web_ticket', 'missing_wt', reason='fields')
    candidate = dict(account, ticket=wt)
    # Preserve any rotated CT immediately, even on a nominally WT-only endpoint.
    ct = info.get('ct')
    if isinstance(ct, str) and ct:
        candidate['ct'] = ct
    user_id = info.get('user_id')
    if user_id is not None and str(user_id) != account['user_id']:
        raise RenewalError('get_web_ticket', 'account_mismatch', reason='validation')
    # Auxiliary steps belong to the retired joint-refresh flow, not this path.
    for field in ('aux_refresh_pending', 'aux_refresh_stage', 'aux_refresh_code'):
        candidate.pop(field, None)
    for field in ('expires', 'refresh_wt_span', 'refresh_ct_span'):
        if info.get(field) is not None:
            candidate[field] = str(info[field])
    now = int(time.time())
    candidate['auth_refreshed_at'] = str(now)
    candidate['next_refresh_at'] = str(now + _refresh_delay(candidate))
    if checkpoint:
        checkpoint(dict(candidate))
    return candidate


def refresh_login(client: HttpClient, account: dict[str, str], *, checkpoint=None) -> dict[str, str]:
    """Compatibility name; all callers now use the same WT-only protocol."""
    return get_web_ticket(client, account, checkpoint=checkpoint)


def _refresh_delay(account: dict[str, str]) -> int:
    try:
        span = int(float(account.get("refresh_wt_span") or 1800))
    except ValueError:
        span = 1800
    return max(300, min(3600, int(span * 0.65)))


def select_pc_role(roles):
    """Main-role responses can contain both PC (agame) and mobile (codev)."""
    if not isinstance(roles, list) or not roles or len(roles) > 100 or any(not isinstance(r, dict) for r in roles):
        return None
    candidates = [role for role in roles if role.get('gameId') == 'agame']
    if len(candidates) == 1:
        return candidates[0]
    # The feature is PC-only: do not guess from names/order or fall back to
    # mobile/unknown games, even when the response contains just one role.
    return None


def fetch_role_name(client: HttpClient, account: dict[str, str]) -> str | None:
    reply = client.json(
        ROLE_URL, payload={"_t": int(time.time())},
        headers={
            "User-Agent": SHOP_UA, "Content-Type": "application/json",
            "Accept": "*/*", "Cookie": _account_cookie(account),
        },
    )
    if str(reply.get("result")) != "0":
        return None
    data = reply.get("data")
    if not isinstance(data, dict):
        return None
    roles = data.get("list") or data.get("roles") or []
    role = select_pc_role(roles)
    if role is None:
        return None
    return str(role.get("role_name") or role.get("name") or "").strip() or None
