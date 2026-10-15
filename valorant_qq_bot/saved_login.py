"""Account-isolated 掌瓦 credentials in macOS Keychain or encrypted Linux files."""

import hashlib
import json
import os
import sys
from pathlib import Path
from contextlib import contextmanager

from .errors import ShopCheckError


SERVICE = "valorant-qq-bot.mval.daily-shop"
ACCOUNT = "personal-qq-login"
REQUIRED = ("user_id", "ticket", "openid", "access_token", "acctype")
SECRET_ENV = "VALORANT_SHOP_SECRET_KEY"
FILE_ENV = "VALORANT_SHOP_CREDENTIAL_FILE"


def _valid_account(account):
    if not isinstance(account, dict):
        return False
    required = REQUIRED
    if account.get('auth_channel') == 'wechat' and account.get('acctype') == 'wx':
        # Verified WeChat app replies can omit the third-party access token.
        # Keep the primary identity, WT and renewal credential mandatory.
        required = ('user_id', 'ticket', 'openid', 'acctype', 'ct')
        if 'access_token' in account and not isinstance(account['access_token'], str):
            return False
    return all(isinstance(account.get(field), str) and bool(account[field])
               for field in required)


def _keyring():
    try:
        import keyring
    except ImportError:
        raise ShopCheckError("请先安装项目的 auth 可选依赖") from None
    backend = keyring.get_keyring()
    if "macOS" not in type(backend).__module__:
        raise ShopCheckError("未找到 macOS 钥匙串，拒绝将登录凭据写入其他存储")
    return keyring


def _linux_store(account_key: str = ACCOUNT):
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        raise ShopCheckError("请先安装项目的 auth 可选依赖") from None
    key = os.environ.get(SECRET_ENV)
    if not key:
        raise ShopCheckError(f"Linux 持久化登录需要配置 {SECRET_ENV}")
    try:
        cipher = Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise ShopCheckError(f"{SECRET_ENV} 格式无效") from None
    if account_key == ACCOUNT:
        path = Path(os.environ.get(FILE_ENV) or "data/qq-shop-login.enc")
    else:
        root = Path(os.environ.get("VALORANT_SHOP_CREDENTIAL_DIR") or "data/credentials")
        path = root / (hashlib.sha256(account_key.encode()).hexdigest() + ".enc")
    return cipher, path


def load(account_key: str = ACCOUNT) -> dict[str, str] | None:
    try:
        if sys.platform == "darwin":
            value = _keyring().get_password(SERVICE, account_key)
        else:
            cipher, path = _linux_store(account_key)
            value = cipher.decrypt(path.read_bytes()).decode("utf-8") if path.exists() else None
    except ShopCheckError:
        raise
    except Exception:
        raise ShopCheckError("读取保存的登录失败；请检查密钥与凭据文件") from None
    if value is None:
        return None
    try:
        account = json.loads(value)
        if not _valid_account(account):
            raise ValueError
    except (ValueError, TypeError):
        raise ShopCheckError("保存的登录记录无效，请先执行 --forget 再扫码") from None
    return account


def save(account: dict[str, str], account_key: str = ACCOUNT) -> None:
    if not _valid_account(account):
        raise ShopCheckError("登录响应缺少必要字段，未保存")
    try:
        value = json.dumps(account, ensure_ascii=False)
        if sys.platform == "darwin":
            _keyring().set_password(SERVICE, account_key, value)
        else:
            cipher, path = _linux_store(account_key)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
            try:
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as output:
                    output.write(cipher.encrypt(value.encode("utf-8")))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            os.chmod(path, 0o600)
    except ShopCheckError:
        raise
    except Exception:
        raise ShopCheckError("保存登录失败") from None


def forget(account_key: str = ACCOUNT) -> None:
    if sys.platform == "darwin":
        keyring = _keyring()
        try:
            keyring.delete_password(SERVICE, account_key)
        except keyring.errors.PasswordDeleteError:
            pass
        except Exception:
            raise ShopCheckError("从 macOS 钥匙串删除登录记录失败") from None
    else:
        _, path = _linux_store(account_key)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise ShopCheckError("删除登录凭据文件失败") from None


class CredentialVault:
    """Uses the same storage implementation for CLI and account services."""
    def load(self, account_key: str):
        return load(account_key)

    def save(self, account_key: str, account: dict[str, str]):
        save(account, account_key)

    def forget(self, account_key: str):
        forget(account_key)

    @contextmanager
    def transaction_lock(self, account_key):
        """Serialize renewal/CLI operations across processes as well as threads."""
        import fcntl
        root = Path(os.environ.get('VALORANT_SHOP_CREDENTIAL_DIR') or 'data/credentials') / '.locks'
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = root / (hashlib.sha256(account_key.encode()).hexdigest() + '.lock')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
