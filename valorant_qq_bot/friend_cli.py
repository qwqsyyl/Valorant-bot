"""Read-only friend list/history CLI; never sends QQ messages."""
import argparse
from .errors import ShopCheckError
from .friend_runtime import application
from .friend_reply import format_friends, error_reply
from .history_reply import format_history


def main():
    parser = argparse.ArgumentParser(description='国服端游游戏好友查询')
    parser.add_argument('--group', required=True)
    parser.add_argument('--requester', required=True)
    parser.add_argument('--keyword', default='')
    parser.add_argument('--select', type=int)
    args = parser.parse_args()
    app = application()
    try:
        selection = app.list(args.group, args.requester, args.keyword)
        print(format_friends(selection))
        if args.select is not None:
            result = app.query(args.group, args.requester, f'{selection.code}-{args.select}')
            app.validate_delivery(args.group, args.requester, result)
            print(format_history(result.history))
    except ShopCheckError as error:
        print(error_reply(error))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
