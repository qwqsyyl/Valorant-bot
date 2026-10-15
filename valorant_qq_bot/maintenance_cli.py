"""Safe per-account login diagnostics, shared with the scheduled core."""
import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from .errors import ShopCheckError
from .shop_runtime import application


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group', required=True)
    parser.add_argument('--qq', required=True)
    parser.add_argument('--renew', action='store_true')
    args = parser.parse_args()
    app = application()
    member = app.repository.require_member(args.group, args.qq)
    outcome = 'not_requested'
    if args.renew:
        try:
            outcome = 'saved' if app.maintain_login(args.group, args.qq, force=True) else 'not_due'
        except ShopCheckError:
            outcome = 'failed'
    state = app.repository.auth_state(member['account_key']) or {}
    report = {'qq': args.qq, 'renewal': outcome}
    for key in ('state', 'failures', 'stage', 'code'):
        report[key] = state.get(key)
    for key in ('last_attempt', 'last_success', 'next_attempt'):
        value = state.get(key)
        report[key + '_beijing'] = datetime.fromtimestamp(value, ZoneInfo('Asia/Shanghai')).isoformat() if value else None
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
