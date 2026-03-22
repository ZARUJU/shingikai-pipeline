from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.utils.io import load_council


class GenericArchivesTest(unittest.TestCase):
    def test_council_can_define_meetings_archives(self) -> None:
        council = load_council("shingi-hosho-126694")
        self.assertEqual(
            council.source_urls.meetings_archives,
            ["https://warp.ndl.go.jp/20250125/20250106133112/www.mhlw.go.jp/stf/shingi/shingi-hosho_126694.html"],
        )

    def test_export_merges_archive_meeting_pages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "shingi-hosho-126694",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meetings_dir = Path(tmpdir) / "councils" / "shingi-hosho-126694" / "meetings"
            self.assertTrue((meetings_dir / "2006-07-28-001.json").exists())
            self.assertTrue((meetings_dir / "2018-12-13-021.json").exists())
            self.assertTrue((meetings_dir / "2026-02-20-029.json").exists())

            first_payload = json.loads((meetings_dir / "2006-07-28-001.json").read_text(encoding="utf-8"))
            self.assertEqual(first_payload["round_label"], 1)

    def test_export_merges_archive_meeting_pages_for_icf_committee(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "meetings",
                    "export",
                    "shingi-hosho-126695",
                    "--use-fixture",
                    "--output-dir",
                    tmpdir,
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            meetings_dir = Path(tmpdir) / "councils" / "shingi-hosho-126695" / "meetings"
            documents_dir = Path(tmpdir) / "councils" / "shingi-hosho-126695" / "documents"
            self.assertTrue((meetings_dir / "2006-07-26-001.json").exists())
            self.assertTrue((meetings_dir / "2024-02-28-023.json").exists())
            self.assertTrue((meetings_dir / "2025-11-10-024.json").exists())
            self.assertFalse((meetings_dir / "2016-05-24-no-round.json").exists())
            self.assertTrue((documents_dir / "2016-05-24-material.json").exists())

            round_17 = json.loads((meetings_dir / "2018-03-29-017.json").read_text(encoding="utf-8"))
            round_20 = json.loads((meetings_dir / "2020-04-03-020.json").read_text(encoding="utf-8"))
            round_23 = json.loads((meetings_dir / "2024-02-28-023.json").read_text(encoding="utf-8"))
            round_24 = json.loads((meetings_dir / "2025-11-10-024.json").read_text(encoding="utf-8"))
            material_doc = json.loads((documents_dir / "2016-05-24-material.json").read_text(encoding="utf-8"))

            self.assertEqual(
                round_17["agenda"],
                [
                    "委員長の選出",
                    "WHO-FICネットワーク年次会議（2016、2017）及びICD-11改訂会議の報告について",
                    "国際生活機能分類（ICF）の一部改正（2016、2017）について",
                    "第7回ICFシンポジウムの報告について",
                    "厚生労働科学研究成果報告（才藤研究班及び筒井研究班）について",
                    "諸外国のICF活用事例報告について",
                    "その他",
                ],
            )
            self.assertEqual(
                round_20["agenda"],
                [
                    "ICD-11V章の和訳について",
                    "WHO-FICネットワーク年次会議の報告（ICF関連）について",
                    "生活機能分類普及推進検討ワーキンググループの令和元年度の活動状況報告について",
                ],
            )
            self.assertEqual(
                round_23["agenda"],
                [
                    "委員長の選出について",
                    "WHO-FICネットワーク年次会議（ICF関連）の報告について",
                    "ICD-11 V章の和訳案について",
                    "その他",
                ],
            )
            self.assertEqual(
                round_24["agenda"],
                [
                    "ICD-11 V章（索引用語の和訳）について",
                    "その他",
                ],
            )
            self.assertEqual(material_doc["document_type"], "資料")
            self.assertEqual(
                material_doc["title"],
                "確定版国際生活機能分類（ＩＣＦ）一部改正（２０１１～２０１５）仮訳",
            )

    def test_council_can_define_meetings_archives_for_icf_committee(self) -> None:
        council = load_council("shingi-hosho-126695")
        self.assertEqual(
            council.source_urls.meetings_archives,
            ["https://warp.ndl.go.jp/20250125/20250106133114/www.mhlw.go.jp/stf/shingi/shingi-hosho_126695.html"],
        )


if __name__ == "__main__":
    unittest.main()
