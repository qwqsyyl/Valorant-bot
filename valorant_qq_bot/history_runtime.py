"""One history service sharing the running shop application's account locks."""
from functools import lru_cache
from .history_application import HistoryApplication
from .shop_runtime import application as shop_application


@lru_cache(maxsize=1)
def application():
    return HistoryApplication(shop_application())
