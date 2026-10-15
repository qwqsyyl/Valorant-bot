"""Real history CLI, using the same service as QQ without sending messages."""
import argparse
from .errors import ShopCheckError
from .history_reply import format_history, error_reply
from .history_runtime import application


def main():
    parser = argparse.ArgumentParser(description='国服最近五场战绩文字查询')
    parser.add_argument('--group', required=True)
    parser.add_argument('--requester', required=True)
    parser.add_argument('--target')
    args = parser.parse_args()
    try:
        print(format_history(application().query(args.group, args.requester, args.target)))
    except ShopCheckError as error:
        print(error_reply(error))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
