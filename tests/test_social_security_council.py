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
    MHLW_INDEX_SOURCE_URL,
    SOCIAL_SECURITY_COUNCIL_ID,
    extract_roster_links_from_material_page,
    fixture_html_path,
    get_mhlw_hierarchy_rule,
    parse_hierarchy_page,
    parse_meeting_page,
)
from shingikai.utils.cache import cached_html_path
from shingikai.cli import build_parser
from shingikai.utils.html import extract_agenda_from_detail_page
from shingikai.utils.io import load_council
from shingikai.utils.normalize import is_roster_link_title


class SocialSecurityCouncilTest(unittest.TestCase):
    HIERARCHY_SNIPPET = """
    <ul class="m-listLink">
      <li><span class="m-listLink__link"><a href="/stf/shingi/shingi-hosho_126692.html">社会保障審議会</a></span><ul class="m-listLink">
        <li><span class="m-listLink__link"><a href="/stf/shingi/shingi-hosho_126693.html">統計分科会</a></span><ul class="m-listLink">
          <li><span class="m-listLink__link"><a href="/stf/shingi/shingi-hosho_164149.html">統計分科会疾病、傷害及び死因分類部会</a></span></li>
        </ul></li>
        <li><span class="m-listLink__link"><a href="/stf/shingi/shingi-hosho_126696.html">医療分科会</a></span></li>
      </ul></li>
    </ul>
    """

    def test_build_council_matches_saved_json(self) -> None:
        council = load_council("social-security-council")
        saved = load_council("social-security-council")

        self.assertEqual(council.to_dict(), saved.to_dict())

    def test_show_council_cli_prints_json(self) -> None:
        result = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), "cli.py", "council", "show", "social-security-council"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertEqual(payload["id"], "social-security-council")
        self.assertEqual(payload["title"], "社会保障審議会")

    def test_show_all_councils_cli_prints_json_array(self) -> None:
        result = subprocess.run(
            [str(ROOT / ".venv" / "bin" / "python"), "cli.py", "council", "show", "all"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )

        payload = json.loads(result.stdout)
        self.assertIsInstance(payload, list)
        ids = {item["id"] for item in payload}
        self.assertIn("social-security-council", ids)
        self.assertIn("social-security-council-statistics-subcommittee", ids)

    def test_build_parser_accepts_force_option(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["meetings", "export", "social-security-council", "--force"])
        self.assertTrue(args.force)

    def test_build_parser_accepts_ops_add(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["ops", "add", "social-security-council", "--skip-quality"])
        self.assertEqual(args.resource, "ops")
        self.assertEqual(args.action, "add")
        self.assertTrue(args.skip_quality)

    def test_build_parser_accepts_ops_update_refresh_hours(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["ops", "update", "social-security-council", "--refresh-hours", "12"])
        self.assertEqual(args.resource, "ops")
        self.assertEqual(args.action, "update")
        self.assertEqual(args.refresh_hours, 12)

    def test_build_parser_rejects_use_fixture_for_ops(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["ops", "update", "social-security-council", "--use-fixture"])

    def test_export_council_meetings_cli_writes_social_security_council(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "social-security-council",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("33 meeting files written, 2 document files written, ", result.stdout)
            meetings_dir = Path(tmpdir) / "councils" / "social-security-council" / "meetings"
            self.assertTrue((meetings_dir / "2025-02-03-033.json").exists())
            round_17 = json.loads((meetings_dir / "2005-09-21-017.json").read_text(encoding="utf-8"))
            round_18 = json.loads((meetings_dir / "2007-03-14-018.json").read_text(encoding="utf-8"))
            round_19 = json.loads((meetings_dir / "2009-08-06-019.json").read_text(encoding="utf-8"))
            self.assertEqual(
                round_17["agenda"],
                [
                    "平成18年度厚生労働省予算案の概要",
                    "社会保障をめぐる最近の動き",
                    "その他",
                ],
            )
            self.assertEqual(
                round_18["agenda"],
                [
                    "会長及び会長代理の選出について",
                    "分科会、部会の活動状況について",
                    "社会保障制度の最近の動向について",
                    "その他",
                ],
            )
            self.assertEqual(
                round_19["agenda"],
                [
                    "会長及び会長代理の選出について",
                    "その他",
                ],
            )

    def test_parse_fixture_meetings(self) -> None:
        council = load_council("social-security-council")
        html = fixture_html_path(council.source_urls.meetings).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=SOCIAL_SECURITY_COUNCIL_ID,
            source_url=council.source_urls.meetings,
            title=council.title,
        )
        meetings = result.meetings
        documents = result.documents
        rosters = result.rosters

        self.assertEqual(len(meetings), 33)
        self.assertEqual(len(documents), 2)
        self.assertEqual(len(rosters), 8)
        self.assertEqual(meetings[0].id, "2025-02-03-033")
        self.assertEqual(meetings[0].round_label, 33)
        self.assertEqual(meetings[0].announcement_links[0].title, "開催案内")
        self.assertEqual(meetings[0].agenda[0], "会長の選出について")
        self.assertNotIn("2017-01-29-no-round", [meeting.id for meeting in meetings])
        self.assertEqual(documents[0].id, "2002-03-12-toshin")
        self.assertEqual(
            documents[0].title,
            "厚生年金保険及び国民年金の積立金の運用に関する基本方針の変更について（答申）",
        )
        self.assertEqual(documents[0].body.status, "not_built")
        self.assertEqual(rosters[0].id, "2009-08-06")
        self.assertEqual(rosters[-1].id, "2017-01-29")

        round_27 = next(meeting for meeting in meetings if meeting.round_label == 27)
        self.assertEqual(
            round_27.agenda,
            [
                "会長の選出について",
                "社会保障制度改革のスケジュール等について",
                "平成27年度社会保障の充実・安定化について",
                "平成27年度厚生労働省関係予算案について",
                "医療保険制度改革骨子について",
            ],
        )

        round_21 = next(meeting for meeting in meetings if meeting.round_label == 21)
        self.assertEqual(
            round_21.agenda,
            [
                "会長の選出について",
                "生活保護基準部会（仮称）の設置について",
                "平成23年度厚生労働省関係予算案の概要について",
                "通常国会提出（予定）法案の概要について",
                "社会保障改革の動向について",
                "その他",
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
                    "social-security-council",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("33 meeting files written, 2 document files written, ", result.stdout)
            self.assertIn(" roster files written", result.stdout)
            meetings_dir = Path(tmpdir) / "councils" / "social-security-council" / "meetings"
            documents_dir = Path(tmpdir) / "councils" / "social-security-council" / "documents"
            rosters_dir = Path(tmpdir) / "councils" / "social-security-council" / "rosters"
            meeting_files = sorted(meetings_dir.glob("*.json"))
            document_files = sorted(documents_dir.glob("*.json"))
            roster_files = sorted(rosters_dir.glob("*.json"))
            self.assertEqual(len(meeting_files), 33)
            self.assertEqual(len(document_files), 2)
            self.assertGreaterEqual(len(roster_files), 10)
            self.assertFalse((meetings_dir / "2017-01-29-no-round.json").exists())

            payload = json.loads(meeting_files[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["council_id"], "social-security-council")
            self.assertIn("held_on", payload)
            self.assertNotIn("title", payload)

    def test_ops_add_cli_writes_council_and_meetings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "ops",
                    "add",
                    "social-security-council",
                    "--skip-quality",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn("social-security-council: 33 meeting files, 2 document files, ", result.stdout)
            council_dir = Path(tmpdir) / "councils" / "social-security-council"
            meetings_dir = council_dir / "meetings"
            documents_dir = council_dir / "documents"
            rosters_dir = council_dir / "rosters"
            document_files = sorted(documents_dir.glob("*.json"))

            self.assertTrue((council_dir / "council.json").exists())
            self.assertTrue(meetings_dir.exists())
            payload = json.loads((meetings_dir / "2025-02-03-033.json").read_text(encoding="utf-8"))
            self.assertIsInstance(payload["agenda"], list)
            self.assertNotIn("held_on_text", payload)
            self.assertNotIn("held_on_era_text", payload)

            document_payload = json.loads(document_files[0].read_text(encoding="utf-8"))
            self.assertEqual(document_payload["document_type"], "答申")
            self.assertEqual(document_payload["body"]["status"], "not_built")
            self.assertNotIn("published_on_text", document_payload)
            self.assertNotIn("published_on_era_text", document_payload)

            roster_payload = json.loads((rosters_dir / "2009-08-06.json").read_text(encoding="utf-8"))
            self.assertEqual(roster_payload["council_id"], "social-security-council")
            self.assertEqual(roster_payload["as_of"], "2009-08-06")
            self.assertTrue((rosters_dir / "2024-01-26.json").exists())

    def test_roster_link_title_detection(self) -> None:
        self.assertTrue(is_roster_link_title("委員名簿"))
        self.assertTrue(is_roster_link_title("（資料１－１）社会保障審議会委員名簿［PDF形式：81KB］"))
        self.assertFalse(is_roster_link_title("資料1"))

    def test_parse_hierarchy_page(self) -> None:
        hierarchy = get_mhlw_hierarchy_rule("social-security-council")
        councils = parse_hierarchy_page(
            self.HIERARCHY_SNIPPET,
            root_href=hierarchy.root_href,
            page_url=MHLW_INDEX_SOURCE_URL,
            root_parent=hierarchy.root_parent,
            known_ids={
                load_council(council_id).source_urls.meetings: council_id for council_id in hierarchy.known_council_ids
            },
        )
        ids = [council.council_id for council in councils]

        self.assertEqual(ids[0], "social-security-council")
        self.assertIn("social-security-council-statistics-subcommittee", ids)
        self.assertIn("shingi-hosho-164149", ids)
        self.assertIn("shingi-hosho-126696", ids)

        root = next(council for council in councils if council.council_id == "social-security-council")
        subcommittee = next(
            council
            for council in councils
            if council.council_id == "social-security-council-statistics-subcommittee"
        )
        subcommittee_child = next(council for council in councils if council.council_id == "shingi-hosho-164149")
        medical_subcommittee = next(council for council in councils if council.council_id == "shingi-hosho-126696")

        self.assertEqual(root.parent, "厚生労働省")
        self.assertEqual(subcommittee.parent, "social-security-council")
        self.assertEqual(subcommittee_child.parent, "social-security-council-statistics-subcommittee")
        self.assertEqual(subcommittee.title, "統計分科会")
        self.assertEqual(subcommittee_child.title, "統計分科会疾病、傷害及び死因分類部会")
        self.assertEqual(medical_subcommittee.title, "医療分科会")

    def test_extract_roster_links_from_material_page(self) -> None:
        path = ROOT / cached_html_path("https://www.mhlw.go.jp/stf/newpage_50483.html")
        html = path.read_text(encoding="utf-8")

        links = extract_roster_links_from_material_page(
            html,
            "https://www.mhlw.go.jp/stf/newpage_50483.html",
        )

        self.assertEqual(len(links), 1)
        self.assertIn("委員名簿", links[0].title)
        self.assertEqual(links[0].url, "https://www.mhlw.go.jp/content/12602000/001392479.pdf")

    def test_extract_agenda_from_legacy_announcement_pages(self) -> None:
        round_17_html = (ROOT / cached_html_path("https://www.mhlw.go.jp/shingi/2005/09/s0921-6.html")).read_text(
            encoding="utf-8"
        )
        round_18_html = (ROOT / cached_html_path("https://www.mhlw.go.jp/shingi/2007/03/s0314-4.html")).read_text(
            encoding="utf-8"
        )
        round_19_html = (ROOT / cached_html_path("https://www.mhlw.go.jp/shingi/2009/08/s0806-2.html")).read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            extract_agenda_from_detail_page(round_17_html),
            [
                "平成18年度厚生労働省予算案の概要",
                "社会保障をめぐる最近の動き",
                "その他",
            ],
        )
        self.assertEqual(
            extract_agenda_from_detail_page(round_18_html),
            [
                "会長及び会長代理の選出について",
                "分科会、部会の活動状況について",
                "社会保障制度の最近の動向について",
                "その他",
            ],
        )
        self.assertEqual(
            extract_agenda_from_detail_page(round_19_html),
            [
                "会長及び会長代理の選出について",
                "その他",
            ],
        )

    def test_extract_agenda_from_detail_page_stops_before_audience_guidance(self) -> None:
        path = ROOT / cached_html_path("https://www.mhlw.go.jp/stf/newpage_65531.html")
        html = path.read_text(encoding="utf-8")

        self.assertEqual(
            extract_agenda_from_detail_page(html),
            ["医療保険制度改革について"],
        )

    def test_extract_roster_links_from_32nd_material_page(self) -> None:
        path = ROOT / cached_html_path("https://www.mhlw.go.jp/stf/newpage_37566.html")
        html = path.read_text(encoding="utf-8")

        links = extract_roster_links_from_material_page(
            html,
            "https://www.mhlw.go.jp/stf/newpage_37566.html",
        )

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].url, "https://www.mhlw.go.jp/content/12602000/001197742.pdf")
        self.assertIn("社会保障審議会委員名簿", links[0].title)

    def test_cached_html_path_uses_url_hash(self) -> None:
        path = cached_html_path("https://www.mhlw.go.jp/stf/newpage_50483.html")
        self.assertEqual(path.name, "f45d1f8cfe0bacc99a5a17559891400d710e606fb283d07c395fb723da469dc9.html")


if __name__ == "__main__":
    unittest.main()
