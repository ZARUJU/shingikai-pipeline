from __future__ import annotations

import unittest

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from shingikai.cli import _normalize_anonymous_medical_committee_agenda


class AnonymousMedicalCommitteeAgendaTest(unittest.TestCase):
    def test_split_on_nitsuite_and_nonpublic(self) -> None:
        agenda = _normalize_anonymous_medical_committee_agenda(
            [
                "「匿名医療保険等関連情報の提供に関する申出書」の審査スケジュールについて"
                "「匿名診療等関連情報の提供に関する申出書」の審査スケジュールについて"
                "不適切利用について（非公開）"
                "個別審査（非公開）"
            ]
        )

        self.assertEqual(
            agenda,
            [
                "「匿名医療保険等関連情報の提供に関する申出書」の審査スケジュールについて",
                "「匿名診療等関連情報の提供に関する申出書」の審査スケジュールについて",
                "不適切利用について（非公開）",
                "個別審査（非公開）",
            ],
        )

    def test_split_with_circled_number_marker(self) -> None:
        agenda = _normalize_anonymous_medical_committee_agenda(["⒈個別審査（非公開）"])
        self.assertEqual(agenda, ["個別審査（非公開）"])

    def test_split_without_number_marker(self) -> None:
        agenda = _normalize_anonymous_medical_committee_agenda(
            ["40歳未満の事業主健診情報等のNDB収載について第11回及び第12回オープンデータの作成方針について個別審査（非公開）"]
        )
        self.assertEqual(
            agenda,
            [
                "40歳未満の事業主健診情報等のNDB収載について",
                "第11回及び第12回オープンデータの作成方針について",
                "個別審査（非公開）",
            ],
        )
