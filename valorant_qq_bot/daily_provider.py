"""One protocol adapter for all real shop queries; no QQ or database imports."""
import time
from .mval_client import HttpClient, BASE, SHOP_URL, SHOP_UA, _account_cookie, parse_goods, get_web_ticket
from .errors import ShopCheckError, AuthExpiredError, RenewalError
from .shop_domain import DailyShop, Offer, shop_day_bounds

class MvalShopProvider:
    def __init__(self, *, confirmed_reset_hour: int | None = None):
        if confirmed_reset_hour is not None and not 0 <= confirmed_reset_hour <= 23:
            raise ValueError("刷新小时需在 0–23 之间")
        self.reset_hour = confirmed_reset_hour

    def refresh(self, account):
        return get_web_ticket(HttpClient(), account)

    def refresh_checked(self, account, checkpoint):
        return get_web_ticket(HttpClient(), account, checkpoint=checkpoint)

    def validate_login(self, account):
        """Validate account authentication without recollecting today's shop."""
        try:
            reply = HttpClient().json(BASE + '/go/auth/bind_relation_list?source_game_zone=agame&game_zone=agame',
                payload={}, headers={'User-Agent': SHOP_UA, 'Content-Type': 'application/json',
                                     'Cookie': _account_cookie(account)})
        except ShopCheckError:
            raise RenewalError('validate_login', 'transport', reason='network') from None
        code = str(reply.get('result'))
        if code in {'1001', '1003', '999999'}:
            raise AuthExpiredError('掌瓦登录票据已失效')
        if code != '0' or not isinstance(reply.get('data'), dict):
            raise RenewalError('validate_login', 'invalid_response', reason='validation')

    def fetch(self, account_key, account):
        reply = HttpClient().json(SHOP_URL, payload={"_t": int(time.time())}, headers={
            "User-Agent": SHOP_UA, "Content-Type": "application/json",
            "Accept": "*/*", "Cookie": _account_cookie(account),
        })
        # Store only structural information and explicitly public product fields.
        # Never dump an entire upstream response or auth payload.
        data = reply.get("data")
        blocks = data if isinstance(data, list) else [data]
        schema = []
        for block in blocks:
            if not isinstance(block, dict):
                schema.append({"type": type(block).__name__})
                continue
            schema.append({"fields": {key: type(value).__name__ for key, value in block.items()},
                           "metadata": {key: block[key] for key in ("key", "title", "time", "end_ts", "cur_ts") if key in block and isinstance(block[key], (str, int))},
                           "goods": [{key: item[key] for key in ("goods_name", "goods_id", "rmb_price", "goods_pic") if key in item and isinstance(item[key], (str, int, float))}
                                     for item in block.get("list", []) if isinstance(item, dict)] if isinstance(block.get("list"), list) else []})
        self.last_schema = schema
        return self.parse(account_key, reply, time.time())

    def parse(self, account_key, reply, now):
        # Validate upstream status using the already tested protocol parser.
        parse_goods(reply)
        data = reply["data"]
        if isinstance(data, list):
            daily = [block for block in data if isinstance(block, dict) and block.get("key") == "dailystore"]
            if len(daily) != 1:
                raise ShopCheckError("未找到唯一每日商店数据块，未合并其他商店")
            data = daily[0]
        offers = []
        for item in data["list"]:
            if not isinstance(item, dict) or not str(item.get("goods_name") or "").strip():
                raise ShopCheckError("商品列表含无效项目，未覆盖旧商店")
            identifier = item.get("goods_id")
            if identifier is not None and not isinstance(identifier, (str, int)):
                raise ShopCheckError("商品 ID 格式异常")
            price = item.get("rmb_price")
            offers.append(Offer(str(item["goods_name"]).strip(),
                                str(price) if price is not None else "未知",
                                str(identifier) if identifier is not None else None,
                                image_url=item.get("goods_pic") if isinstance(item.get("goods_pic"), str) else None))
        if not offers:
            raise ShopCheckError("商店商品为空，未覆盖旧商店")
        # No guessed upstream field names, price conversions or content-hash cycles.
        cycle = None
        expires = None
        source = "未验证"
        end = data.get("end_ts")
        current = data.get("cur_ts")
        if isinstance(end, int) and isinstance(current, int) and 0 < end-current <= 172800 and abs(current-now) < 300:
            cycle = "mval-end:" + str(end)
            expires = float(end + 1)
            source = "掌瓦每日商店 end_ts"
        elif self.reset_hour is not None:
            # A stale explicit upstream cycle must never be relabelled as today.
            if end is not None or current is not None:
                raise ShopCheckError('掌瓦商店周期尚未更新或时间异常，请稍后重试')
            start, expires = shop_day_bounds(now, self.reset_hour)
            cycle = 'beijing-reset:' + str(int(start))
            source = "管理员确认的北京时间刷新时刻"
        return DailyShop(account_key, tuple(offers), now, cycle, expires, source)
