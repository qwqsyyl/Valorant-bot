"""Create the Linux encryption key once without printing it or overwriting it."""
import os
from pathlib import Path
from cryptography.fernet import Fernet

def main():
    root = Path('data')
    root.mkdir(mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    key_file = root / 'core.env'
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print('已有密钥配置，保持原文件。')
        return
    with os.fdopen(fd,'w') as output:
        output.write('VALORANT_SHOP_SECRET_KEY=' + Fernet.generate_key().decode() + '\n')
        output.flush()
        os.fsync(output.fileno())
    print('已创建私有密钥配置；不会在终端显示密钥。')

if __name__ == '__main__': main()
