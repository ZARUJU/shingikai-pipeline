from __future__ import annotations

import logging
import re
import time
from urllib.request import Request, urlopen

from shingikai.utils.cache import cached_html_path


USER_AGENT = "Mozilla/5.0"
FETCH_INTERVAL_SECONDS = 1.0
logger = logging.getLogger(__name__)
WARP_REPLAY_URL_PATTERN = re.compile(
    r"^https://warp\.ndl\.go\.jp/(?P<collection>\d+)/(?P<timestamp>\d{14})(?P<modifier>[a-z_]+)?/(?P<target>.+)$"
)
_last_fetch_started_at: float | None = None


def fetch_html(url: str, timeout: int = 30) -> str:
    logger.info("fetch start: %s", url)
    request_url = resolve_html_fetch_url(url)
    _wait_for_next_fetch_window()
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        encoding = response.headers.get_content_charset()
        html = _decode_html(body, encoding)
    cache_path = cached_html_path(url)
    cache_path.write_text(html, encoding="utf-8")
    logger.info("fetch done: %s -> %s", url, cache_path)
    return html


def resolve_html_fetch_url(url: str) -> str:
    """HTML 本体を取得するための実リクエスト URL を返す。"""

    warp_html_url = build_warp_raw_html_url(url)
    if warp_html_url is not None:
        return warp_html_url
    return url


def build_warp_raw_html_url(url: str) -> str | None:
    """WARP の再生 URL を、生 HTML 取得向けの `id_` URL に変換する。"""

    match = WARP_REPLAY_URL_PATTERN.match(url)
    if match is None:
        return None

    target = _normalize_warp_target_url(match.group("target"))
    return (
        f"https://warp.ndl.go.jp/{match.group('collection')}/"
        f"{match.group('timestamp')}id_/{target}"
    )


def is_warp_replay_url(url: str) -> bool:
    """WARP の再生 URL なら `True` を返す。"""

    return WARP_REPLAY_URL_PATTERN.match(url) is not None


def _wait_for_next_fetch_window() -> None:
    global _last_fetch_started_at

    now = time.monotonic()
    if _last_fetch_started_at is not None:
        wait_seconds = FETCH_INTERVAL_SECONDS - (now - _last_fetch_started_at)
        if wait_seconds > 0:
            logger.info("throttle fetch: sleep %.3fs", wait_seconds)
            time.sleep(wait_seconds)
            now = time.monotonic()
    _last_fetch_started_at = now


def _decode_html(body: bytes, encoding: str | None) -> str:
    candidates = []
    if encoding:
        candidates.append(encoding)
    candidates.extend(["utf-8", "cp932", "shift_jis", "euc_jp", "iso2022_jp"])

    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        try:
            return body.decode(candidate)
        except UnicodeDecodeError:
            continue

    return body.decode("utf-8", errors="replace")


def _normalize_warp_target_url(target: str) -> str:
    if target.startswith(("http://", "https://")):
        return target
    return f"https://{target}"
