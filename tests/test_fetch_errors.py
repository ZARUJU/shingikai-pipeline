from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import shingikai.cli as cli_module
from shingikai.fetch_errors import load_fetch_errors


class FetchErrorCacheTest(unittest.TestCase):
    def test_optional_404_is_recorded_and_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            error_path = Path(tmpdir) / "fetch_errors.json"
            original_has_recorded_404 = cli_module.has_recorded_404
            original_record_fetch_error = cli_module.record_fetch_error
            original_clear_fetch_error = cli_module.clear_fetch_error

            cli_module.has_recorded_404 = lambda url: original_has_recorded_404(url, path=error_path)
            cli_module.record_fetch_error = (
                lambda url, *, status_code, reason: original_record_fetch_error(
                    url,
                    status_code=status_code,
                    reason=reason,
                    path=error_path,
                )
            )
            cli_module.clear_fetch_error = lambda url: original_clear_fetch_error(url, path=error_path)
            try:
                call_count = {"count": 0}

                def failing_fetcher() -> str:
                    call_count["count"] += 1
                    raise HTTPError("https://example.com/missing", 404, "Not Found", hdrs=None, fp=None)

                result = cli_module._load_cached_html(
                    url="https://example.com/missing",
                    path=Path(tmpdir) / "dummy.html",
                    fetcher=failing_fetcher,
                    use_fixture=False,
                    force=False,
                    required=False,
                )
                self.assertIsNone(result)
                self.assertEqual(call_count["count"], 1)

                recorded = load_fetch_errors(path=error_path)
                self.assertIn("https://example.com/missing", recorded)
                self.assertEqual(recorded["https://example.com/missing"]["status_code"], 404)

                result = cli_module._load_cached_html(
                    url="https://example.com/missing",
                    path=Path(tmpdir) / "dummy.html",
                    fetcher=failing_fetcher,
                    use_fixture=False,
                    force=False,
                    required=False,
                )
                self.assertIsNone(result)
                self.assertEqual(call_count["count"], 1)
            finally:
                cli_module.has_recorded_404 = original_has_recorded_404
                cli_module.record_fetch_error = original_record_fetch_error
                cli_module.clear_fetch_error = original_clear_fetch_error


if __name__ == "__main__":
    unittest.main()
