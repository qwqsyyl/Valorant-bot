"""Public CDN images only; this module never sees login credentials."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
import warnings

MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 12_000_000
CDN_DOMAINS = ('qpic.cn', 'gtimg.cn', 'gtimg.com', 'qq.com')


def allowed_url(url):
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname or ''
        return (parts.scheme == 'https' and parts.port in (None, 443)
                and not parts.username and not parts.password
                and any(host == domain or host.endswith('.' + domain) for domain in CDN_DOMAINS))
    except ValueError:
        return False


class _CDNRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed_url(newurl):
            raise ValueError('Unexpected image redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_image(body):
    from PIL import Image
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(BytesIO(body)) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('Oversized product image')
            image = source.convert('RGBA')
            # Transparent padding should not make the actual weapon look tiny.
            bounds = image.getchannel('A').getbbox()
            if bounds:
                image = image.crop(bounds)
            image.thumbnail((1200, 600), Image.Resampling.LANCZOS)
            output = BytesIO()
            image.save(output, 'PNG')
            return output.getvalue()


def _load_image(url, root):
    if not allowed_url(url):
        return None
    path = root / (hashlib.sha256(url.encode()).hexdigest() + '.png')
    try:
        if path.exists() and path.stat().st_size <= MAX_BYTES:
            try:
                return normalize_image(path.read_bytes())
            except Exception:
                path.unlink(missing_ok=True)
        request = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'image/*'})
        # Dedicated opener: no account cookie jar, no auth headers.
        with build_opener(_CDNRedirect()).open(request, timeout=5) as response:
            if not allowed_url(response.url):
                return None
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            return None
        normalized = normalize_image(body)
        root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                temporary = Path(output.name)
                output.write(normalized)
            os.replace(temporary, path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        return normalized
    except Exception:
        # One bad CDN response must not prevent shop text/prices from rendering.
        return None


def load_offer_images(offers, *, cache_dir=None):
    root = Path(cache_dir or os.environ.get('VALORANT_IMAGE_CACHE', 'data/skin-images'))
    urls = tuple(dict.fromkeys(offer.image_url for offer in offers if allowed_url(offer.image_url)))
    if not urls:
        return {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        bodies = dict(zip(urls, pool.map(lambda url: _load_image(url, root), urls)))
    return {offer.identity: bodies[offer.image_url] for offer in offers
            if bodies.get(offer.image_url)}
