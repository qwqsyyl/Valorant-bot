"""Short account lease: experiments exclude every regular account operation."""
import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from .errors import ShopCheckError

_access = ContextVar('auth_test_access', default=None)


def lease_path(key):
    root = Path(os.environ.get('VALORANT_SHOP_CREDENTIAL_DIR') or 'data/credentials')
    return root / '.experiments' / (hashlib.sha256(key.encode()).hexdigest() + '.json')


def read_lease(key):
    try:
        data = json.loads(lease_path(key).read_text())
        if not isinstance(data, dict) or not isinstance(data.get('session'), str):
            raise ValueError
        if not isinstance(data.get('expires_at'), (int, float)):
            raise ValueError
        return data
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError):
        raise ShopCheckError('账号测试状态无法读取，请联系管理员') from None


def check_available(key):
    lease = read_lease(key)
    if lease is None or float(lease.get('expires_at', 0)) <= time.time():
        return
    if _access.get() != (key, lease['session']):
        raise ShopCheckError('该账号正在进行登录测试，请稍后再试')


@contextmanager
def access(key, session):
    marker = _access.set((key, session))
    try:
        yield
    finally:
        _access.reset(marker)


def create(key, session, *, minutes=90):
    # Caller holds the existing cross-process account lock.
    check_available(key)
    if not 1 <= minutes <= 120:
        raise ValueError('测试隔离限时 1 至 120 分钟')
    path = lease_path(key)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'session': session, 'expires_at': time.time() + minutes * 60}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def require(key, session):
    lease = read_lease(key)
    if not lease or lease['session'] != session or lease['expires_at'] <= time.time():
        raise ShopCheckError('测试隔离已结束，请重新准备实验')


def release(key, session):
    lease = read_lease(key)
    if lease and lease['session'] == session:
        lease_path(key).unlink(missing_ok=True)
