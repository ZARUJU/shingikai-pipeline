from __future__ import annotations

import json
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.quality import export_meeting_gap_issues, list_meeting_gap_issues


class QualityExportTest(unittest.TestCase):
    def test_list_meeting_gap_issues_includes_zero_meeting_council(self) -> None:
        issues = list_meeting_gap_issues()
        issue_by_id = {issue.council_id: issue for issue in issues}

        self.assertIn("shingi-hosho-126731", issue_by_id)
        self.assertEqual(issue_by_id["shingi-hosho-126731"].issue_display, "開催記録が0件です")

    def test_export_meeting_gap_issues_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "meeting_gap_issues.json"
            written = export_meeting_gap_issues(output_path=output_path)

            self.assertEqual(written, output_path)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertIn("generated_at", payload)
            self.assertGreater(payload["count"], 0)
            ids = {item["council_id"] for item in payload["issues"]}
            self.assertIn("shingi-hosho-126731", ids)

    def test_quality_export_cli_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "meeting_gap_issues.json"
            result = subprocess.run(
                [
                    str(ROOT / ".venv" / "bin" / "python"),
                    "cli.py",
                    "quality",
                    "export",
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn(str(output_path), result.stdout)
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertGreater(payload["count"], 0)

    def test_list_meeting_gap_issues_includes_count_exceeds_latest_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "councils"
            council_dir = data_root / "sample-council"
            meetings_dir = council_dir / "meetings"
            meetings_dir.mkdir(parents=True)
            (council_dir / "council.json").write_text(
                json.dumps(
                    {
                        "id": "sample-council",
                        "title": "件数超過テスト会議",
                        "parent": "厚生労働省",
                        "source_urls": {"portal": "https://example.com", "meetings": "https://example.com"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name, round_label in [("2024-01-01-001.json", 1), ("2024-01-02-002.json", 2), ("2024-01-03-002b.json", 2)]:
                (meetings_dir / name).write_text(
                    json.dumps(
                        {
                            "id": name.removesuffix(".json"),
                            "council_id": "sample-council",
                            "round_label": round_label,
                            "held_on": "2024-01-01",
                            "agenda": [],
                            "source_url": "https://example.com",
                            "minutes_links": [],
                            "materials_links": [],
                            "announcement_links": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            issues = list_meeting_gap_issues(data_root=data_root)
            self.assertEqual(len(issues), 1)
            issue = issues[0]
            self.assertTrue(issue.exceeds_latest_round)
            self.assertEqual(issue.excess_meeting_count, 1)
            self.assertEqual(issue.issue_display, "開催記録数超過: 3件 / 最新2回")

    def test_list_meeting_gap_issues_ignores_no_round_meetings_for_excess_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "councils"
            council_dir = data_root / "sample-council"
            meetings_dir = council_dir / "meetings"
            meetings_dir.mkdir(parents=True)
            (council_dir / "council.json").write_text(
                json.dumps(
                    {
                        "id": "sample-council",
                        "title": "回次なし併存テスト会議",
                        "parent": "厚生労働省",
                        "source_urls": {"portal": "https://example.com", "meetings": "https://example.com"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name, round_label in [("2024-01-01-001.json", 1), ("2024-01-02-002.json", 2), ("2024-01-03-no-round.json", None)]:
                (meetings_dir / name).write_text(
                    json.dumps(
                        {
                            "id": name.removesuffix(".json"),
                            "council_id": "sample-council",
                            "round_label": round_label,
                            "held_on": "2024-01-01",
                            "agenda": [],
                            "source_url": "https://example.com",
                            "minutes_links": [],
                            "materials_links": [],
                            "announcement_links": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            issues = list_meeting_gap_issues(data_root=data_root)
            self.assertEqual(issues, [])

    def test_list_meeting_gap_issues_ignores_excess_when_round_numbers_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "councils"
            council_dir = data_root / "sample-council"
            meetings_dir = council_dir / "meetings"
            meetings_dir.mkdir(parents=True)
            (council_dir / "council.json").write_text(
                json.dumps(
                    {
                        "id": "sample-council",
                        "title": "回次リセットテスト会議",
                        "parent": "厚生労働省",
                        "source_urls": {"portal": "https://example.com", "meetings": "https://example.com"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name, held_on, round_label in [
                ("2020-01-01-001.json", "2020-01-01", 1),
                ("2020-02-01-002.json", "2020-02-01", 2),
                ("2024-01-01-001.json", "2024-01-01", 1),
                ("2024-02-01-002.json", "2024-02-01", 2),
                ("2024-03-01-003.json", "2024-03-01", 3),
            ]:
                (meetings_dir / name).write_text(
                    json.dumps(
                        {
                            "id": name.removesuffix(".json"),
                            "council_id": "sample-council",
                            "round_label": round_label,
                            "held_on": held_on,
                            "agenda": [],
                            "source_url": "https://example.com",
                            "minutes_links": [],
                            "materials_links": [],
                            "announcement_links": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            issues = list_meeting_gap_issues(data_root=data_root)
            self.assertEqual(issues, [])

    def test_list_meeting_gap_issues_ignores_excess_when_later_segment_starts_midway(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            data_root = Path(tmpdir) / "councils"
            council_dir = data_root / "sample-council"
            meetings_dir = council_dir / "meetings"
            meetings_dir.mkdir(parents=True)
            (council_dir / "council.json").write_text(
                json.dumps(
                    {
                        "id": "sample-council",
                        "title": "途中再開テスト会議",
                        "parent": "厚生労働省",
                        "source_urls": {"portal": "https://example.com", "meetings": "https://example.com"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            for name, held_on, round_label in [
                ("2020-01-01-001.json", "2020-01-01", 1),
                ("2020-02-01-002.json", "2020-02-01", 2),
                ("2020-03-01-003.json", "2020-03-01", 3),
                ("2024-01-01-002.json", "2024-01-01", 2),
                ("2024-02-01-003.json", "2024-02-01", 3),
                ("2024-03-01-004.json", "2024-03-01", 4),
            ]:
                (meetings_dir / name).write_text(
                    json.dumps(
                        {
                            "id": name.removesuffix(".json"),
                            "council_id": "sample-council",
                            "round_label": round_label,
                            "held_on": held_on,
                            "agenda": [],
                            "source_url": "https://example.com",
                            "minutes_links": [],
                            "materials_links": [],
                            "announcement_links": [],
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            issues = list_meeting_gap_issues(data_root=data_root)
            self.assertEqual(issues, [])


if __name__ == "__main__":
    unittest.main()
