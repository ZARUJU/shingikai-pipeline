from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mhlw import _load_cached_html
from shingikai.utils.cache import is_cache_fresh
from shingikai.utils.fetch import build_warp_raw_html_url, fetch_html, is_warp_replay_url


class _FakeResponse:
    def __init__(self, body: bytes, *, charset: str | None = "utf-8") -> None:
        self._body = io.BytesIO(body)
        self.headers = Message()
        if charset is not None:
            self.headers["Content-Type"] = f"text/html; charset={charset}"

    def read(self) -> bytes:
        return self._body.read()

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class FetchUtilsTest(unittest.TestCase):
    def test_is_cache_fresh_uses_mtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.html"
            path.write_text("ok", encoding="utf-8")
            fresh_timestamp = (datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()
            os.utime(path, (fresh_timestamp, fresh_timestamp))

            self.assertTrue(is_cache_fresh(path, max_age_hours=24))
            self.assertFalse(is_cache_fresh(path, max_age_hours=0))

    def test_build_warp_raw_html_url_adds_id_modifier(self) -> None:
        url = "https://warp.ndl.go.jp/20240620/20240601094408/www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"
        self.assertEqual(
            build_warp_raw_html_url(url),
            "https://warp.ndl.go.jp/20240620/20240601094408id_/https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html",
        )

    def test_build_warp_raw_html_url_drops_existing_modifier(self) -> None:
        url = "https://warp.ndl.go.jp/20240620/20240601094408js_/https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"
        self.assertEqual(
            build_warp_raw_html_url(url),
            "https://warp.ndl.go.jp/20240620/20240601094408id_/https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html",
        )

    def test_is_warp_replay_url(self) -> None:
        self.assertTrue(
            is_warp_replay_url(
                "https://warp.ndl.go.jp/20240620/20240601094408/www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"
            )
        )
        self.assertFalse(is_warp_replay_url("https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"))

    def test_fetch_html_uses_raw_warp_url_but_caches_by_original_url(self) -> None:
        original_url = "https://warp.ndl.go.jp/20240620/20240601094408/www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"
        expected_request_url = (
            "https://warp.ndl.go.jp/20240620/20240601094408id_/https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "warp.html"
            with (
                patch("shingikai.utils.fetch.cached_html_path", return_value=cache_path),
                patch("shingikai.utils.fetch.urlopen", return_value=_FakeResponse(b"<html>ok</html>")) as mock_urlopen,
            ):
                html = fetch_html(original_url)
                self.assertEqual(cache_path.read_text(encoding="utf-8"), "<html>ok</html>")

        self.assertEqual(html, "<html>ok</html>")
        request = mock_urlopen.call_args.args[0]
        self.assertEqual(request.full_url, expected_request_url)

    def test_fetch_html_waits_one_second_between_requests(self) -> None:
        monotonic_values = iter([100.0, 100.2, 101.2])

        with (
            patch("shingikai.utils.fetch.cached_html_path", return_value=Path(tempfile.gettempdir()) / "unused.html"),
            patch("shingikai.utils.fetch.urlopen", return_value=_FakeResponse(b"<html>ok</html>")),
            patch("shingikai.utils.fetch.time.monotonic", side_effect=lambda: next(monotonic_values)),
            patch("shingikai.utils.fetch.time.sleep") as mock_sleep,
            patch("shingikai.utils.fetch._last_fetch_started_at", None),
        ):
            fetch_html("https://example.com/1")
            fetch_html("https://example.com/2")

        mock_sleep.assert_called_once()
        self.assertAlmostEqual(mock_sleep.call_args.args[0], 0.8)

    def test_load_cached_html_prefers_fixture_without_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fixture.html"
            path.write_text("<html>fixture</html>", encoding="utf-8")

            fetcher_called = False

            def fetcher() -> str:
                nonlocal fetcher_called
                fetcher_called = True
                return "<html>live</html>"

            html = _load_cached_html(
                url="https://example.com",
                path=path,
                fetcher=fetcher,
                use_fixture=True,
                force=False,
            )

        self.assertEqual(html, "<html>fixture</html>")
        self.assertFalse(fetcher_called)

    def test_load_cached_html_refetches_stale_cache_when_refresh_hours_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cache.html"
            path.write_text("<html>stale</html>", encoding="utf-8")
            stale_timestamp = (datetime.now(timezone.utc) - timedelta(hours=48)).timestamp()
            os.utime(path, (stale_timestamp, stale_timestamp))

            html = _load_cached_html(
                url="https://example.com",
                path=path,
                fetcher=lambda: "<html>live</html>",
                use_fixture=False,
                force=False,
                max_cache_age_hours=24,
            )

        self.assertEqual(html, "<html>live</html>")


if __name__ == "__main__":
    unittest.main()
