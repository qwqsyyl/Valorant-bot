"""Share the production core and locks with the shop and history services."""
from functools import lru_cache
from .friend_application import FriendApplication
from .shop_runtime import application as shop_application


@lru_cache(maxsize=1)
def application():
    return FriendApplication(shop_application())
