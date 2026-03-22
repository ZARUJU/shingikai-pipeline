from __future__ import annotations

import sys
import tempfile
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.councils.mhlw import (
    ExistingCouncilData,
    _can_skip_regeneration,
    _reuse_existing_outputs,
    fixture_html_path,
    parse_meeting_page,
)
from shingikai.models.document import CouncilDocument, DocumentBody
from shingikai.models.meeting import Meeting, MeetingLink
from shingikai.models.roster import CouncilRoster
from shingikai.utils.normalize import parse_round_labels


CHRONIC_DISEASE_COMMITTEE_ID = "shingi-hosho-126716"
CHRONIC_DISEASE_COMMITTEE_TITLE = "児童部会小児慢性特定疾患児への支援の在り方に関する専門委員会"
CHRONIC_DISEASE_COMMITTEE_SOURCE_URL = "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126716.html"


class MhlwCommonTest(unittest.TestCase):
    def test_parse_round_labels_supports_joint_round_notation(self) -> None:
        self.assertEqual(parse_round_labels("第43・44回"), [43, 44])
        self.assertEqual(parse_round_labels("第19回、第20回"), [19, 20])

    def test_parse_meeting_page_expands_joint_round_rows(self) -> None:
        html = fixture_html_path(CHRONIC_DISEASE_COMMITTEE_SOURCE_URL).read_text(encoding="utf-8")
        result = parse_meeting_page(
            html,
            council_id=CHRONIC_DISEASE_COMMITTEE_ID,
            source_url=CHRONIC_DISEASE_COMMITTEE_SOURCE_URL,
            title=CHRONIC_DISEASE_COMMITTEE_TITLE,
        )

        rounds_on_2017_07_05 = [meeting for meeting in result.meetings if meeting.held_on == "2017-07-05"]
        self.assertEqual([meeting.round_label for meeting in rounds_on_2017_07_05], [19, 20])
        self.assertEqual(
            rounds_on_2017_07_05[0].agenda,
            [
                "移行期医療における連携の推進のためのガイドの作成について（小児慢性特定疾病児童成人移行期医療支援モデル事業の報告）",
                "その他",
            ],
        )
        self.assertEqual(
            rounds_on_2017_07_05[1].agenda,
            [
                "小児慢性特定疾病対策の現状（基本方針の取組状況）について",
                "小児慢性特定疾病（平成30年度実施分）の募集について",
                "その他",
            ],
        )

        rounds_on_2021_05_13 = [meeting for meeting in result.meetings if meeting.held_on == "2021-05-13"]
        self.assertEqual([meeting.round_label for meeting in rounds_on_2021_05_13], [43, 44])
        self.assertEqual(rounds_on_2021_05_13[0].agenda, rounds_on_2021_05_13[1].agenda)

        self.assertFalse(any(meeting.held_on == "2021-07-14" for meeting in result.meetings))
        opinion_document = next(document for document in result.documents if document.published_on == "2021-07-14")
        self.assertEqual(opinion_document.document_type, "意見書")
        self.assertEqual(opinion_document.id, "2021-07-14-ikensho")
        self.assertEqual(opinion_document.title, "難病・小慢対策の見直しに関する意見書について")

    def test_parse_meeting_page_supports_legacy_table_layout(self) -> None:
        html = """
        <html>
          <body>
            <table>
              <tbody>
                <tr>
                  <th><center>回数</center></th>
                  <th><center>開催日</center></th>
                  <th><center>議題</center></th>
                  <th><center>議事録</center></th>
                  <th><center>資料</center></th>
                  <th><center>開催案内</center></th>
                </tr>
                <tr>
                  <th><center>第３回</center></th>
                  <th><center>2013年11月6日<br>（平成25年11月6日）</center></th>
                  <td class="agenda">１．部会長の選出について<br>２．その他</td>
                  <td><center><div><a href="https://example.com/minutes.html">議事録</a></div></center></td>
                  <td><center><div><a href="https://example.com/materials.html">資料</a></div></center></td>
                  <td><center>－</center></td>
                </tr>
              </tbody>
            </table>
          </body>
        </html>
        """
        result = parse_meeting_page(
            html,
            council_id="legacy-council",
            source_url="https://example.com/legacy.html",
            title="旧ページ会議",
        )

        self.assertEqual(len(result.meetings), 1)
        self.assertEqual(result.meetings[0].round_label, 3)
        self.assertEqual(result.meetings[0].held_on, "2013-11-06")
        self.assertEqual(result.meetings[0].agenda, ["部会長の選出について", "その他"])
        self.assertEqual(result.meetings[0].minutes_links[0].url, "https://example.com/minutes.html")

    def test_parse_meeting_page_treats_no_round_material_only_row_as_document(self) -> None:
        html = """
        <html>
          <body>
            <table class="m-tableFlex">
              <tbody>
                <tr>
                  <th>回数</th>
                  <th>開催日</th>
                  <th>議題</th>
                  <th>議事録</th>
                  <th>資料</th>
                  <th>開催案内</th>
                </tr>
                <tr>
                  <td> - </td>
                  <td>2025年11月18日</td>
                  <td></td>
                  <td></td>
                  <td><a href="report.html">報告書</a></td>
                  <td></td>
                </tr>
              </tbody>
            </table>
          </body>
        </html>
        """
        result = parse_meeting_page(
            html,
            council_id="document-council",
            source_url="https://example.com/index.html",
            title="文書会議",
        )

        self.assertEqual(result.meetings, [])
        self.assertEqual(len(result.documents), 1)
        self.assertEqual(result.documents[0].id, "2025-11-18-material")
        self.assertEqual(result.documents[0].document_type, "資料")
        self.assertEqual(result.documents[0].source_url, "https://example.com/report.html")

    def test_export_removes_stale_joint_round_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            meetings_dir = Path(tmpdir) / "councils" / CHRONIC_DISEASE_COMMITTEE_ID / "meetings"
            meetings_dir.mkdir(parents=True, exist_ok=True)
            stale_path = meetings_dir / "2017-07-05-1920.json"
            stale_path.write_text("{}", encoding="utf-8")

            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    CHRONIC_DISEASE_COMMITTEE_ID,
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertFalse(stale_path.exists())
            self.assertTrue((meetings_dir / "2017-07-05-019.json").exists())
            self.assertTrue((meetings_dir / "2017-07-05-020.json").exists())

    def test_reuse_existing_outputs_keeps_enriched_meeting_without_detail_fetch(self) -> None:
        parsed_meeting = Meeting(
            id="2025-01-01-001",
            council_id="sample-council",
            round_label=1,
            held_on="2025-01-01",
            agenda=[],
            source_url="https://example.com/notice.html",
            minutes_links=[],
            materials_links=[MeetingLink(title="資料", url="https://example.com/materials.html")],
            announcement_links=[MeetingLink(title="開催案内", url="https://example.com/notice.html")],
        )
        existing_meeting = Meeting(
            id="2025-01-01-001",
            council_id="sample-council",
            round_label=1,
            held_on="2025-01-01",
            agenda=["議題A", "議題B"],
            source_url="https://example.com/notice.html",
            minutes_links=[],
            materials_links=[MeetingLink(title="資料", url="https://example.com/materials.html")],
            announcement_links=[MeetingLink(title="開催案内", url="https://example.com/notice.html")],
        )
        parsed_document = CouncilDocument(
            id="2025-01-01-material",
            council_id="sample-council",
            title="資料",
            published_on="2025-01-01",
            document_type="資料",
            source_url="https://example.com/materials.pdf",
            links=[MeetingLink(title="資料", url="https://example.com/materials.pdf")],
            body=DocumentBody(status="not_built"),
        )
        parsed_roster = CouncilRoster(
            id="2025-01-01",
            council_id="sample-council",
            as_of="2025-01-01",
            source_url="https://example.com/roster.pdf",
            links=[MeetingLink(title="委員名簿", url="https://example.com/roster.pdf")],
        )

        reused_result, meeting_ids_to_enrich = _reuse_existing_outputs(
            parse_meeting_page(
                """
                <html><body><table class="m-tableFlex"><tr><th>回数</th><th>開催日</th><th>議題</th><th>議事録</th><th>資料</th><th>開催案内</th></tr></table></body></html>
                """,
                council_id="sample-council",
                source_url="https://example.com/index.html",
                title="sample",
            ).model_copy(update={"meetings": [parsed_meeting], "documents": [parsed_document], "rosters": [parsed_roster]}),
            existing_data=ExistingCouncilData(
                meetings={existing_meeting.id: existing_meeting},
                documents={parsed_document.id: parsed_document},
                rosters={parsed_roster.id: parsed_roster},
            ),
        )

        self.assertEqual(reused_result.meetings[0].agenda, ["議題A", "議題B"])
        self.assertEqual(meeting_ids_to_enrich, set())

    def test_can_skip_regeneration_when_list_page_has_no_diff(self) -> None:
        parsed_meeting = Meeting(
            id="2025-01-01-001",
            council_id="sample-council",
            round_label=1,
            held_on="2025-01-01",
            agenda=[],
            source_url="https://example.com/notice.html",
            minutes_links=[],
            materials_links=[MeetingLink(title="資料", url="https://example.com/materials.html")],
            announcement_links=[MeetingLink(title="開催案内", url="https://example.com/notice.html")],
        )
        existing_meeting = parsed_meeting.model_copy(update={"agenda": ["議題A"]})
        parsed_document = CouncilDocument(
            id="2025-01-01-material",
            council_id="sample-council",
            title="資料",
            published_on="2025-01-01",
            document_type="資料",
            source_url="https://example.com/materials.pdf",
            links=[MeetingLink(title="資料", url="https://example.com/materials.pdf")],
            body=DocumentBody(status="not_built"),
        )
        parsed_roster = CouncilRoster(
            id="2025-01-01",
            council_id="sample-council",
            as_of="2025-01-01",
            source_url="https://example.com/roster.pdf",
            links=[MeetingLink(title="委員名簿", url="https://example.com/roster.pdf")],
        )

        self.assertTrue(
            _can_skip_regeneration(
                parsed_result=parse_meeting_page(
                    """
                    <html><body><table class="m-tableFlex"><tr><th>回数</th><th>開催日</th><th>議題</th><th>議事録</th><th>資料</th><th>開催案内</th></tr></table></body></html>
                    """,
                    council_id="sample-council",
                    source_url="https://example.com/index.html",
                    title="sample",
                ).model_copy(update={"meetings": [parsed_meeting], "documents": [parsed_document], "rosters": [parsed_roster]}),
                existing_data=ExistingCouncilData(
                    meetings={existing_meeting.id: existing_meeting},
                    documents={parsed_document.id: parsed_document},
                    rosters={parsed_roster.id: parsed_roster},
                ),
            )
        )


if __name__ == "__main__":
    unittest.main()
