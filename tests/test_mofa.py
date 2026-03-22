from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mofa import (
    MOFA_COUNCIL_ID,
    MOFA_INDEX_SOURCE_URL,
    MOFA_JINJI_COUNCIL_ID,
    MOFA_JINJI_MEETINGS_URL,
    fixture_html_path,
    parse_hierarchy_page,
    parse_meeting_page,
    fetch_mofa_html,
)
from shingikai.utils.io import load_council


class MofaTest(unittest.TestCase):
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
        council = load_council(MOFA_JINJI_COUNCIL_ID)
        html = fixture_html_path(MOFA_JINJI_MEETINGS_URL).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=MOFA_JINJI_COUNCIL_ID,
            source_url=council.source_urls.meetings,
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
        with tempfile.TemporaryDirectory() as tmpdir:
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
