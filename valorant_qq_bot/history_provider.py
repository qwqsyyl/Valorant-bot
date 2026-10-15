"""Observed 掌瓦 history protocol; no QQ, SQLite, or credential persistence."""
import re
import time
from .errors import AuthExpiredError, ShopCheckError
from .history_domain import HistoryMatch, MatchHistory
from .mval_client import BASE, ROLE_URL, SHOP_UA, HttpClient, _account_cookie, select_pc_role

HISTORY_PATH = '/go/agame/career/record/list?source_game_zone=agame&game_zone=agame'


class HistoryError(ShopCheckError):
    def __init__(self, reason='unavailable'):
        self.reason = reason
        super().__init__('战绩暂时无法查询，请稍后再试。')


def label(value, fallback='未知'):
    if not isinstance(value, str) or not value.strip():
        return fallback
    return ' '.join(value.split())[:100]


def number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{1,9}', value):
        return int(value)
    return None


class MvalHistoryProvider:
    def __init__(self, *, client_factory=HttpClient, clock=time.time):
        self.client_factory, self.clock = client_factory, clock

    def _request(self, client, url, account, payload, *, data_type=dict):
        try:
            reply = client.json(url, payload=payload, headers={
                'User-Agent': SHOP_UA, 'Content-Type': 'application/json',
                'Accept': '*/*', 'Cookie': _account_cookie(account)}, timeout=15)
        except ShopCheckError:
            raise HistoryError('transport') from None
        if not isinstance(reply, dict):
            raise HistoryError('schema')
        code = str(reply.get('result'))
        if code in {'1001', '1003', '999999'}:
            raise AuthExpiredError('掌瓦登录已失效')
        if code != '0':
            # Unknown upstream errors are never interpreted as an empty history
            # or as a reason to rotate credentials.
            raise HistoryError('upstream')
        data = reply.get('data')
        if not isinstance(data, data_type):
            raise HistoryError('schema')
        if isinstance(data, dict) and 'result' in data and str(data['result']) != '0':
            raise HistoryError('upstream')
        return data

    def fetch(self, account_key, account, expected_name):
        client = self.client_factory()
        data = self._request(client, ROLE_URL, account, {'_t': int(self.clock())})
        roles = data.get('list')
        role = select_pc_role(roles)
        if role is None:
            if isinstance(roles, list) and all(isinstance(r, dict) and r.get('gameId') != 'agame' for r in roles):
                raise HistoryError('pc_role_missing')
            raise HistoryError('identity')
        role_id, scene = role.get('game_role_id'), role.get('scene')
        if not isinstance(role_id, str) or not role_id or not isinstance(scene, str) or not scene:
            raise HistoryError('identity')
        # A mutable display name is not an identity key. The account cookie
        # chooses the role, and every returned record must match that role ID.
        display_name = label(role.get('role_name'), label(expected_name))
        return self.fetch_records(account_key, account, role_id, scene, display_name, client=client)

    def fetch_records(self, account_key, account, role_id, scene, display_name, *, client=None):
        client = client or self.client_factory()
        found, seen_ids, seen_cursors = [], set(), set()
        cursor = None
        for page in range(1, 4):
            payload = {'game_role_id': role_id, 'scene': scene,
                       'page_no': page, 'page_size': 10, '_t': int(self.clock())}
            if cursor:
                payload['baton'] = cursor
            data = self._request(client, BASE + HISTORY_PATH, account, payload)
            rows = data.get('battle_list')
            if not isinstance(rows, list) or len(rows) > 100:
                raise HistoryError('schema')
            for row in rows:
                match = self.parse_match(row, role_id)
                if match is not None and match.match_id not in seen_ids:
                    seen_ids.add(match.match_id)
                    found.append(match)
            found.sort(key=lambda row: row.played_at if row.played_at is not None else -1, reverse=True)
            if len(found) >= 5:
                break
            cursor = data.get('next_baton')
            if not cursor:
                break
            if not isinstance(cursor, str) or cursor in seen_cursors or not rows:
                raise HistoryError('pagination')
            seen_cursors.add(cursor)
        else:
            # Do not claim a complete/empty history when pagination was cut off.
            raise HistoryError('pagination')
        return MatchHistory(account_key, display_name, tuple(found[:5]), self.clock(),
                            str(account.get('authorization_id') or ''))

    def parse_match(self, row, role_id):
        if not isinstance(row, dict):
            raise HistoryError('schema')
        if row.get('role_id') != role_id:
            raise HistoryError('identity')
        match_id = row.get('match_id') or row.get('battle_id')
        if not isinstance(match_id, str) or not match_id or len(match_id) > 128:
            raise HistoryError('schema')
        result = label(row.get('result_title'), '结果未知')
        if result in {'进行中', '对局中', '未结束'}:
            return None
        played_at = number(row.get('ts'))
        if played_at is not None and not 946684800 <= played_at <= self.clock() + 300:
            raise HistoryError('schema')
        content = row.get('content')
        content = content.split('|', 1) if isinstance(content, str) else []
        mode = label(row.get('game_mode'), label(content[0] if content else None))
        map_info = row.get('used_map')
        if map_info is not None and not isinstance(map_info, dict):
            raise HistoryError('schema')
        map_name = label((map_info or {}).get('name'), label(content[1] if len(content) == 2 else None))
        kda = row.get('kda')
        parts = kda.split('/') if isinstance(kda, str) else []
        parsed_kda = [number(x) for x in parts] if len(parts) == 3 else [None] * 3
        stats = []
        for key, fallback in zip(('kills', 'deaths', 'assists'), parsed_kda):
            value = number(row.get(key)) if row.get(key) is not None else fallback
            if value is not None and fallback is not None and value != fallback:
                raise HistoryError('schema')
            stats.append(value)
        return HistoryMatch(match_id, played_at, mode, map_name, label(row.get('hero_name')),
                            result, number(row.get('round_won')), number(row.get('round_fail')), *stats)
