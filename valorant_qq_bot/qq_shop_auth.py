"""One-shot QQ QR authentication for a real daily-shop check.

This module implements the protocol steps directly; it does not depend on the
reference plugin. No credential is printed or saved.
"""

import json
import random
import re
import time
import urllib.parse
from typing import Any

from .mval_client import HttpClient
from .errors import ShopCheckError


XLOGIN = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin"
QR_SHOW = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
QR_POLL = "https://xui.ptlogin2.qq.com/ssl/ptqrlogin"
REDIRECT_RESOLVE = "https://openmobile.qq.com/oauth2.0/m_get_redirect_url"
MVAL_QQ_LOGIN = "https://app.mval.qq.com/go/auth/login_by_qq?source_game_zone=agame&game_zone=agame"
CLIENT_ID = "102061775"
QQ_APP_ID = "716027609"
DAID = "381"
ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 12; 23117RK66C Build/V417IR; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/101.0.4951.61 Mobile Safari/537.36"
)
SCAN_UA = ANDROID_UA + " tencent_game_emulator"


def _url(base: str, params: dict[str, str]) -> str:
    return base + "?" + urllib.parse.urlencode(params)


def _token_from_cookie(qrsig: str) -> int:
    value = 0
    for character in qrsig:
        value = (value * 33 + ord(character)) & 0x7FFFFFFF
    return value


def create_qq_qr(client: HttpClient) -> tuple[dict[str, str], bytes]:
    callback = "http://connect.qq.com"
    login_params = {
        "pt_enable_pwd": "1", "appid": QQ_APP_ID, "pt_3rd_aid": CLIENT_ID,
        "daid": DAID, "style": "35", "force_qr": "1", "s_url": callback,
        "refer_cgi": "m_authorize", "ucheck": "1", "fall_to_wv": "1",
        "redirect_uri": "auth://tauth.qq.com/", "client_id": CLIENT_ID,
        "pf": "openmobile_android", "response_type": "token", "scope": "all",
        "sdkp": "a", "sdkv": "3.5.17.lite",
        "sign": "a6479455d3e49b597350f13f776a6288",
        "status_os": "12", "status_machine": "MjMxMTdSSzY2Qw==",
        "switch": "1", "time": "1763280194",
        "h5sig": "trobryxo8IPM0GaSQH12mowKG-CY65brFzkK7_-9EW4",
        "loginty": "6",
    }
    login_url = _url(XLOGIN, login_params)
    headers = {"User-Agent": ANDROID_UA, "Referer": "https://openmobile.qq.com/",
               "X-Requested-With": "com.tencent.apps.valorant",
               "Cookie": "accountType=5; clientType=9"}
    login_page = client.text(login_url, headers=headers)
    login_sig_match = re.search(r'g_login_sig=encodeURIComponent\("([^"]+)"\)', login_page)
    login_sig = login_sig_match.group(1) if login_sig_match else client.cookie("pt_login_sig")
    jsver_match = re.search(r"/monorepo/([0-9A-Za-z]+)/ptlogin/js/", login_page)
    jsver = jsver_match.group(1) if jsver_match else "28d22679"

    qr_url = _url(QR_SHOW, {
        "s": "8", "e": "0", "appid": QQ_APP_ID, "type": "0",
        "t": str(random.random()), "u1": callback, "daid": DAID,
        "pt_3rd_aid": CLIENT_ID,
    })
    _, _, image = client.raw(qr_url, headers={
        "User-Agent": ANDROID_UA, "Referer": login_url,
        "Accept": "image/*,*/*;q=0.8",
        "X-Requested-With": "com.tencent.apps.valorant",
    })
    qrsig = client.cookie("qrsig")
    if not qrsig or not image:
        raise ShopCheckError("QQ 二维码响应缺少会话信息")
    if not (image.startswith(b"\x89PNG") or image.startswith(b"\xff\xd8\xff") or image.startswith(b"GIF8")):
        raise ShopCheckError("QQ 二维码图片格式异常")
    return {
        "token": str(_token_from_cookie(qrsig)),
        "login_sig": login_sig,
        "login_url": login_url,
        "callback": callback,
        "jsver": jsver,
        "pt_openlogin_data": _openlogin_metadata(login_params, client),
        "aegis_uid": client.cookie("__aegis_uid"),
    }, image


def _openlogin_metadata(login_params: dict[str, str], client: HttpClient) -> str:
    metadata = {
        "which": "", "refer_cgi": "m_authorize", "response_type": "token",
        "client_id": CLIENT_ID, "state": "", "display": "", "openapi": "1011",
        "switch": "1", "src": "1", "sdkv": "3.5.17.lite", "sdkp": "a",
        "tid": client.cookie("idt") or str(int(time.time())),
        "pf": "openmobile_android", "need_pay": "0", "browser": "0",
        "browser_error": "", "serial": "", "token_key": "",
        "redirect_uri": login_params["redirect_uri"],
        "sign": login_params["sign"], "time": login_params["time"],
        "status_version": "", "status_os": "12",
        "status_machine": login_params["status_machine"],
        "page_type": "1", "has_auth": "1", "update_auth": "1",
        "auth_time": str(int(time.time() * 1000)), "loginfrom": "",
        "h5sig": login_params["h5sig"], "loginty": "6",
    }
    return urllib.parse.urlencode(metadata)


def _extract_credentials(url: str) -> tuple[str, str, list[str]]:
    candidates = [url]
    seen: set[str] = set()
    keys: list[str] = []
    openid = access_token = ""
    while candidates:
        item = candidates.pop(0).replace("\\/", "/").replace("\\x26", "&")
        if item in seen:
            continue
        seen.add(item)
        for _ in range(3):
            decoded = urllib.parse.unquote(item)
            if decoded == item:
                break
            item = decoded
        parsed = urllib.parse.urlsplit(item)
        for raw in (parsed.query, parsed.fragment):
            params = urllib.parse.parse_qs(raw, keep_blank_values=True)
            openid = openid or (params.get("openid") or [""])[0]
            access_token = access_token or (params.get("access_token") or [""])[0]
            for name in ("key", "keystr", "redirect_uri_key", "uikey"):
                keys += [key for key in params.get(name, []) if key not in keys]
            for name in ("url", "u1", "redirect_uri", "redirect_url", "s_url"):
                candidates.extend(params.get(name, []))
    return openid, access_token, keys


def _complete_redirect(client: HttpClient, callback_url: str, login_url: str) -> tuple[str, str]:
    openid, token, keys = _extract_credentials(callback_url)
    if openid and token:
        return openid, token
    if callback_url.startswith("https://") or callback_url.startswith("http://"):
        try:
            status, headers, body = client.raw(
                callback_url, headers={"User-Agent": ANDROID_UA, "Referer": login_url},
                follow_redirects=False,
            )
            if status in (301, 302, 303, 307, 308):
                next_url = urllib.parse.urljoin(callback_url, headers.get("Location", ""))
                next_openid, next_token, next_keys = _extract_credentials(next_url)
                openid = openid or next_openid
                token = token or next_token
                keys.extend(next_keys)
            else:
                body_text = body.decode("utf-8", "replace")
                match = re.search(r"(auth://tauth\.qq\.com/[^\s\"'<>]+)", body_text)
                if match:
                    next_openid, next_token, next_keys = _extract_credentials(match.group(1))
                    openid = openid or next_openid
                    token = token or next_token
                    keys.extend(next_keys)
        except ShopCheckError:
            pass
    if openid and token:
        return openid, token
    for name in ("redirect_uri_key", "keystr", "key", "uikey"):
        cookie_key = client.cookie(name)
        if cookie_key and cookie_key not in keys:
            keys.append(cookie_key)
    for key in keys:
        response = client.text(
            _url(REDIRECT_RESOLVE, {"keystr": key}),
            headers={"User-Agent": ANDROID_UA, "Referer": "https://imgcache.qq.com/"},
        )
        match = re.search(r"_Callback\s*\(\s*(\{.*?\})\s*\)", response)
        if not match:
            continue
        try:
            resolved = json.loads(match.group(1)).get("url", "")
        except ValueError:
            continue
        new_openid, new_token, _ = _extract_credentials(str(resolved))
        openid = openid or new_openid
        token = token or new_token
        if openid and token:
            return openid, token
    raise ShopCheckError("QQ 扫码已确认，但回调未提供完整授权信息")


def complete_qq_login(client: HttpClient, session: dict[str, str], *, cancelled=None) -> dict[str, str]:
    deadline = time.monotonic() + 120
    network_errors = 0
    while time.monotonic() < deadline:
        if cancelled is not None and cancelled():
            raise ShopCheckError("扫码任务已取消")
        try:
            status, redirect = poll_qq_once(client, session)
            network_errors = 0
        except ShopCheckError as error:
            network_errors += 1
            if network_errors >= 3:
                raise ShopCheckError(f"QQ 扫码状态接口连续失败：{error}") from None
            time.sleep(2)
            continue
        if status:
            if status == "0":
                openid, access_token = _complete_redirect(client, redirect, session["login_url"])
                if cancelled is not None and cancelled():
                    raise ShopCheckError("扫码任务已取消")
                return _exchange_qq_token(client, openid, access_token)
            if status == "65":
                raise ShopCheckError("QQ 登录二维码已过期")
            if status not in ("66", "67"):
                raise ShopCheckError(f"QQ 扫码未完成（状态码 {status}）")
        time.sleep(2)
    raise ShopCheckError("QQ 扫码超时，请重新运行命令")


def poll_qq_once(client: HttpClient, session: dict[str, str]) -> tuple[str, str]:
    params = {
        "u1": session["callback"], "from_ui": "1", "type": "1",
        "ptlang": "2052", "ptqrtoken": session["token"],
        "daid": DAID, "aid": QQ_APP_ID, "pt_3rd_aid": CLIENT_ID,
        "pt_openlogin_data": session["pt_openlogin_data"],
        "device": "2", "ptopt": "1", "pt_uistyle": "35",
        "jsver": session["jsver"], "r": str(random.random()),
    }
    if session["login_sig"]:
        params["login_sig"] = session["login_sig"]
    if session["aegis_uid"]:
        params["aegis_uid"] = session["aegis_uid"]
    text = client.text(_url(QR_POLL, params), headers={
        "User-Agent": SCAN_UA, "Referer": session["login_url"],
        "X-Requested-With": "com.tencent.apps.valorant",
        "Accept": "*/*",
    })
    match = re.search(r"ptuiCB\('([^']*)','[^']*','([^']*)','[^']*','([^']*)'", text)
    if not match:
        raise ShopCheckError("QQ 扫码状态响应无法解析")
    return match.group(1), match.group(2).replace("\\/", "/")


def _exchange_qq_token(client: HttpClient, openid: str, access_token: str) -> dict[str, str]:
    payload: dict[str, Any] = {
        "clienttype": 9,
        "config_params": {"client_dev_name": "23117RK66C", "lang_type": 0},
        "login_info": {
            "appid": 102061775, "openid": openid, "qq_info_type": 5,
            "sig": access_token, "uin": 0,
        },
        "mappid": 10200, "mcode": "132f0a77d34402abc8463d60100011d19b0e",
        "source_game_zone": "agame", "game_zone": "agame",
    }
    reply = client.json(
        MVAL_QQ_LOGIN, payload=payload,
        headers={"User-Agent": ANDROID_UA, "Content-Type": "application/json",
                 "Cookie": "clientType=9; openid=null; access_token=null;"},
    )
    if str(reply.get("result")) != "0":
        raise ShopCheckError(f"掌瓦 QQ 登录失败（结果码 {reply.get('result')}）")
    info = (reply.get("data") or {}).get("login_info") or {}
    account = {
        "user_id": str(info.get("user_id") or ""),
        "ticket": str(info.get("wt") or ""),
        "openid": str(info.get("openid") or openid),
        "access_token": str(info.get("access_token") or access_token),
        "acctype": str(info.get("third_type") or "qc"),
        "uin": str(info.get("uin") or "0"),
        "ct": str(info.get("ct") or ""),
        "refresh_wt_span": str(info.get("refresh_wt_span") or "1800"),
        "refresh_ct_span": str(info.get("refresh_ct_span") or "0"),
        "expires": str(info.get("expires") or "0"),
    }
    if not account["user_id"] or not account["ticket"]:
        raise ShopCheckError("掌瓦 QQ 登录响应缺少商店所需票据")
    return account
