from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from werkzeug.datastructures import MultiDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ui.app import create_app


class UiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.review_path = Path(self.tempdir.name) / "meeting_gap_reviews.json"
        self.app = create_app(review_path=self.review_path)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_index_page(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("会議体一覧", html)
        self.assertIn("社会保障審議会", html)
        self.assertIn("統計分科会", html)
        self.assertIn("会議体系統を見る", html)
        self.assertIn("月ごとの開催一覧を見る", html)
        self.assertIn("開催回次の欠番を確認する", html)

    def test_council_detail_page(self) -> None:
        response = self.client.get("/councils/social-security-council")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("開催記録", html)
        self.assertIn("文書", html)
        self.assertIn("名簿", html)
        self.assertIn("2001-02-27", html)
        self.assertIn("親", html)

    def test_monthly_meetings_page(self) -> None:
        response = self.client.get("/meetings/monthly")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("月ごとの開催一覧", html)
        self.assertIn("2025-02", html)
        self.assertIn("2025-08", html)
        self.assertIn("2025-02-03", html)
        self.assertIn("2025-08-01", html)
        self.assertIn("社会保障審議会", html)

    def test_council_treemap_page(self) -> None:
        response = self.client.get("/councils/treemap")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("会議体系統", html)
        self.assertIn("厚生労働省", html)
        self.assertIn("社会保障審議会", html)
        self.assertIn("統計分科会", html)

    def test_meeting_gaps_page(self) -> None:
        response = self.client.get("/quality/meeting-gaps")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("開催回次の異常確認", html)
        self.assertIn("医療保険部会", html)
        self.assertIn("開催記録が0件です", html)
        self.assertIn("1 - 211", html)
        self.assertIn("欠番: 1~6", html)
        self.assertIn("開催記録数超過", html)

    def test_meeting_gap_review_can_be_ignored(self) -> None:
        response = self.client.post(
            "/quality/meeting-gaps/newpage-28708",
            data={
                "tab": "active",
                "ignored": "true",
                "note": "古い回は未公開なので無視",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        saved = self.review_path.read_text(encoding="utf-8")
        self.assertIn("古い回は未公開なので無視", saved)

        ignored_page = self.client.get("/quality/meeting-gaps?tab=ignored")
        ignored_html = ignored_page.get_data(as_text=True)
        self.assertIn("医療保険部会", ignored_html)
        self.assertIn("古い回は未公開なので無視", ignored_html)

    def test_meeting_gap_review_checkbox_value_is_preserved_when_hidden_field_is_present(self) -> None:
        response = self.client.post(
            "/quality/meeting-gaps/newpage-28708",
            data=MultiDict(
                [
                    ("tab", "active"),
                    ("ignored", "false"),
                    ("ignored", "true"),
                    ("note", "checkbox checked"),
                ]
            ),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        saved = self.review_path.read_text(encoding="utf-8")
        self.assertIn('"ignored": true', saved)


if __name__ == "__main__":
    unittest.main()
