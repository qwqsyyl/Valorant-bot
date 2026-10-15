import os
import nonebot
from nonebot.adapters.onebot.v11 import Adapter


def main() -> None:
    group = os.environ.get("VALORANT_GROUP_ID", "")
    token = os.environ.get("ONEBOT_ACCESS_TOKEN", "")
    if not group.isdecimal() or not token:
        raise RuntimeError("请先配置 VALORANT_GROUP_ID 和 ONEBOT_ACCESS_TOKEN")
    nonebot.init(host=os.environ.get("VALORANT_BOT_HOST", "127.0.0.1"), port=8080, onebot_access_token=token)
    driver = nonebot.get_driver()
    driver.register_adapter(Adapter)
    nonebot.load_plugin("valorant_qq_bot.daily_plugin")
    nonebot.run()


if __name__ == "__main__":
    main()
