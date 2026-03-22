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
    CARE_BENEFIT_INTERNAL_COMMITTEES,
    CARE_BENEFIT_SUBCOMMITTEE_ID,
    _build_care_benefit_internal_committee_council,
    _detect_care_benefit_internal_committee_meeting,
    _normalize_care_benefit_internal_committee_agenda,
    extract_related_meeting_page_links,
)
from shingikai.models.meeting import Meeting


class CareBenefitSubcommitteeSplitTest(unittest.TestCase):
    def test_extracts_related_legacy_meeting_pages(self) -> None:
        html = (
            ROOT / "fixtures" / "html" / "8647d1529087bc4b7d1d32e0b2f246b8a60b880e0d62eead62097f9cef6be622.html"
        ).read_text(encoding="utf-8")
        links = extract_related_meeting_page_links(html, "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126698_00022.html")
        self.assertEqual(
            links,
            [
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126698.html",
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126698_old2.html",
                "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126698_old.html",
            ],
        )

    def test_detect_care_benefit_internal_committee_meeting(self) -> None:
        meeting = Meeting(
            id="2024-06-25-039",
            council_id=CARE_BENEFIT_SUBCOMMITTEE_ID,
            round_label=39,
            held_on="2024-06-25",
            agenda=[
                "介護事業経営調査委員会",
                "令和6年度介護従事者処遇状況等調査の実施について",
            ],
            source_url="https://example.com",
            minutes_links=[],
            materials_links=[],
            announcement_links=[],
        )

        self.assertEqual(
            _detect_care_benefit_internal_committee_meeting(meeting),
            CARE_BENEFIT_INTERNAL_COMMITTEES["介護事業経営調査委員会"],
        )

    def test_detect_care_benefit_internal_committee_meeting_from_embedded_title(self) -> None:
        meeting = Meeting(
            id="2022-03-07-024",
            council_id=CARE_BENEFIT_SUBCOMMITTEE_ID,
            round_label=24,
            held_on="2022-03-07",
            agenda=[
                "[PDF:27KB]介護報酬改定検証・研究委員会名簿[PDF:58KB]【資料1】 令和3年度介護報酬改定の効果検証及び調査研究に係る調査の結果について"
            ],
            source_url="https://example.com",
            minutes_links=[],
            materials_links=[],
            announcement_links=[],
        )

        self.assertEqual(
            _detect_care_benefit_internal_committee_meeting(meeting),
            CARE_BENEFIT_INTERNAL_COMMITTEES["介護報酬改定検証・研究委員会"],
        )

    def test_detect_care_benefit_internal_committee_meeting_keeps_parent_when_multiple_committees_are_mixed(self) -> None:
        meeting = Meeting(
            id="2012-05-17-090",
            council_id=CARE_BENEFIT_SUBCOMMITTEE_ID,
            round_label=90,
            held_on="2012-05-17",
            agenda=[
                "介護報酬改定検証・研究委員会における議論について",
                "介護事業経営調査委員会（仮称）の設置について",
                "その他",
            ],
            source_url="https://example.com",
            minutes_links=[],
            materials_links=[],
            announcement_links=[],
        )

        self.assertIsNone(_detect_care_benefit_internal_committee_meeting(meeting))

    def test_normalize_care_benefit_internal_committee_agenda_removes_embedded_roster_title(self) -> None:
        agenda = _normalize_care_benefit_internal_committee_agenda(
            [
                "[PDF:27KB]介護報酬改定検証・研究委員会名簿[PDF:58KB]【資料1】 令和3年度介護報酬改定の効果検証及び調査研究に係る調査の結果について",
                "【資料1-1】個別調査結果",
            ],
            child_council_id=CARE_BENEFIT_INTERNAL_COMMITTEES["介護報酬改定検証・研究委員会"],
        )

        self.assertEqual(agenda, ["【資料1】 令和3年度介護報酬改定の効果検証及び調査研究に係る調査の結果について", "【資料1-1】個別調査結果"])

    def test_build_internal_committee_council(self) -> None:
        council = _build_care_benefit_internal_committee_council(
            CARE_BENEFIT_INTERNAL_COMMITTEES["介護報酬改定検証・研究委員会"]
        )

        self.assertEqual(council.title, "介護報酬改定検証・研究委員会")
        self.assertEqual(council.parent, CARE_BENEFIT_SUBCOMMITTEE_ID)

    def test_export_moves_internal_committee_meetings_into_child_councils(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    CARE_BENEFIT_SUBCOMMITTEE_ID,
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("meeting files written", result.stdout)

            parent_meetings_dir = Path(tmpdir) / "councils" / CARE_BENEFIT_SUBCOMMITTEE_ID / "meetings"
            self.assertFalse((parent_meetings_dir / "2024-06-25-039.json").exists())
            self.assertFalse((parent_meetings_dir / "2024-08-28-029.json").exists())

            business_committee_id = CARE_BENEFIT_INTERNAL_COMMITTEES["介護事業経営調査委員会"]
            business_meeting_path = (
                Path(tmpdir) / "councils" / business_committee_id / "meetings" / "2024-06-25-039.json"
            )
            business_council_path = Path(tmpdir) / "councils" / business_committee_id / "council.json"
            business_roster_path = Path(tmpdir) / "councils" / business_committee_id / "rosters" / "2024-06-25.json"

            self.assertTrue(business_council_path.exists())
            self.assertTrue(business_meeting_path.exists())
            self.assertTrue(business_roster_path.exists())

            business_meeting = json.loads(business_meeting_path.read_text(encoding="utf-8"))
            self.assertEqual(business_meeting["council_id"], business_committee_id)
            self.assertEqual(
                business_meeting["agenda"],
                [
                    "令和6年度介護従事者処遇状況等調査の実施について",
                    "その他",
                ],
            )

            validation_committee_id = CARE_BENEFIT_INTERNAL_COMMITTEES["介護報酬改定検証・研究委員会"]
            validation_meeting_path = (
                Path(tmpdir) / "councils" / validation_committee_id / "meetings" / "2024-08-28-029.json"
            )
            self.assertTrue(validation_meeting_path.exists())
            self.assertTrue(
                (Path(tmpdir) / "councils" / validation_committee_id / "meetings" / "2022-03-07-024.json").exists()
            )
            self.assertTrue(
                (Path(tmpdir) / "councils" / business_committee_id / "meetings" / "2022-03-24-034.json").exists()
            )
            self.assertTrue((parent_meetings_dir / "2012-05-17-090.json").exists())
