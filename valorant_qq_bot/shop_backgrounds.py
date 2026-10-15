"""Bounded local background pool; no network or account credentials."""
import logging
import os
from pathlib import Path
import random
import threading

logger = logging.getLogger(__name__)
MAX_IMAGES = 50
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 4_000_000
_lock = threading.Lock()
_last = None
_verified = {}


def choose_background(default):
    global _last
    directory = os.environ.get('VALORANT_CARD_BACKGROUND_DIR')
    if not directory:
        return Path(default)
    from PIL import Image
    with _lock:
        candidates, used = [], 0
        try:
            paths = sorted(Path(directory).iterdir())
        except OSError:
            return Path(default)
        active = set()
        for path in paths:
            if path.suffix.lower() not in ('.jpg', '.jpeg', '.png') or path.is_symlink():
                continue
            try:
                stat = path.stat()
                if not path.is_file() or not 0 < stat.st_size <= MAX_BYTES:
                    continue
                key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
                active.add(key)
                valid = _verified.get(key)
                if valid is None:
                    try:
                        with Image.open(path) as source:
                            valid = (source.format in ('JPEG', 'PNG') and source.width >= 1600
                                     and source.height >= 900 and source.width * 9 == source.height * 16
                                     and source.width * source.height <= MAX_PIXELS)
                            source.verify()
                    except (OSError, ValueError, Image.DecompressionBombError):
                        valid = False
                    _verified[key] = valid
                if valid and used + stat.st_size <= MAX_BYTES:
                    candidates.append(path)
                    used += stat.st_size
                if len(candidates) >= MAX_IMAGES:
                    break
            except OSError:
                continue
        # Bound validation state when files are replaced or removed.
        for key in list(_verified):
            if key not in active:
                del _verified[key]
        if not candidates:
            return Path(default)
        choices = [path for path in candidates if str(path.resolve()) != _last] or candidates
        selected = random.choice(choices)
        _last = str(selected.resolve())
        logger.info('商店卡片背景：%s；图片池=%d', selected.name, len(candidates))
        return selected


def card_opacity(name, default):
    try:
        value = int(os.environ.get(name, str(default)))
        return value if 0 <= value <= 255 else default
    except ValueError:
        return default
