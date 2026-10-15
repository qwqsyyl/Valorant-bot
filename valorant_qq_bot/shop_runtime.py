"""Composition root shared by CLI and NoneBot; one application per process."""
from functools import lru_cache
import os
from .daily_provider import MvalShopProvider
from .saved_login import CredentialVault
from .shop_application import ShopApplication
from .shop_repository import ShopRepository

@lru_cache(maxsize=1)
def application():
    hour = int(os.environ.get('VALORANT_CONFIRMED_RESET_HOUR', '8'))
    provider = MvalShopProvider(confirmed_reset_hour=hour)
    vault = CredentialVault()
    renewal = None
    return ShopApplication(
        ShopRepository(os.environ.get('VALORANT_SHOP_DB', 'data/shop.sqlite3')),
        vault,
        provider,
        reset_hour=hour,
        renewal_strategy=renewal,
    )
