from __future__ import annotations

from datetime import date as real_date
import sys
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

from werkzeug.datastructures import MultiDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ui.app import create_app
from ui.export import export_static_site


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
        self.assertIn("開催記録を月ごとのページに分けて確認できます。", html)
        self.assertIn("年月", html)
        self.assertIn("開催件数", html)

    def test_monthly_meetings_detail_page(self) -> None:
        monthly_data_root = Path(self.tempdir.name) / "monthly_data"
        council_dir = monthly_data_root / "sample-council"
        meetings_dir = council_dir / "meetings"
        meetings_dir.mkdir(parents=True)
        (council_dir / "documents").mkdir()
        (council_dir / "rosters").mkdir()
        (council_dir / "council.json").write_text(
            json.dumps(
                {
                    "id": "sample-council",
                    "title": "サンプル会議体",
                    "parent": "テスト省",
                    "source_urls": {
                        "portal": "https://example.com",
                        "meetings": "https://example.com/meetings",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (meetings_dir / "2026-02-10.json").write_text(
            json.dumps(
                {
                    "held_on": "2026-02-10",
                    "round_label": "1",
                    "agenda": ["議題A"],
                    "source_url": "https://example.com/meeting/1",
                    "announcement_links": [],
                    "materials_links": [],
                    "minutes_links": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (meetings_dir / "2026-01-15.json").write_text(
            json.dumps(
                {
                    "held_on": "2026-01-15",
                    "round_label": "2",
                    "agenda": ["議題B"],
                    "source_url": "https://example.com/meeting/2",
                    "announcement_links": [],
                    "materials_links": [],
                    "minutes_links": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (meetings_dir / "2026-03-20.json").write_text(
            json.dumps(
                {
                    "held_on": "2026-03-20",
                    "round_label": "3",
                    "agenda": ["議題C"],
                    "source_url": "https://example.com/meeting/3",
                    "announcement_links": [],
                    "materials_links": [],
                    "minutes_links": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with patch("ui.app.DATA_ROOT", monthly_data_root), patch("ui.app.date") as mock_date:
            mock_date.today.return_value = real_date(2026, 3, 23)
            mock_date.side_effect = lambda *args, **kwargs: real_date(*args, **kwargs)
            app = create_app(review_path=self.review_path)
            client = app.test_client()
            response = client.get("/meetings/2026/02/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("2026-02 の開催一覧", html)
        self.assertIn("月一覧へ戻る", html)
        self.assertIn("前月", html)
        self.assertIn("今月", html)
        self.assertIn("翌月", html)
        self.assertIn('/meetings/2026/03/', html)
        self.assertIn("日付", html)
        self.assertIn("会議体", html)
        self.assertIn("回次", html)
        self.assertIn("<th class=\"whitespace-nowrap px-4 py-3 font-medium\">リンク</th>", html)
        self.assertIn("代表リンク", html)

    def test_council_treemap_page(self) -> None:
        response = self.client.get("/councils/treemap")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("会議体系統", html)
        self.assertIn("/councils/treemap/mhlw", html)
        self.assertIn("/councils/treemap/mofa", html)
        self.assertNotIn("社会保障審議会", html)

    def test_council_treemap_mhlw_page(self) -> None:
        response = self.client.get("/councils/treemap/mhlw")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("厚生労働省", html)
        self.assertIn("社会保障審議会", html)
        self.assertIn("統計分科会", html)

    def test_council_treemap_mofa_page(self) -> None:
        response = self.client.get("/councils/treemap/mofa")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("外務省", html)
        self.assertIn("外務人事審議会", html)

    def test_meeting_gaps_page(self) -> None:
        response = self.client.get("/quality/meeting-gaps")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("開催回次の異常確認", html)
        self.assertIn("医療保険部会", html)
        self.assertIn("開催記録が0件です", html)
        self.assertIn("未無視", html)
        self.assertIn("無視済み", html)

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

    def test_index_page_supports_base_path_links(self) -> None:
        app = create_app(base_path="/shingikai-pipeline", static_mode=True)
        client = app.test_client()

        response = client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/shingikai-pipeline/"', html)
        self.assertIn('href="/shingikai-pipeline/councils/treemap/"', html)
        self.assertIn('href="/shingikai-pipeline/quality/meeting-gaps.html"', html)
        self.assertIn('href="/shingikai-pipeline/meetings/monthly.html"', html)

    def test_static_site_export_writes_pages(self) -> None:
        output_dir = Path(self.tempdir.name) / "site"

        written_paths = export_static_site(
            output_dir,
            review_path=self.review_path,
            base_path="/shingikai-pipeline",
        )

        self.assertTrue((output_dir / "index.html").exists())
        self.assertTrue((output_dir / "councils" / "treemap" / "index.html").exists())
        self.assertTrue((output_dir / "councils" / "treemap" / "mhlw" / "index.html").exists())
        self.assertTrue((output_dir / "councils" / "treemap" / "mofa" / "index.html").exists())
        self.assertTrue((output_dir / "councils" / "social-security-council.html").exists())
        self.assertTrue((output_dir / "meetings" / "monthly.html").exists())
        self.assertTrue((output_dir / "quality" / "meeting-gaps.html").exists())
        self.assertTrue((output_dir / "quality" / "meeting-gaps-ignored.html").exists())
        self.assertTrue((output_dir / ".nojekyll").exists())
        self.assertGreater(len(written_paths), 5)

        html = (output_dir / "quality" / "meeting-gaps.html").read_text(encoding="utf-8")
        self.assertIn("/shingikai-pipeline/councils/newpage-28708.html", html)
        self.assertNotIn("<form method=\"post\"", html)
        self.assertIn("要確認", html)

    def test_static_site_export_writes_monthly_detail_pages_when_meetings_exist(self) -> None:
        monthly_data_root = Path(self.tempdir.name) / "monthly_export_data"
        council_dir = monthly_data_root / "sample-council"
        meetings_dir = council_dir / "meetings"
        meetings_dir.mkdir(parents=True)
        (council_dir / "documents").mkdir()
        (council_dir / "rosters").mkdir()
        (council_dir / "council.json").write_text(
            json.dumps(
                {
                    "id": "sample-council",
                    "title": "サンプル会議体",
                    "parent": "テスト省",
                    "source_urls": {
                        "portal": "https://example.com",
                        "meetings": "https://example.com/meetings",
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (meetings_dir / "2026-02-10.json").write_text(
            json.dumps(
                {
                    "held_on": "2026-02-10",
                    "round_label": "1",
                    "agenda": ["議題A"],
                    "source_url": "https://example.com/meeting/1",
                    "announcement_links": [],
                    "materials_links": [],
                    "minutes_links": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        output_dir = Path(self.tempdir.name) / "monthly_site"
        with patch("ui.app.DATA_ROOT", monthly_data_root):
            written_paths = export_static_site(output_dir, review_path=self.review_path)

        self.assertTrue((output_dir / "meetings" / "monthly.html").exists())
        self.assertTrue((output_dir / "meetings" / "2026" / "02" / "index.html").exists())
        self.assertGreater(len(written_paths), 2)


if __name__ == "__main__":
    unittest.main()
