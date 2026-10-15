"""Ephemeral friend choices scoped to the viewer, group and authorization."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import re
import secrets
import threading
import time
from .errors import AuthExpiredError, BindingError
from .friend_provider import FriendError, MvalFriendProvider


@dataclass(frozen=True)
class Selection:
    code: str
    expires_at: float
    friends: tuple = field(repr=False)
    total: int
    matched: int
    account_key: str = field(repr=False)
    generation: str = field(repr=False)
    owner_role: str = field(repr=False)


@dataclass(frozen=True)
class FriendResult:
    selection: Selection = field(repr=False)
    friend: object = field(repr=False)
    history: object


class FriendApplication:
    def __init__(self, core, provider=None, *, clock=time.time, ttl=300):
        self.core, self.clock, self.ttl = core, clock, ttl
        self.provider = provider or MvalFriendProvider(clock=clock)
        self._sessions, self._failures = {}, {}
        self._guard = threading.RLock()

    def invalidate(self, group, requester):
        with self._guard:
            self._sessions.pop((group, requester), None)

    @contextmanager
    def _account(self, group, requester):
        key = self.core.repository.require_member(group, requester)['account_key']
        with self.core._lock(key):
            self._member(group, requester, key)
            account = self.core.vault.load(key)
            if account is None:
                raise AuthExpiredError('请重新授权')
            yield key, account

    def _member(self, group, requester, key):
        if self.core.repository.require_member(group, requester)['account_key'] != key:
            raise BindingError('查询期间绑定已变化')

    def _run(self, key, account, requester, operation):
        generation = str(account.get('authorization_id') or '')
        with self._guard:
            failure = self._failures.get(key)
        if failure and failure[0] > self.clock() and failure[1] == generation:
            raise FriendError('cooldown')
        try:
            try:
                return operation(account)
            except AuthExpiredError:
                candidate, _, refreshed = self.core._maintain_locked(key, account, requester, recover=True)
                if not refreshed:
                    raise
                return operation(candidate)
        except Exception as error:
            # Usage and relationship changes must not block unrelated targets.
            if getattr(error, 'reason', '') in {'transport', 'schema', 'upstream', 'pagination', 'identity'}:
                with self._guard:
                    self._failures = {k: v for k, v in self._failures.items() if v[0] > self.clock()}
                    if len(self._failures) >= 128:
                        self._failures.pop(next(iter(self._failures)))
                    self._failures[key] = (self.clock()+60, generation)
            raise

    def list(self, group, requester, keyword=''):
        if len(keyword) > 60:
            raise FriendError('usage')
        self.invalidate(group, requester)
        with self._account(group, requester) as (key, account):
            owner, friends = self._run(key, account, requester, self.provider.discover)
            matched = tuple(f for f in friends if keyword.strip().casefold() in f.name.casefold())
            # Recovery preserves authorization_id; explicit reauthorization changes it.
            current = self.core.vault.load(key)
            if current is None:
                raise AuthExpiredError('请重新授权')
            selection = Selection(secrets.token_hex(3).upper(), self.clock()+self.ttl, matched[:20],
                len(friends), len(matched), key, str(current.get('authorization_id') or ''), owner['game_role_id'])
            self._member(group, requester, key)
            with self._guard:
                self._sessions = {k: v for k, v in self._sessions.items() if v.expires_at > self.clock()}
                if len(self._sessions) >= 128:
                    self._sessions.pop(next(iter(self._sessions)))
                self._sessions[group, requester] = selection
            return selection

    def _selection(self, group, requester, code=None):
        with self._guard:
            selection = self._sessions.get((group, requester))
        if selection is None or selection.expires_at <= self.clock() or (code and selection.code != code):
            raise FriendError('selection_expired')
        return selection

    def _validate_locked(self, group, requester, selection, key, account):
        self._member(group, requester, key)
        if (self._selection(group, requester).code != selection.code or key != selection.account_key
                or str(account.get('authorization_id') or '') != selection.generation):
            raise FriendError('selection_expired')

    def query(self, group, requester, token):
        match = re.fullmatch(r'([A-Fa-f0-9]{6})-([1-9][0-9]?)', token.strip())
        if match is None:
            raise FriendError('usage')
        selection = self._selection(group, requester, match[1].upper())
        index = int(match[2])-1
        if index >= len(selection.friends):
            raise FriendError('usage')
        selected = selection.friends[index]
        with self._account(group, requester) as (key, account):
            self._validate_locked(group, requester, selection, key, account)
            def fetch(viewer):
                owner = self.provider.owner(viewer)
                if owner['game_role_id'] != selection.owner_role:
                    raise FriendError('selection_expired')
                friend = self.provider.current(viewer, owner, selected.role_id)
                named = self.provider.profiles(viewer, owner, (friend,))
                if len(named) != 1:
                    raise FriendError('pc_role_missing')
                result = self.provider.history(viewer, owner, named[0])
                self.provider.current(viewer, owner, selected.role_id)
                return FriendResult(selection, named[0], result)
            result = self._run(key, account, requester, fetch)
            self._validate_locked(group, requester, selection, key, self.core.vault.load(key) or {})
            return result

    def validate_list(self, group, requester, selection):
        with self._account(group, requester) as (key, account):
            self._validate_locked(group, requester, selection, key, account)

    def validate_delivery(self, group, requester, result):
        with self._account(group, requester) as (key, account):
            self._validate_locked(group, requester, result.selection, key, account)
            def check(viewer):
                owner = self.provider.owner(viewer)
                if owner['game_role_id'] != result.selection.owner_role:
                    raise FriendError('selection_expired')
                self.provider.current(viewer, owner, result.friend.role_id)
            self._run(key, account, requester, check)
