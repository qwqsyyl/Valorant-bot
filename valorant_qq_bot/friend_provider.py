"""Read-only PC game relationships using only the viewer's credentials."""
from dataclasses import dataclass, field
import hashlib
from .errors import AuthExpiredError
from .history_provider import MvalHistoryProvider, HistoryError, label
from .mval_client import BASE, ROLE_URL, select_pc_role

QUERY = '?source_game_zone=agame&game_zone=agame'


class FriendError(HistoryError):
    pass


@dataclass(frozen=True)
class Friend:
    role_id: str = field(repr=False)
    uuid: str = field(repr=False)
    scene: str = field(repr=False)
    name: str = '端游好友'


def identifier(value, maximum=2048):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise FriendError('identity')
    return value


class MvalFriendProvider(MvalHistoryProvider):
    def owner(self, account):
        data = self._request(self.client_factory(), ROLE_URL, account, {'_t': int(self.clock())})
        role = select_pc_role(data.get('list'))
        if role is None:
            raise FriendError('pc_role_missing')
        if role.get('uuid') != account.get('user_id'):
            raise FriendError('identity')
        for key in ('uuid', 'scene', 'game_role_id'):
            identifier(role.get(key))
        return role

    def relations(self, account, owner):
        client = self.client_factory()
        found, cursors = {}, set()
        cursor = ''
        for _ in range(10):
            data = self._request(client, BASE + '/go/relation/query_relation_list' + QUERY, account,
                {'cache_version': '', 'scene': owner['scene'], 'main_uuid': owner['uuid'],
                 'uuid': owner['uuid'], 'baton': cursor, '_t': int(self.clock())})
            rows = data.get('relation_list')
            if data.get('rsp_data_type') != 2 or not isinstance(rows, list) or len(rows) > 200:
                raise FriendError('schema')
            for row in rows:
                if not isinstance(row, dict):
                    raise FriendError('schema')
                flag, black = row.get('is_game_friend'), row.get('is_black_user')
                if type(flag) is not int or flag not in (0, 1) or type(black) is not int or black not in (0, 1):
                    raise FriendError('schema')
                if flag != 1 or black:
                    continue
                friend = Friend(identifier(row.get('role_id'), 256), identifier(row.get('uuid'), 256),
                                identifier(row.get('scene')))
                if friend.role_id in found and found[friend.role_id] != friend:
                    raise FriendError('identity')
                found[friend.role_id] = friend
            cursor = data.get('next_baton')
            if not isinstance(cursor, str):
                raise FriendError('pagination')
            if not cursor:
                return tuple(found.values())
            if cursor in cursors or not rows:
                raise FriendError('pagination')
            cursors.add(cursor)
        raise FriendError('pagination')

    def profiles(self, account, owner, friends):
        client = self.client_factory()
        named = []
        for start in range(0, len(friends), 20):
            batch = friends[start:start+20]
            expected = {friend.scene: friend for friend in batch}
            if len(expected) != len(batch):
                raise FriendError('identity')
            data = self._request(client, BASE + '/go/user_profile/query/user' + QUERY, account,
                {'opUuid': owner['uuid'], 'uuidSceneList': [{'uuid': f.uuid, 'scene': f.scene} for f in batch],
                 'isNeedGameInfo': 1, 'isNeedMainInfo': 0, 'isNeedCommunityInfo': 0,
                 'isNeedMedal': 0, 'clientType': 1, '_t': int(self.clock())}, data_type=list)
            seen, covered = set(), set()
            for profile in data:
                if not isinstance(profile, dict) or not isinstance(profile.get('gameInfoList'), list):
                    raise FriendError('schema')
                for game in profile['gameInfoList']:
                    if not isinstance(game, dict):
                        raise FriendError('schema')
                    scene = game.get('scene')
                    if scene not in expected:
                        raise FriendError('identity')
                    covered.add(scene)
                    if game.get('gameId') != 'agame':
                        continue
                    if scene in seen:
                        raise FriendError('identity')
                    seen.add(scene)
                    friend = expected[scene]
                    named.append(Friend(friend.role_id, friend.uuid, friend.scene, label(game.get('roleName'))))
            if covered != set(expected):
                raise FriendError('schema')
        return tuple(named)

    def discover(self, account):
        owner = self.owner(account)
        friends = self.profiles(account, owner, self.relations(account, owner))
        return owner, tuple(sorted(friends, key=lambda f: (f.name.casefold(), f.role_id)))

    def current(self, account, owner, role_id):
        matches = [friend for friend in self.relations(account, owner) if friend.role_id == role_id]
        if len(matches) != 1:
            raise FriendError('not_friend')
        return matches[0]

    def history(self, account, owner, friend):
        namespace = 'friend:' + hashlib.sha256(friend.role_id.encode()).hexdigest()
        try:
            return self.fetch_records(namespace, account, friend.role_id, friend.scene, friend.name)
        except AuthExpiredError:
            # Target rejection is not proof that the viewer's login expired.
            self.owner(account)
            raise FriendError('not_visible') from None
