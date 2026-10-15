"""SQLite production state; credentials are held separately by CredentialVault."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time
from .errors import BindingError
from .shop_domain import DailyShop, Wish
from .history_domain import MatchHistory

class ShopRepository:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS accounts (
                qq_id TEXT PRIMARY KEY, account_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships (
                group_id TEXT NOT NULL, qq_id TEXT NOT NULL REFERENCES accounts(qq_id) ON DELETE CASCADE,
                PRIMARY KEY(group_id, qq_id));
            CREATE TABLE IF NOT EXISTS daily_shops (
                account_key TEXT PRIMARY KEY, snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS match_history (
                account_key TEXT PRIMARY KEY REFERENCES accounts(account_key) ON DELETE CASCADE,
                snapshot TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS wishes (
                group_id TEXT NOT NULL, qq_id TEXT NOT NULL, wish_key TEXT NOT NULL,
                name TEXT NOT NULL, goods_id TEXT,
                PRIMARY KEY(group_id, qq_id, wish_key),
                FOREIGN KEY(group_id, qq_id) REFERENCES memberships(group_id, qq_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS shop_outbox (
                id INTEGER PRIMARY KEY, group_id TEXT NOT NULL, qq_id TEXT NOT NULL,
                account_key TEXT NOT NULL, cycle TEXT NOT NULL, offer_key TEXT NOT NULL,
                name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                UNIQUE(group_id, qq_id, account_key, cycle, offer_key),
                FOREIGN KEY(group_id, qq_id) REFERENCES memberships(group_id, qq_id) ON DELETE CASCADE);
            CREATE INDEX IF NOT EXISTS outbox_state ON shop_outbox(state);
            CREATE TABLE IF NOT EXISTS login_maintenance (
                account_key TEXT PRIMARY KEY REFERENCES accounts(account_key) ON DELETE CASCADE,
                state TEXT NOT NULL, last_attempt REAL NOT NULL,
                last_success REAL, next_attempt REAL NOT NULL,
                failures INTEGER NOT NULL, stage TEXT NOT NULL, code TEXT NOT NULL);
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(shop_outbox)')}
            if 'attempts' not in columns:
                db.execute('ALTER TABLE shop_outbox ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def bind(self, group, qq, account_key, name):
        with self.connect() as db:
            old = db.execute('SELECT account_key FROM accounts WHERE qq_id=?', (qq,)).fetchone()
            if old and old['account_key'] != account_key:
                raise BindingError('此 QQ 已绑定其他账号，请先解绑原账号的所有群关系')
            other = db.execute('SELECT qq_id FROM accounts WHERE account_key=?', (account_key,)).fetchone()
            if other and other['qq_id'] != qq:
                raise BindingError('游戏账号已由其他 QQ 绑定')
            db.execute('INSERT INTO accounts VALUES(?,?,?) ON CONFLICT(qq_id) DO UPDATE SET display_name=excluded.display_name', (qq, account_key, name))
            db.execute('INSERT OR IGNORE INTO memberships VALUES(?,?)', (group, qq))
            db.execute('DELETE FROM match_history WHERE account_key=?', (account_key,))

    def member(self, group, qq):
        with self.connect() as db:
            row = db.execute('SELECT a.* FROM accounts a JOIN memberships m USING(qq_id) WHERE m.group_id=? AND m.qq_id=?', (group, qq)).fetchone()
            return dict(row) if row else None

    def auth_state(self, account_key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM login_maintenance WHERE account_key=?', (account_key,)).fetchone()
            return dict(row) if row else None

    def set_auth_state(self, account_key, *, state, now, next_attempt, failures=0, stage='', code='', success=False):
        with self.connect() as db:
            old = db.execute('SELECT last_success FROM login_maintenance WHERE account_key=?', (account_key,)).fetchone()
            last_success = now if success else (old[0] if old else None)
            db.execute('INSERT INTO login_maintenance VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(account_key) DO UPDATE SET state=excluded.state,last_attempt=excluded.last_attempt,last_success=excluded.last_success,next_attempt=excluded.next_attempt,failures=excluded.failures,stage=excluded.stage,code=excluded.code',
                (account_key,state,now,last_success,next_attempt,failures,stage,code))

    def clear_auth_state(self, account_key):
        with self.connect() as db:
            db.execute('DELETE FROM login_maintenance WHERE account_key=?', (account_key,))

    def require_member(self, group, qq):
        member = self.member(group, qq)
        if not member:
            raise BindingError('目标 QQ 尚未在本群绑定账号')
        return member

    def update_display_name(self, account_key, name):
        # Repair an older mobile-role label after a validated PC-role lookup,
        # without rebinding or touching account identity and credentials.
        with self.connect() as db:
            db.execute('UPDATE accounts SET display_name=? WHERE account_key=?', (name, account_key))

    def members(self, group):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT a.* FROM accounts a JOIN memberships m USING(qq_id) WHERE m.group_id=?', (group,))]

    def unlink(self, group, qq):
        with self.connect() as db:
            member = db.execute('SELECT a.account_key FROM accounts a JOIN memberships m USING(qq_id) WHERE m.group_id=? AND m.qq_id=?', (group, qq)).fetchone()
            if not member:
                raise BindingError('本群没有你的绑定')
            db.execute('DELETE FROM memberships WHERE group_id=? AND qq_id=?', (group, qq))
            remaining = db.execute('SELECT 1 FROM memberships WHERE qq_id=?', (qq,)).fetchone()
            if not remaining:
                db.execute('DELETE FROM accounts WHERE qq_id=?', (qq,))
                db.execute('DELETE FROM daily_shops WHERE account_key=?', (member['account_key'],))
                return member['account_key']
            return None

    def snapshot(self, account_key):
        with self.connect() as db:
            row = db.execute('SELECT snapshot FROM daily_shops WHERE account_key=?', (account_key,)).fetchone()
            return DailyShop.loads(row[0]) if row else None

    def save_snapshot(self, snapshot):
        with self.connect() as db:
            db.execute('INSERT INTO daily_shops VALUES(?,?) ON CONFLICT(account_key) DO UPDATE SET snapshot=excluded.snapshot', (snapshot.account_key, snapshot.dumps()))

    def history_snapshot(self, account_key):
        with self.connect() as db:
            row = db.execute('SELECT snapshot FROM match_history WHERE account_key=?', (account_key,)).fetchone()
        if not row:
            return None
        try:
            value = MatchHistory.loads(row[0])
            return value if value.account_key == account_key and len(value.matches) <= 5 else None
        except (ValueError, TypeError, KeyError):
            return None

    def save_history(self, snapshot):
        with self.connect() as db:
            db.execute('INSERT INTO match_history VALUES(?,?) ON CONFLICT(account_key) DO UPDATE SET snapshot=excluded.snapshot',
                       (snapshot.account_key, snapshot.dumps()))

    def add_wish(self, group, qq, name, goods_id=None):
        self.require_member(group, qq)
        name = name.strip()
        if not name or len(name) > 100:
            raise BindingError('请输入 1–100 字的完整皮肤名称')
        key = 'id:' + goods_id if goods_id else 'name:' + name
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO wishes VALUES(?,?,?,?,?)', (group, qq, key, name, goods_id))
        return key

    def remove_wish(self, group, qq, key):
        self.require_member(group, qq)
        with self.connect() as db:
            wish = db.execute('SELECT name,goods_id FROM wishes WHERE group_id=? AND qq_id=? AND wish_key=?', (group, qq, key)).fetchone()
            if wish:
                db.execute('UPDATE shop_outbox SET state="cancelled" WHERE group_id=? AND qq_id=? AND state="pending" AND (offer_key=? OR name=?)', (group, qq, key, wish['name']))
            result = db.execute('DELETE FROM wishes WHERE group_id=? AND qq_id=? AND wish_key=?', (group, qq, key))
            return bool(result.rowcount)

    def wishes(self, group, qq):
        self.require_member(group, qq)
        with self.connect() as db:
            return tuple(Wish(row['wish_key'], row['name'], row['goods_id']) for row in db.execute('SELECT * FROM wishes WHERE group_id=? AND qq_id=? ORDER BY wish_key', (group, qq)))

    def enqueue(self, snapshot, *, now=None):
        now = time.time() if now is None else now
        if not snapshot.cycle or snapshot.expires_at is None or snapshot.expires_at <= now:
            return 0
        with self.connect() as db:
            rows = db.execute('SELECT w.* FROM wishes w JOIN accounts a USING(qq_id) WHERE a.account_key=?', (snapshot.account_key,)).fetchall()
            added = 0
            for row in rows:
                wish = Wish(row['wish_key'], row['name'], row['goods_id'])
                for offer in snapshot.offers:
                    if wish.matches(offer):
                        added += db.execute('INSERT OR IGNORE INTO shop_outbox(group_id,qq_id,account_key,cycle,offer_key,name,created_at) VALUES(?,?,?,?,?,?,?)', (row['group_id'], row['qq_id'], snapshot.account_key, snapshot.cycle, offer.identity, offer.name, now)).rowcount
            return added

    def claim(self, group, *, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            # A crash after sending leaves uncertainty, never silently auto-resend it.
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute('SELECT * FROM shop_outbox WHERE group_id=? AND state="pending" ORDER BY id', (group,)).fetchall()
            valid = []
            for row in rows:
                cached = db.execute('SELECT snapshot FROM daily_shops WHERE account_key=?', (row['account_key'],)).fetchone()
                shop = DailyShop.loads(cached[0]) if cached else None
                if shop and shop.cycle == row['cycle'] and shop.expires_at and shop.expires_at > now:
                    valid.append(dict(row))
                    state = 'sending'
                else:
                    state = 'cancelled'
                db.execute('UPDATE shop_outbox SET state=? WHERE id=?', (state, row['id']))
            return valid

    def finish(self, ids, state):
        if state not in ('sent', 'pending', 'unknown'):
            raise ValueError('invalid delivery state')
        with self.connect() as db:
            if state == 'pending':
                db.executemany('UPDATE shop_outbox SET attempts=attempts+1, state=CASE WHEN attempts+1>=3 THEN "failed" ELSE "pending" END WHERE id=? AND state="sending"', [(identifier,) for identifier in ids])
            else:
                db.executemany('UPDATE shop_outbox SET state=? WHERE id=? AND state="sending"', [(state, identifier) for identifier in ids])

    def recover_interrupted(self):
        with self.connect() as db:
            db.execute('UPDATE shop_outbox SET state="unknown" WHERE state="sending"')

    def outbox_states(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT id,state FROM shop_outbox ORDER BY id')]
