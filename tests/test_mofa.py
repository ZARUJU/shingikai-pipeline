from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mofa import (
    MOFA_COUNCIL_ID,
    MOFA_INDEX_SOURCE_URL,
    MOFA_JINJI_COUNCIL_ID,
    MOFA_JINJI_WARP_ARCHIVE_URL,
    MOFA_JINJI_MEETINGS_URL,
    _load_mofa_html,
    build_mofa_export_plan,
    fixture_html_path,
    parse_hierarchy_page,
    parse_meeting_page,
    fetch_mofa_html,
    load_mofa_council,
)
from shingikai.utils.html import extract_agenda_from_detail_page
from shingikai.utils.io import load_council


class MofaTest(unittest.TestCase):
    CURRENT_MEETINGS_HTML = """
    <html>
      <body>
        <h1>外務人事審議会の会合の概要</h1>
        <h2>令和2年</h2>
        <ul>
          <li><a href="/mofaj/ms/prs/page26_000026.html">臨時会議（11月16日）</a></li>
          <li><a href="/mofaj/ms/prs/page26_000027.html">第608回（11月18日）</a></li>
        </ul>
        <h2>令和7年</h2>
        <ul>
          <li><a href="/mofaj/ms/prs/page25_001234.html">第667回（12月23日）</a></li>
        </ul>
      </body>
    </html>
    """
    WARP_ARCHIVE_HTML = """
    <html>
      <body>
        <h1>外務人事審議会の会合の概要</h1>
        <h2>平成31年（令和元年）</h2>
        <ul>
          <li><a href="/mofaj/ms/prs/page23_003216.html">第598回（12月20日）</a></li>
        </ul>
        <h2>平成30年</h2>
        <ul>
          <li><a href="/mofaj/ms/prs/page25_001508.html">第579回（4月25日）</a></li>
        </ul>
      </body>
    </html>
    """
    OLD_DETAIL_HTML = """
    <html>
      <body>
        <h2>第485回外務人事審議会議事要旨</h2>
        <h3>4.議題：</h3>
        <div id="noem">
          <ul>
            <li>「気候変動問題について」</li>
            <li>在勤手当検討事務局の設置について</li>
            <li>名誉総領事について</li>
            <li>前回会合の議事要旨及び議事録の承認</li>
            <li>次回開催日の決定</li>
          </ul>
        </div>
      </body>
    </html>
    """
    CURRENT_SPECIAL_DETAIL_URL = "https://www.mofa.go.jp/mofaj/ms/prs/page26_000026.html"
    CURRENT_608_DETAIL_URL = "https://www.mofa.go.jp/mofaj/ms/prs/page26_000027.html"
    WARP_598_DETAIL_URL = (
        "https://warp.ndl.go.jp/20250207/20250202091155/"
        "https://www.mofa.go.jp/mofaj/ms/prs/page23_003216.html"
    )
    WARP_579_DETAIL_URL = (
        "https://warp.ndl.go.jp/20250207/20250202091155/"
        "https://www.mofa.go.jp/mofaj/ms/prs/page25_001508.html"
    )
    CURRENT_SPECIAL_DETAIL_HTML = """
    <html>
      <body>
        <h1>外務人事審議会</h1>
        <h2>臨時会議議事要旨</h2>
        <h2>4 議題</h2>
        <ul>
          <li>行政措置要求について</li>
          <li>次回開催日の決定</li>
        </ul>
      </body>
    </html>
    """
    CURRENT_608_DETAIL_HTML = """
    <html>
      <body>
        <h1>外務人事審議会</h1>
        <h2>第608回議事要旨</h2>
        <h2>4 議題</h2>
        <ul>
          <li>在勤基本手当の改定について</li>
          <li>次回開催日の決定</li>
        </ul>
      </body>
    </html>
    """
    WARP_598_DETAIL_HTML = """
    <html>
      <body>
        <h1>外務人事審議会</h1>
        <h2>第598回議事要旨</h2>
        <h2>4 議題</h2>
        <ul>
          <li>在勤手当改定について</li>
          <li>次回開催日の決定</li>
        </ul>
      </body>
    </html>
    """
    WARP_579_DETAIL_HTML = """
    <html>
      <body>
        <h1>外務人事審議会</h1>
        <h2>第579回議事要旨</h2>
        <h2>4 議題</h2>
        <ul>
          <li>在外公館の体制強化について</li>
          <li>その他</li>
        </ul>
      </body>
    </html>
    """

    @contextmanager
    def override_mofa_fixtures(self):
        replacements = {
            MOFA_JINJI_MEETINGS_URL: self.CURRENT_MEETINGS_HTML,
            MOFA_JINJI_WARP_ARCHIVE_URL: self.WARP_ARCHIVE_HTML,
            self.CURRENT_SPECIAL_DETAIL_URL: self.CURRENT_SPECIAL_DETAIL_HTML,
            self.CURRENT_608_DETAIL_URL: self.CURRENT_608_DETAIL_HTML,
            self.WARP_598_DETAIL_URL: self.WARP_598_DETAIL_HTML,
            self.WARP_579_DETAIL_URL: self.WARP_579_DETAIL_HTML,
        }
        originals: dict[Path, str | None] = {}
        try:
            for url, html in replacements.items():
                path = fixture_html_path(url)
                originals[path] = path.read_text(encoding="utf-8") if path.exists() else None
                path.write_text(html, encoding="utf-8")
            yield
        finally:
            for path, original in originals.items():
                if original is None:
                    if path.exists():
                        path.unlink()
                    continue
                path.write_text(original, encoding="utf-8")

    def test_extract_agenda_from_old_mofa_detail_page(self) -> None:
        agenda = extract_agenda_from_detail_page(self.OLD_DETAIL_HTML)

        self.assertEqual(
            agenda,
            [
                "「気候変動問題について」",
                "在勤手当検討事務局の設置について",
                "名誉総領事について",
                "前回会合の議事要旨及び議事録の承認",
                "次回開催日の決定",
            ],
        )

    def test_fetch_mofa_html_falls_back_to_curl_on_403(self) -> None:
        with patch(
            "shingikai.councils.mofa.fetch_html",
            side_effect=HTTPError(
                url="https://www.mofa.go.jp/mofaj/ms/prs/page25_001234.html",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            ),
        ), patch("shingikai.councils.mofa.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="<html>ok</html>",
                stderr="",
            )

            html = fetch_mofa_html("https://www.mofa.go.jp/mofaj/ms/prs/page25_001234.html")

        self.assertEqual(html, "<html>ok</html>")
        self.assertEqual(mock_run.call_args.args[0][:4], ["curl", "-L", "--max-time", "30"])

    def test_load_mofa_html_refetches_when_cached_html_is_access_denied(self) -> None:
        access_denied_html = """
        <html>
          <head><title>Access Denied</title></head>
          <body>You don't have permission to access</body>
        </html>
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "mofa-current.html"
            cache_path.write_text(access_denied_html, encoding="utf-8")

            with patch("shingikai.councils.mofa.fixture_html_path", return_value=cache_path), patch(
                "shingikai.councils.mofa.fetch_mofa_html", return_value=self.CURRENT_MEETINGS_HTML
            ) as mock_fetch:
                html = _load_mofa_html(
                    url=MOFA_JINJI_MEETINGS_URL,
                    use_fixture=False,
                    force=False,
                )

        self.assertEqual(html, self.CURRENT_MEETINGS_HTML)
        mock_fetch.assert_called_once_with(MOFA_JINJI_MEETINGS_URL)

    def test_show_council_cli_prints_json(self) -> None:
        result = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), "cli.py", "council", "show", MOFA_JINJI_COUNCIL_ID],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["id"], MOFA_JINJI_COUNCIL_ID)
        self.assertEqual(payload["title"], "外務人事審議会")

    def test_parse_fixture_hierarchy(self) -> None:
        html = fixture_html_path(MOFA_INDEX_SOURCE_URL).read_text(encoding="utf-8")
        councils = parse_hierarchy_page(html, page_url=MOFA_INDEX_SOURCE_URL)

        self.assertEqual([council.council_id for council in councils], [MOFA_COUNCIL_ID, MOFA_JINJI_COUNCIL_ID])
        self.assertEqual(councils[1].parent, MOFA_COUNCIL_ID)

    def test_parse_fixture_meetings(self) -> None:
        result = parse_meeting_page(
            self.CURRENT_MEETINGS_HTML,
            council_id=MOFA_JINJI_COUNCIL_ID,
            source_url=MOFA_JINJI_MEETINGS_URL,
        )

        self.assertEqual(len(result.meetings), 3)
        self.assertEqual(result.meetings[0].id, "2020-11-16-special")
        self.assertEqual(result.meetings[1].id, "2020-11-18-608")
        self.assertEqual(result.meetings[2].id, "2025-12-23-667")

    def test_hierarchy_export_cli_prints_mofa_family(self) -> None:
        result = subprocess.run(
            [
                str(ROOT / ".venv" / "bin" / "python"),
                "cli.py",
                "hierarchy",
                "export",
                MOFA_COUNCIL_ID,
                "--use-fixture",
                "--stdout",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual([item["id"] for item in payload], [MOFA_COUNCIL_ID, MOFA_JINJI_COUNCIL_ID])

    def test_export_council_meetings_cli_writes_mofa_jinji(self) -> None:
        with self.override_mofa_fixtures(), tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    MOFA_JINJI_COUNCIL_ID,
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("5 meeting files written, 0 document files written, 0 roster files written", result.stdout)
            meetings_dir = Path(tmpdir) / "councils" / MOFA_JINJI_COUNCIL_ID / "meetings"
            meeting = json.loads((meetings_dir / "2020-11-18-608.json").read_text(encoding="utf-8"))
            self.assertEqual(meeting["agenda"], ["在勤基本手当の改定について", "次回開催日の決定"])
            old_meeting = json.loads((meetings_dir / "2019-12-20-598.json").read_text(encoding="utf-8"))
            self.assertEqual(old_meeting["agenda"], ["在勤手当改定について", "次回開催日の決定"])

    def test_build_mofa_export_plan_skips_detail_fetch_when_list_page_has_no_diff(self) -> None:
        with self.override_mofa_fixtures(), tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    MOFA_JINJI_COUNCIL_ID,
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            with patch("shingikai.councils.mofa._enrich_meetings_from_detail_pages") as mock_enrich:
                plan = build_mofa_export_plan(
                    council=load_mofa_council(MOFA_JINJI_COUNCIL_ID),
                    use_fixture=True,
                    force=False,
                    output_dir=Path(tmpdir),
                    reuse_existing_outputs=True,
                )

        self.assertTrue(plan.skip_write)
        mock_enrich.assert_not_called()
