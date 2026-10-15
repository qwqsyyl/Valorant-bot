"""History queries share production membership, credentials, and account locks."""
import time
from .errors import AuthExpiredError, BindingError, ShopCheckError
from .history_provider import HistoryError, MvalHistoryProvider


class HistoryApplication:
    def __init__(self, core, provider=None, *, clock=time.time, cache_seconds=60):
        self.core = core
        self.provider = provider or MvalHistoryProvider(clock=clock)
        self.clock, self.cache_seconds = clock, cache_seconds
        self._failures = {}

    def access(self, group, requester, target, *, account_key=None):
        self.core.repository.require_member(group, requester)
        member = self.core.repository.require_member(group, target)
        if account_key is not None and member['account_key'] != account_key:
            raise BindingError('查询期间账号绑定已变化，请重新查询')
        return member

    def query(self, group, requester, target=None):
        target = target or requester
        member = self.access(group, requester, target)
        key = member['account_key']
        with self.core._lock(key):
            self.access(group, requester, target, account_key=key)
            account = self.core.vault.load(key)
            if account is None:
                raise AuthExpiredError('请本人重新扫码绑定')
            generation = str(account.get('authorization_id') or '')
            cached = self.core.repository.history_snapshot(key)
            now = self.clock()
            if cached and cached.authorization_id == generation and 0 <= now - cached.fetched_at < self.cache_seconds:
                return cached
            failure = self._failures.get(key)
            if failure and failure[1] == generation and now < failure[0]:
                raise failure[2]
            try:
                try:
                    result = self.provider.fetch(key, account, member['display_name'])
                except AuthExpiredError:
                    # Only a confirmed auth rejection enters the same WT
                    # recovery used by the shop; ordinary failures never renew.
                    candidate, _, refreshed = self.core._maintain_locked(key, account, target, recover=True)
                    if not refreshed:
                        raise
                    result = self.provider.fetch(key, candidate, member['display_name'])
                if result.account_key != key or len(result.matches) > 5:
                    raise HistoryError('identity')
                self.access(group, requester, target, account_key=key)
                self.core.repository.update_display_name(key, result.display_name)
                self.core.repository.save_history(result)
                self._failures.pop(key, None)
                return result
            except ShopCheckError as error:
                self._failures[key] = (self.clock() + 60, generation, error)
                raise
