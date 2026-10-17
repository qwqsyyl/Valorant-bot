"""Local card backgrounds, independent of accounts, QQ, network and deployment.

Configuration is read for each render. Relative paths use the process working
directory (the repository root for the supplied launchers). Pool history is
bounded, thread safe and isolated by card type and directory; it is process local.
"""
from collections import OrderedDict
from dataclasses import dataclass
from itertools import islice
import logging
import os
from pathlib import Path
import random
import threading
from typing import Mapping

logger = logging.getLogger(__name__)
BUILTIN_BACKGROUND = Path(__file__).parent / 'assets' / 'card-background-fallback.png'
MAX_IMAGES = 50
MAX_ENTRIES = 500
MAX_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 8_000_000
EXTENSIONS = {'.jpg', '.jpeg', '.png'}


@dataclass(frozen=True)
class BackgroundConfig:
    """One complete profile; an explicit scene profile overrides the common one."""

    mode: str = 'default'
    file: str = ''
    directory: str = ''

    @classmethod
    def from_env(cls, kind: str, env: Mapping[str, str] | None = None):
        if kind not in ('shop', 'history'):
            raise ValueError('Unknown card type: ' + kind)
        env = os.environ if env is None else env
        prefix = 'VALORANT_' + kind.upper() + '_BACKGROUND'
        if not any(env.get(prefix + suffix, '').strip() for suffix in ('', '_DIR', '_MODE')):
            prefix = 'VALORANT_CARD_BACKGROUND'
        file = env.get(prefix, '').strip()
        directory = env.get(prefix + '_DIR', '').strip()
        mode = env.get(prefix + '_MODE', '').strip().lower()
        if not mode:
            # Preserve the existing directory > file priority.
            mode = 'random' if directory else ('fixed' if file else 'default')
        if mode not in ('default', 'fixed', 'random'):
            logger.warning('未知背景模式 %r；使用内置保底图', mode)
            mode = 'default'
        return cls(mode, file, directory)


def _valid_image(path: Path) -> bool:
    from PIL import Image
    try:
        if path.suffix.lower() not in EXTENSIONS or path.is_symlink() or not path.is_file():
            return False
        if not 0 < path.stat().st_size <= MAX_BYTES:
            return False
        with Image.open(path) as source:
            if source.format != ('PNG' if path.suffix.lower() == '.png' else 'JPEG') or source.width * source.height > MAX_PIXELS:
                return False
            source.verify()
        return True
    except (OSError, ValueError, Image.DecompressionBombError):
        return False


class BackgroundPool:
    """Owns only bounded no-repeat history; callers may create isolated instances."""

    def __init__(self):
        self._lock = threading.Lock()
        self._last: OrderedDict[tuple[str, str], Path] = OrderedDict()

    def candidates(self, config: BackgroundConfig, kind: str) -> list[Path]:
        if config.mode == 'default':
            return []
        if config.mode == 'fixed':
            return [Path(config.file).expanduser()] if config.file else []
        directory = Path(config.directory).expanduser() if config.directory else None
        candidates, used = [], 0
        if directory is not None:
            try:
                # Bound scanning as well as selected image count and aggregate bytes.
                with os.scandir(directory) as entries:
                    paths = sorted(Path(entry.path) for entry in islice(entries, MAX_ENTRIES))
                for path in paths:
                    if not _valid_image(path):
                        continue
                    size = path.stat().st_size
                    if used + size > MAX_BYTES:
                        continue
                    candidates.append(path)
                    used += size
                    if len(candidates) >= MAX_IMAGES:
                        break
            except OSError:
                logger.warning('%s 背景目录读取失败；尝试固定图或内置保底图', kind)
        if not candidates:
            logger.warning('%s 背景池无可用图片；尝试固定图或内置保底图', kind)
        else:
            with self._lock:
                key = (kind, str(directory.resolve()))
                previous = self._last.pop(key, None)
                choices = [path for path in candidates if path != previous] or candidates
                selected = random.choice(choices)
                candidates.remove(selected)
                random.shuffle(candidates)
                candidates.insert(0, selected)
                self._last[key] = selected
                if len(self._last) > 16:
                    self._last.popitem(last=False)
        if config.file:
            candidates.append(Path(config.file).expanduser())
        return candidates


_pool = BackgroundPool()


def choose_background(default, *, kind: str = 'shop') -> Path:
    """Compatibility selector; rendering should use load_background for recovery."""
    config = BackgroundConfig.from_env(kind)
    return next((path for path in _pool.candidates(config, kind) if _valid_image(path)), Path(default))


def load_background(kind: str, size: tuple[int, int], *, centering=(0.5, 0.5),
                    color='#171226', config: BackgroundConfig | None = None):
    """Return an RGBA canvas: custom candidates -> packaged fallback -> solid color.

    Both validation and decoding are bounded. A file disappearing or changing
    after validation is recoverable; no network, credential or database is used.
    """
    from PIL import Image, ImageOps
    config = config or BackgroundConfig.from_env(kind)
    paths = _pool.candidates(config, kind) + [BUILTIN_BACKGROUND]
    for path in dict.fromkeys(paths):
        if not _valid_image(path):
            logger.warning('%s 背景不可用：%s；继续回退', kind, path.name)
            continue
        try:
            with Image.open(path) as source:
                if source.width * source.height > MAX_PIXELS:
                    continue
                source.load()
                image = ImageOps.fit(ImageOps.exif_transpose(source).convert('RGB'), size,
                    method=Image.Resampling.LANCZOS, centering=centering).convert('RGBA')
            # Keep EXIF, ICC profiles and text comments out of generated cards.
            image.info.clear()
            logger.info('%s 卡片背景：%s', kind, path.name)
            return image
        except (OSError, ValueError, Image.DecompressionBombError):
            logger.warning('%s 背景解码失败：%s；继续回退', kind, path.name)
    logger.warning('%s 内置背景不可用；使用纯色保底', kind)
    return Image.new('RGBA', size, color)


def card_opacity(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
        return value if 0 <= value <= 255 else default
    except ValueError:
        return default
