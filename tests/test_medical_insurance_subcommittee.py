from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mhlw import extract_related_meeting_page_links, parse_meeting_page
from shingikai.utils.html import extract_agenda_from_detail_page


class MedicalInsuranceSubcommitteeTest(unittest.TestCase):
    def test_extracts_related_legacy_meeting_pages(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "4abfb240d5d041f76d8b4cffcdc8cdbc9b761e38aa8a17238b4e599d5cf5f076.html"
        ).read_text(encoding="utf-8")
        links = extract_related_meeting_page_links(html, "https://www.mhlw.go.jp/stf/newpage_28708.html")
        self.assertEqual(
            links,
            [
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126706old.html",
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126706_old2.html",
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126706_old2_00002.html",
            ],
        )

    def test_export_splits_concatenated_agenda_from_detail_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "newpage-28708",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meeting_path = Path(tmpdir) / "councils" / "newpage-28708" / "meetings" / "2026-02-12-210.json"
            payload = json.loads(meeting_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["agenda"],
                [
                    "医療法等改正を踏まえた対応について",
                    "第４期医療費適正化計画における地域フォーミュラリについて",
                    "マイナ保険証の円滑な利用について",
                    "令和８年度予算案（保険局関係）の主な事項について（報告）",
                ],
            )

    def test_export_merges_legacy_meeting_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "newpage-28708",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meetings_dir = Path(tmpdir) / "councils" / "newpage-28708" / "meetings"
            documents_dir = Path(tmpdir) / "councils" / "newpage-28708" / "documents"
            self.assertTrue((meetings_dir / "2019-01-17-117.json").exists())
            self.assertTrue((meetings_dir / "2024-11-07-185.json").exists())
            self.assertTrue((meetings_dir / "2024-11-21-186.json").exists())
            self.assertFalse((meetings_dir / "2025-12-26-no-round.json").exists())
            discussion_doc = json.loads((documents_dir / "2025-12-26-material.json").read_text(encoding="utf-8"))
            self.assertEqual(discussion_doc["document_type"], "資料")
            self.assertEqual(
                discussion_doc["title"],
                "社会保障審議会医療保険部会における議論の整理について",
            )

    def test_parse_legacy_archive_page_with_broken_table_rows(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "b4b3f6e20245415b9f30db34a694306ef0c17afb06ed96299c39b8446e14fb84.html"
        ).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id="newpage-28708",
            source_url="https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126706_old2.html",
            title="医療保険部会",
        )

        by_round = {meeting.round_label: meeting for meeting in result.meetings}
        self.assertIn(143, by_round)
        self.assertIn(147, by_round)
        self.assertIn(149, by_round)
        self.assertIn(153, by_round)
        self.assertEqual(
            by_round[143].agenda,
            [
                "「全世代対応型の社会保障制度を構築するための健康保険法等の一部を改正する法律」の成立について",
                "「経済財政運営と改革の基本方針2021」、「成長戦略（2021年）」及び「規制改革実施計画」について",
                "オンライン資格確認等システムについて",
                "医療保険制度における新型コロナウイルス感染症の影響について",
            ],
        )

    def test_export_splits_parenthesized_nitsuite_agenda(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "newpage-28708",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meeting_path = Path(tmpdir) / "councils" / "newpage-28708" / "meetings" / "2025-08-28-196.json"
            payload = json.loads(meeting_path.read_text(encoding="utf-8"))
            self.assertEqual(
                payload["agenda"],
                [
                    "診療報酬改定の基本方針について（前回改定の振り返り）",
                    "マイナ保険証の利用促進等について",
                    "電子処方箋・電子カルテの目標設定等について（報告事項）",
                ],
            )

    def test_extract_agenda_from_detail_page_ignores_placeholder_notice(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "9aed023bc5524dbae72b41f8c3d3b375903e773d6717b3f049cfaca7e777345f.html"
        ).read_text(encoding="utf-8")
        self.assertEqual(extract_agenda_from_detail_page(html), [])

    def test_export_judo_therapy_committee_merges_legacy_meeting_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "shingi-hosho-126707",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meetings_dir = Path(tmpdir) / "councils" / "shingi-hosho-126707" / "meetings"
            self.assertTrue((meetings_dir / "2012-10-19-001.json").exists())
            self.assertTrue((meetings_dir / "2019-09-06-015.json").exists())
            self.assertTrue((meetings_dir / "2018-04-23-014.json").exists())
            self.assertTrue((meetings_dir / "2020-02-28-016.json").exists())

            payload = json.loads((meetings_dir / "2020-02-28-016.json").read_text(encoding="utf-8"))
            self.assertEqual(
                payload["agenda"],
                [
                    "柔道整復療養費検討専門委員会の議論の整理の各項目の状況等について",
                ],
            )


if __name__ == "__main__":
    unittest.main()
