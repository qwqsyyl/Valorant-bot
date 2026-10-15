"""Shared synchronous core, called with asyncio.to_thread by the QQ adapter."""
import logging
import hashlib
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from .errors import ShopCheckError, AuthExpiredError, BindingError, RenewalError
from .mval_client import _refresh_delay

logger = logging.getLogger(__name__)

class ShopApplication:
    def __init__(self, repository, vault, provider, *, cache_seconds=120, reset_hour=None, clock=time.time, renewal_strategy=None):
        self.repository, self.vault, self.provider = repository, vault, provider
        self.cache_seconds, self.clock = cache_seconds, clock
        self.reset_hour = reset_hour
        self.renewal_strategy = renewal_strategy
        self._guard = threading.RLock()
        self._locks = {}
        self._refresh_retry_after = {}
        self._fetch_failures = {}

    def cached_shop_is_current(self, shop, now):
        if shop is None:
            return False
        if self.reset_hour is not None:
            return shop.current_for_day(now, self.reset_hour)
        return (0 <= now-shop.fetched_at < self.cache_seconds
                and (shop.expires_at is None or now < shop.expires_at))

    def _validate_current_day(self, shop, now):
        if self.reset_hour is not None and not shop.current_for_day(now, self.reset_hour):
            raise ShopCheckError('掌瓦尚未返回当前商店周期的数据，稍后重试；未覆盖已保存商店')

    @contextmanager
    def _lock(self, key):
        with self._guard:
            lock = self._locks.setdefault(key, threading.RLock())
        with lock:
            process_lock = self.vault.transaction_lock(key) if hasattr(self.vault, 'transaction_lock') else nullcontext()
            with process_lock:
                from .account_guard import check_available
                check_available(key)
                yield

    @staticmethod
    def _pending_key(key):
        return 'renewal-pending:' + key

    def needs_reauthorization(self, key):
        state = self.repository.auth_state(key)
        return bool(state and state['state'] == 'needs_auth' and state['next_attempt'] > self.clock())

    def _validate_login(self, key, candidate):
        if hasattr(self.provider, 'validate_login'):
            self.provider.validate_login(candidate)
            return None
        # Other data providers can validate using their normal read operation.
        shop = self.provider.fetch(key, candidate)
        self._validate_current_day(shop, self.clock())
        return shop

    def _maintain_locked(self, key, account, qq, *, force=False, recover=False):
        original_account = dict(account)
        now = self.clock()
        state = self.repository.auth_state(key) or {}
        if not force and state.get('next_attempt', 0) > now:
            if state.get('state') == 'needs_auth':
                raise AuthExpiredError('请本人重新扫码绑定')
            return account, None, False
        try:
            due = float(account.get('next_refresh_at') or 0) <= now
        except (ValueError, TypeError):
            due = True
        if not force and not recover and not due:
            return account, None, False
        pending_key = self._pending_key(key)
        validating = False
        try:
            pending = self.vault.load(pending_key)
            candidate = None
            verified = None
            if pending and pending.get('user_id') == account.get('user_id'):
                try:
                    validating = True
                    verified = self._validate_login(key, pending)
                    candidate = pending
                    candidate['next_refresh_at'] = str(int(now + _refresh_delay(candidate)))
                except AuthExpiredError:
                    # Continue with the latest rotated refresh credential, never
                    # silently fall back to a potentially consumed older CT.
                    account = pending
                    validating = False
            if candidate is None:
                if self.renewal_strategy is not None:
                    candidate = self.renewal_strategy(key, dict(account),
                        lambda value: self.vault.save(pending_key, value))
                elif hasattr(self.provider, 'refresh_checked'):
                    candidate = self.provider.refresh_checked(dict(account),
                        lambda value: self.vault.save(pending_key, value))
                else:
                    candidate = self.provider.refresh(dict(account))
                    self.vault.save(pending_key, candidate)
                validating = True
                verified = self._validate_login(key, candidate)
            if candidate.get('user_id') != account.get('user_id'):
                raise RenewalError('validate_login', 'account_mismatch', reason='validation')
            self.vault.save(key, candidate)
            self.vault.forget(pending_key)
            try:
                next_attempt = float(candidate.get('next_refresh_at') or now + _refresh_delay(candidate))
            except (ValueError, TypeError):
                next_attempt = now + _refresh_delay(candidate)
            partial = candidate.get('aux_refresh_pending') == '1'
            self.repository.set_auth_state(key, state='aux_pending' if partial else 'healthy',
                now=now, next_attempt=max(now + 60, next_attempt), success=True,
                stage=candidate.get('aux_refresh_stage', '') if partial else '',
                code=candidate.get('aux_refresh_code', '') if partial else '')
            self._fetch_failures.pop(key, None)
            logger.info('登录维护 qq=%s state=%s stage=%s code=%s', qq,
                'aux_pending' if partial else 'healthy', candidate.get('aux_refresh_stage', '') if partial else '',
                candidate.get('aux_refresh_code', '') if partial else '')
            return candidate, verified, True
        except ShopCheckError as error:
            error.validation_failed = validating
            failures = int(state.get('failures', 0)) + 1
            network = ((isinstance(error, RenewalError) and error.reason == 'network')
                       or (validating and type(error) is ShopCheckError))
            # A refresh endpoint can fail while the saved login still works.
            # Require a confirmed authentication rejection before asking for QR.
            rejected = False
            if not network:
                try:
                    self._validate_login(key, original_account)
                except AuthExpiredError:
                    rejected = True
                except ShopCheckError:
                    pass  # An unavailable validator cannot prove expiry.
            blocked = rejected and (not original_account.get('ct') or failures >= 3)
            stage = error.stage if isinstance(error, RenewalError) else 'validate_login'
            code = error.code if isinstance(error, RenewalError) else ('auth_expired' if isinstance(error, AuthExpiredError) else 'unavailable')
            delay = 86400 if blocked else min(3600, 300 * 2 ** min(failures-1, 4))
            self.repository.set_auth_state(key, state='needs_auth' if blocked else 'retry', now=now,
                next_attempt=now+delay, failures=failures, stage=stage, code=code)
            logger.warning('登录维护 qq=%s state=%s stage=%s code=%s failures=%s', qq,
                'needs_auth' if blocked else 'retry', stage, code, failures)
            raise

    def maintain_login(self, group, qq, *, force=False):
        member = self.repository.require_member(group, qq)
        key = member['account_key']
        with self._lock(key):
            self.repository.require_member(group, qq)
            try:
                account = self.vault.load(key)
            except ShopCheckError:
                now = self.clock()
                self.repository.set_auth_state(key, state='retry', now=now, next_attempt=now+300,
                    failures=1, stage='credential_store', code='unreadable')
                logger.warning('登录维护 qq=%s state=retry stage=credential_store code=unreadable', qq)
                raise
            if account is None:
                now = self.clock()
                self.repository.set_auth_state(key, state='needs_auth', now=now, next_attempt=now+86400,
                    failures=1, stage='credential_store', code='missing')
                raise AuthExpiredError('请本人重新扫码绑定')
            return self._maintain_locked(key, account, qq, force=force)[2]

    def binding_channel(self, group, qq):
        """Only expose the channel; credentials stay inside the account service."""
        from .login_channels import account_channel
        member = self.repository.member(group, qq)
        if not member:
            return 'qq'
        with self._lock(member['account_key']):
            account = self.vault.load(member['account_key']) or {}
            return account_channel(account)

    @staticmethod
    def account_key(account):
        identifier = account.get('user_id')
        if not identifier:
            raise ShopCheckError('登录缺少账号标识')
        return 'mval:' + hashlib.sha256(str(identifier).encode()).hexdigest()

    def authorize(self, group, qq, account, display_name):
        key = self.account_key(account)
        # All membership mutations share this guard; each credential operation also
        # holds the same account lock used by queries and refreshes.
        with self._guard, self._lock(key):
            with self.repository.connect() as db:
                old = db.execute('SELECT account_key FROM accounts WHERE qq_id=?', (qq,)).fetchone()
                other = db.execute('SELECT qq_id FROM accounts WHERE account_key=?', (key,)).fetchone()
            if old and old[0] != key:
                raise BindingError('此 QQ 已绑定其他账号，请先解绑原账号的所有群关系')
            if other and other[0] != qq:
                raise BindingError('游戏账号已由其他 QQ 绑定')
            shop = self.provider.fetch(key, account)
            self._validate_current_day(shop, self.clock())
            candidate = dict(account)
            candidate['authorized_at'] = str(self.clock())
            candidate['authorization_id'] = uuid.uuid4().hex
            candidate['next_refresh_at'] = str(int(self.clock()) + _refresh_delay(candidate))
            previous = self.vault.load(key)
            self.vault.save(key, candidate)
            try:
                self.repository.bind(group, qq, key, display_name)
            except Exception:
                if previous is None:
                    self.vault.forget(key)
                else:
                    self.vault.save(key, previous)
                raise
            self.repository.save_snapshot(shop)
            self.repository.enqueue(shop, now=self.clock())
            self.vault.forget(self._pending_key(key))
            self.repository.clear_auth_state(key)
            self._fetch_failures.pop(key, None)
            return shop

    def query(self, group, requester, target=None, *, force=False, refresh_now=False):
        # Caller supplies authenticated QQ/event group; never take these from text.
        target = target or requester
        member = self.repository.require_member(group, target)
        key = member['account_key']
        with self._lock(key):
            self.repository.require_member(group, target)
            now = self.clock()
            cached = self.repository.snapshot(key)
            if not force and not refresh_now and self.cached_shop_is_current(cached, now):
                self.repository.enqueue(cached, now=now)
                return cached
            failure = self._fetch_failures.get(key)
            if not force and not refresh_now and failure and now < failure[0]:
                raise failure[1]
            account = self.vault.load(key)
            if account is None:
                raise AuthExpiredError('请本人重新扫码绑定')
            if self.needs_reauthorization(key) and not refresh_now:
                raise AuthExpiredError('请本人重新扫码绑定')
            try:
                next_refresh = float(account.get('next_refresh_at') or 0)
            except (ValueError, TypeError):
                next_refresh = 0
            refreshed = False
            shop = None
            try:
                if refresh_now or (next_refresh <= now and now >= self._refresh_retry_after.get(key, 0)):
                    try:
                        candidate, shop, refreshed = self._maintain_locked(key, account, target, force=refresh_now)
                    except ShopCheckError as error:
                        if refresh_now or getattr(error, 'validation_failed', False):
                            raise
                        # Failed maintenance must not reject a still-valid login.
                        self._refresh_retry_after[key] = now + 300
                        logger.warning('主动续期失败，尝试仍保存的商店票据')
                        shop = self.provider.fetch(key, account)
                        candidate = account
                    else:
                        if shop is None:
                            shop = self.provider.fetch(key, candidate)
                else:
                    candidate = account
                    try:
                        shop = self.provider.fetch(key, candidate)
                    except AuthExpiredError:
                        candidate, shop, refreshed = self._maintain_locked(key, account, target, recover=True)
                        if not refreshed:
                            raise
                        if shop is None:
                            shop = self.provider.fetch(key, candidate)
                self._validate_current_day(shop, self.clock())
            except ShopCheckError as error:
                if self.reset_hour is not None:
                    self._fetch_failures[key] = (self.clock()+60, error)
                raise
            self.repository.save_snapshot(shop)
            self.repository.enqueue(shop, now=now)
            self._fetch_failures.pop(key, None)
            return shop

    def unlink(self, group, qq):
        with self._guard:
            member = self.repository.require_member(group, qq)
            with self._lock(member['account_key']):
                with self.repository.connect() as db:
                    count = db.execute('SELECT count(*) FROM memberships WHERE qq_id=?', (qq,)).fetchone()[0]
                if count == 1:
                    # Fail before removing the binding if credential deletion fails.
                    self.vault.forget(self._pending_key(member['account_key']))
                    self.vault.forget(member['account_key'])
                deleted_key = self.repository.unlink(group, qq)
                return bool(deleted_key)

    def add_wish(self, group, qq, name):
        member = self.repository.require_member(group, qq)
        with self._lock(member['account_key']):
            self.repository.require_member(group, qq)
            cached = self.repository.snapshot(member['account_key'])
            exact = [offer for offer in cached.offers if offer.name == name.strip()] if cached else []
            ids = {offer.goods_id for offer in exact}
            goods_id = next(iter(ids)) if len(ids) == 1 else None
            key = self.repository.add_wish(group, qq, name, goods_id)
            if cached:
                self.repository.enqueue(cached, now=self.clock())
            return key
