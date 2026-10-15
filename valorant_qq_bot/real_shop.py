"""Compatibility entry point; real account operations use shop_core_cli."""
import argparse
import os
from pathlib import Path
from .mval_client import AuthExpiredError, ShopCheckError, HttpClient, parse_goods, parse_poll, refresh_login


def _write_qr(path: Path, image: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(image)


def main():
    parser = argparse.ArgumentParser(description="QQ 商店验证兼容入口，新测试请使用 shop_core_cli")
    parser.add_argument("--channel", choices=("qq",))
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--remember", action="store_true")
    parser.add_argument("--saved", action="store_true")
    parser.add_argument("--refresh-now", action="store_true")
    parser.add_argument("--forget", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--qr-file", type=Path, default=None)
    args = parser.parse_args()
    if args.probe:
        if args.saved or args.forget or args.refresh_now:
            parser.error("probe 不能与保存的账号操作组合")
        from .qq_shop_auth import create_qq_qr
        try:
            create_qq_qr(HttpClient())
            print("QQ 二维码接口通过；尚未授权真实账号。")
            return 0
        except ShopCheckError as error:
            print(str(error))
            return 1
    if args.forget:
        action = "unlink"
    elif args.saved:
        action = "refresh" if args.refresh_now else "shop"
    elif args.channel == "qq" and args.remember:
        action = "login"
    else:
        parser.error("请使用 --channel qq --remember 或 --saved；新入口为 shop_core_cli")
    from .shop_core_cli import main as core_main
    return core_main([action] + (["--qr-file", str(args.qr_file)] if args.qr_file else []))

if __name__ == "__main__":
    raise SystemExit(main())
