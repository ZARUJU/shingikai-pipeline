from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mhlw import (
    SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID,
    fixture_html_path,
    get_mhlw_council_rule,
    parse_meeting_page,
)
from shingikai.utils.html import extract_agenda_from_detail_page
from shingikai.utils.io import load_council


class SocialSecurityCouncilStatisticsSubcommitteeTest(unittest.TestCase):
    def test_build_council_matches_saved_json(self) -> None:
        council = load_council("social-security-council-statistics-subcommittee")
        saved = load_council("social-security-council-statistics-subcommittee")

        self.assertEqual(council.to_dict(), saved.to_dict())
        self.assertEqual(council.title, "統計分科会")
        self.assertEqual(council.parent, "social-security-council")

    def test_parse_current_fixture_meetings(self) -> None:
        council = load_council("social-security-council-statistics-subcommittee")
        html = fixture_html_path(council.source_urls.meetings).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID,
            source_url=council.source_urls.meetings,
            title=council.title,
        )

        self.assertEqual(len(result.meetings), 7)
        self.assertEqual(len(result.documents), 0)
        self.assertEqual(result.meetings[0].id, "2025-08-01-030")
        self.assertEqual(
            result.meetings[0].agenda,
            [
                "令和8年医療施設調査の調査計画案について",
                "令和8年患者調査の調査計画案について",
                "人口動態調査の調査計画案について",
                "その他",
            ],
        )
        self.assertEqual(result.meetings[-1].id, "2019-08-28-024")

    def test_parse_legacy_fixture_meetings(self) -> None:
        council = load_council("social-security-council-statistics-subcommittee")
        legacy_source_url = get_mhlw_council_rule(council.council_id).legacy_meeting_page_urls[0]
        html = fixture_html_path(legacy_source_url).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID,
            source_url=council.source_urls.meetings,
            title=council.title,
        )

        self.assertEqual(len(result.meetings), 29)
        self.assertEqual(len(result.documents), 0)
        self.assertEqual(result.meetings[0].id, "2024-05-29-029")
        self.assertEqual(result.meetings[-1].id, "2001-07-30-001")
        self.assertEqual(
            result.meetings[-1].agenda,
            [
                "統計分科会の運営について",
                "「疾病、傷害及び死因分類」について",
                "その他",
            ],
        )
        round_15 = next(meeting for meeting in result.meetings if meeting.round_label == 15)
        self.assertEqual(
            round_15.agenda,
            [
                "厚生労働統計の整備に関する検討会について",
                "平成22年国民生活基礎調査について",
                "WHO-FIC韓国会議報告について",
                "ICF-CYの刊行について",
                "ICFシンポジウムの報告について",
                "その他",
            ],
        )
        self.assertTrue(result.meetings[-1].source_url.startswith("https://warp.ndl.go.jp/"))

    def test_parse_current_fixture_round_25_agenda(self) -> None:
        council = load_council("social-security-council-statistics-subcommittee")
        html = fixture_html_path(council.source_urls.meetings).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID,
            source_url=council.source_urls.meetings,
            title=council.title,
        )
        round_25 = next(meeting for meeting in result.meetings if meeting.round_label == 25)

        self.assertEqual(
            round_25.agenda,
            [
                "人口動態調査の調査計画案について",
                "基準人口の改訂について",
                "新型コロナウイルス感染症を踏まえた厚生労働省所管統計調査の対応について",
                "その他",
            ],
        )

    def test_extract_detail_page_agenda_keeps_icd11_and_year_parentheses(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "7c9cf91785e28ba02c02698de00b7a22abdcc9c0751470b497bda6e2c1390743.html"
        ).read_text(encoding="utf-8")
        agenda = extract_agenda_from_detail_page(html)
        self.assertEqual(
            agenda,
            [
                "委員長の選出について",
                "WHO-FICネットワーク年次会議（ICF関連）の報告について",
                "ICD-11 V章の和訳案について",
                "その他",
            ],
        )

    def test_extract_detail_page_agenda_strips_spaced_heading(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "ab604a1b6ed3c105f0a80e45e855e0c2687a7213d86adaeb1ad93ad8cbd8aa94.html"
        ).read_text(encoding="utf-8")
        agenda = extract_agenda_from_detail_page(html)
        self.assertEqual(
            agenda,
            [
                "ＩＣＤ－11Ｖ章の和訳について",
                "ＷＨＯ－ＦＩＣネットワーク年次会議（2019カナダ会議）の報告について",
                "生活機能分類普及推進検討ワーキンググループ令和元年度の活動状況報告について",
            ],
        )

    def test_export_meetings_cli_writes_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "social-security-council-statistics-subcommittee",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("30 meeting files written, 0 document files written, ", result.stdout)
            meetings_dir = Path(tmpdir) / "councils" / "social-security-council-statistics-subcommittee" / "meetings"
            documents_dir = Path(tmpdir) / "councils" / "social-security-council-statistics-subcommittee" / "documents"
            rosters_dir = Path(tmpdir) / "councils" / "social-security-council-statistics-subcommittee" / "rosters"
            meeting_files = sorted(meetings_dir.glob("*.json"))
            document_files = sorted(documents_dir.glob("*.json"))
            roster_files = sorted(rosters_dir.glob("*.json"))

            self.assertEqual(len(meeting_files), 30)
            self.assertEqual(len(document_files), 0)
            self.assertGreaterEqual(len(roster_files), 1)
            self.assertTrue((meetings_dir / "2001-07-30-001.json").exists())
            self.assertTrue((meetings_dir / "2025-08-01-030.json").exists())
            self.assertTrue((rosters_dir / "2025-08-01.json").exists())

            payload = json.loads((meetings_dir / "2001-07-30-001.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["council_id"], "social-security-council-statistics-subcommittee")
            self.assertEqual(payload["round_label"], 1)
            self.assertTrue(payload["source_url"].startswith("https://warp.ndl.go.jp/"))


if __name__ == "__main__":
    unittest.main()
