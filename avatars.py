from __future__ import annotations

import html
import re
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image

from config import AVATAR_DIR, BASE_DIR, ensure_directories

MAX_AVATAR_BYTES = 6 * 1024 * 1024
REQUEST_TIMEOUT = 8
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def _request(url: str) -> Request:
    return Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


def _safe_name(value: str) -> str:
    clean = value.strip().lower().lstrip("@")
    clean = re.sub(r"[^a-z0-9_.-]+", "_", clean)
    return clean.strip("._-") or "creator"


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(BASE_DIR))
    except ValueError:
        return str(path)


def _read_url(url: str) -> bytes:
    with urlopen(_request(url), timeout=REQUEST_TIMEOUT) as response:
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type and "image/" not in content_type and content_type:
            raise ValueError(f"Unsupported content type: {content_type}")
        return response.read(MAX_AVATAR_BYTES + 1)


def find_tiktok_avatar_url(username: str) -> str | None:
    username = username.strip().lstrip("@")
    if not username:
        return None

    url = f"https://www.tiktok.com/@{quote(username)}"
    try:
        page = _read_url(url).decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None

    patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'"avatarLarger"\s*:\s*"([^"]+)"',
        r'"avatarMedium"\s*:\s*"([^"]+)"',
        r'"avatarThumb"\s*:\s*"([^"]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, page)
        if match:
            return html.unescape(match.group(1)).replace("\\u002F", "/")
    return None


def cache_avatar(creator_id: str, avatar_url: str | None = None) -> tuple[str, str] | None:
    username = creator_id.strip().lstrip("@")
    source_url = (avatar_url or "").strip() or find_tiktok_avatar_url(username)
    if not source_url:
        return None

    ensure_directories()
    avatar_path = AVATAR_DIR / f"{_safe_name(username)}.jpg"
    try:
        image_bytes = _read_url(source_url)
        if len(image_bytes) > MAX_AVATAR_BYTES:
            return None
        temp_path = avatar_path.with_suffix(".download")
        temp_path.write_bytes(image_bytes)
        with Image.open(temp_path) as image:
            image.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS).save(avatar_path, "JPEG", quality=90)
        temp_path.unlink(missing_ok=True)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None

    return source_url, _relative(avatar_path)


def cache_avatar_bytes(creator_id: str, image_bytes: bytes, source_label: str = "manual-upload") -> tuple[str, str] | None:
    if len(image_bytes) > MAX_AVATAR_BYTES:
        return None

    ensure_directories()
    avatar_path = AVATAR_DIR / f"{_safe_name(creator_id)}.jpg"
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.convert("RGB").resize((256, 256), Image.Resampling.LANCZOS).save(avatar_path, "JPEG", quality=90)
    except OSError:
        return None

    return source_label, _relative(avatar_path)
