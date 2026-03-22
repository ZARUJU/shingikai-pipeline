from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.utils.html import extract_agenda_from_detail_page


class FundManagementSubcommitteeTest(unittest.TestCase):
    def test_extract_agenda_from_detail_page_keeps_inline_text_before_audience_notice(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "eb41f58436032f7aa852e8337b41e5b67b55528b7310d300cc06bba818211639.html"
        ).read_text(encoding="utf-8")

        self.assertEqual(
            extract_agenda_from_detail_page(html),
            [
                "ＧＰＩＦの次期中期目標等に関する議論の進め方について",
                "ＧＰＩＦの現状の取組及び課題について（ＧＰＩＦへのヒアリング）",
            ],
        )

    def test_export_uses_actual_agenda_instead_of_audience_notice(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "shingi-hosho-439756",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meeting_path = Path(tmpdir) / "councils" / "shingi-hosho-439756" / "meetings" / "2024-10-07-022.json"
            payload = json.loads(meeting_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["agenda"],
                [
                    "ＧＰＩＦの次期中期目標等に関する議論の進め方について",
                    "ＧＰＩＦの現状の取組及び課題について（ＧＰＩＦへのヒアリング）",
                ],
            )


if __name__ == "__main__":
    unittest.main()
