"""Real-account core validation using the production service, without a QQ bot."""
import argparse
import json
import secrets
import sys
from pathlib import Path
from .errors import ShopCheckError
from .mval_client import HttpClient, fetch_role_name
from .login_channels import CHANNELS
from .real_shop import _write_qr
from .shop_runtime import application

def main(argv=None):
    parser = argparse.ArgumentParser(description='真实账号商店服务验收；无需连接 QQ Bot')
    parser.add_argument('action', choices=('login', 'shop', 'refresh', 'unlink', 'wish', 'wishes'))
    parser.add_argument('--qq', default='personal-test', help='测试绑定标识，正式 QQ 绑定由事件提供')
    parser.add_argument('--group', default='core-test', help='与正式 QQ 群隔离的测试组')
    parser.add_argument('--name', help='wish 操作的完整商品名称')
    parser.add_argument('--channel', choices=tuple(CHANNELS), default='qq', help='QQ 或微信游戏账号登录')
    parser.add_argument('--qr-file', type=Path, default=None)
    args = parser.parse_args(argv)
    qr = None
    try:
        app = application()
        if args.action == 'login':
            client = HttpClient()
            channel = CHANNELS[args.channel]
            session, image = channel.create_qr(client)
            qr = args.qr_file or Path("data/login-" + secrets.token_hex(6) + ".png")
            _write_qr(qr, image)
            print(f'请用 {channel.label} 扫码并确认：{qr.resolve()}（最多等待 120 秒）', flush=True)
            account = channel.login(client, session)
            account['auth_channel'] = args.channel
            try:
                role = fetch_role_name(client, account) or '未识别角色'
            except ShopCheckError:
                role = '未识别角色'
            shop = app.authorize(args.group, args.qq, account, role)
            print(f'绑定并保存成功：{role}', flush=True)
        elif args.action in ('shop', 'refresh'):
            shop = app.query(args.group, args.qq, force=True, refresh_now=args.action == 'refresh')
        elif args.action == 'unlink':
            app.unlink(args.group, args.qq)
            print('已解除测试组绑定。')
            return 0
        elif args.action == 'wish':
            if not args.name:
                parser.error('wish 需要 --name 完整商品名称')
            key = app.add_wish(args.group, args.qq, args.name)
            print('愿望已保存：' + key)
            return 0
        else:
            for wish in app.repository.wishes(args.group, args.qq):
                print(wish.name + ('（商品 ID 匹配）' if wish.goods_id else '（完整名称匹配）'))
            return 0
        for offer in shop.offers:
            print(f'{offer.name} · {offer.price} · {offer.price_unit}')
        print(f'刷新周期：{shop.cycle_source}；商品 ID：' + ('已返回' if all(o.goods_id for o in shop.offers) else '部分或全部未返回'))
        if args.action == 'refresh':
            member = app.repository.require_member(args.group, args.qq)
            stored = app.vault.load(member['account_key'])
            print('商店票据续期并查询验证成功。')
            if stored.get('aux_refresh_pending'):
                print('第三方令牌续期接口未通过；当前商店票据可用，仍可能需要再次扫码。')
        if shop.cycle is None:
            print('刷新周期尚未确认，自动提醒保持关闭；商店查询与愿望保存可正常测试。')
        return 0
    except ShopCheckError as error:
        print(f'核心验证失败：{error}', file=sys.stderr)
        return 1
    finally:
        if 'app' in locals() and getattr(app.provider, 'last_schema', None):
            schema = Path('data/shop-schema.json')
            schema.parent.mkdir(parents=True, exist_ok=True)
            schema.write_text(json.dumps(app.provider.last_schema, ensure_ascii=False, indent=2))
        if qr:
            qr.unlink(missing_ok=True)
        if 'session' in locals():
            session.clear()
        if 'account' in locals():
            account.clear()

if __name__ == '__main__':
    raise SystemExit(main())
