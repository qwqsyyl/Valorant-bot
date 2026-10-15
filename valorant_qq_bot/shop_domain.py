"""Production shop model. Demo models remain confined to the demo commands."""
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import json
from zoneinfo import ZoneInfo


def shop_day_bounds(now, hour=8):
    """The confirmed Beijing reset defines a shop day, including before 08:00."""
    local = datetime.fromtimestamp(now, ZoneInfo('Asia/Shanghai'))
    start = local.replace(hour=hour, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=1)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()

@dataclass(frozen=True)
class Offer:
    name: str
    price: str
    goods_id: str | None = None
    price_unit: str = "VP"
    image_url: str | None = None

    @property
    def identity(self):
        return "id:" + self.goods_id if self.goods_id else "name:" + self.name

@dataclass(frozen=True)
class DailyShop:
    account_key: str
    offers: tuple[Offer, ...]
    fetched_at: float
    cycle: str | None = None
    expires_at: float | None = None
    cycle_source: str = "未验证"

    def current_for_day(self, now, hour=8):
        start, end = shop_day_bounds(now, hour)
        return (bool(self.cycle) and start <= self.fetched_at <= now
                and self.expires_at is not None and self.expires_at >= end)

    def dumps(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def loads(cls, text):
        data = json.loads(text)
        # Normalize the previous placeholder in saved snapshots after confirmation.
        for offer in data["offers"]:
            if offer.get("price_unit") == "上游原始价格（单位待验证）":
                offer["price_unit"] = "VP"
        data["offers"] = tuple(Offer(**offer) for offer in data["offers"])
        return cls(**data)

@dataclass(frozen=True)
class Wish:
    key: str
    name: str
    goods_id: str | None = None

    def matches(self, offer: Offer):
        return self.goods_id == offer.goods_id if self.goods_id else self.name == offer.name
