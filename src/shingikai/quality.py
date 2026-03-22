from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path


DEFAULT_DATA_ROOT = Path("data/councils")
DEFAULT_REVIEW_PATH = Path("data/_reviews/meeting_gap_reviews.json")
DEFAULT_ISSUES_PATH = Path("data/_quality/meeting_gap_issues.json")


@dataclass(slots=True)
class MeetingGapIssue:
    council_id: str
    council_title: str
    min_round: int | None
    max_round: int | None
    total_meeting_count: int
    existing_round_count: int
    missing_rounds: list[int]
    missing_rounds_display: str
    exceeds_latest_round: bool
    excess_meeting_count: int
    issue_display: str
    review_note: str
    ignored: bool
    reviewed_at: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def list_meeting_gap_issues(
    *,
    data_root: Path | None = None,
    review_path: Path | None = None,
) -> list[MeetingGapIssue]:
    council_root = data_root or DEFAULT_DATA_ROOT
    review_data = load_meeting_gap_reviews(review_path=review_path)
    issues: list[MeetingGapIssue] = []

    if not council_root.exists():
        return issues

    for council_dir in sorted(path for path in council_root.iterdir() if path.is_dir()):
        council_path = council_dir / "council.json"
        if not council_path.exists():
            continue

        council = load_json(council_path)
        meetings = load_json_files(council_dir / "meetings")
        total_meeting_count = len(meetings)
        numbered_meeting_count = sum(1 for meeting in meetings if meeting.get("round_label") is not None)
        round_labels = sorted(
            {
                int(meeting["round_label"])
                for meeting in meetings
                if meeting.get("round_label") is not None
            }
        )
        review = review_data.get(str(council["id"]), {})
        if not round_labels:
            issues.append(
                MeetingGapIssue(
                    council_id=str(council["id"]),
                    council_title=str(council["title"]),
                    min_round=None,
                    max_round=None,
                    total_meeting_count=total_meeting_count,
                    existing_round_count=0,
                    missing_rounds=[],
                    missing_rounds_display="開催記録が0件です",
                    exceeds_latest_round=False,
                    excess_meeting_count=0,
                    issue_display="開催記録が0件です",
                    review_note=str(review.get("note", "")),
                    ignored=bool(review.get("ignored", False)),
                    reviewed_at=str(review["reviewed_at"]) if "reviewed_at" in review else None,
                )
            )
            continue

        min_round = round_labels[0]
        max_round = round_labels[-1]
        expected_rounds = set(range(1, max_round + 1))
        missing_rounds = sorted(expected_rounds - set(round_labels))
        exceeds_latest_round = numbered_meeting_count > max_round
        excess_meeting_count = max(numbered_meeting_count - max_round, 0)
        if exceeds_latest_round and _has_strict_round_reset(meetings):
            exceeds_latest_round = False
            excess_meeting_count = 0
        if not missing_rounds and not exceeds_latest_round:
            continue

        issues.append(
            MeetingGapIssue(
                council_id=str(council["id"]),
                council_title=str(council["title"]),
                min_round=min_round,
                max_round=max_round,
                total_meeting_count=total_meeting_count,
                existing_round_count=len(round_labels),
                missing_rounds=missing_rounds,
                missing_rounds_display=format_round_ranges(missing_rounds),
                exceeds_latest_round=exceeds_latest_round,
                excess_meeting_count=excess_meeting_count,
                issue_display=build_issue_display(
                    missing_rounds=missing_rounds,
                    exceeds_latest_round=exceeds_latest_round,
                    total_meeting_count=numbered_meeting_count,
                    max_round=max_round,
                ),
                review_note=str(review.get("note", "")),
                ignored=bool(review.get("ignored", False)),
                reviewed_at=str(review["reviewed_at"]) if "reviewed_at" in review else None,
            )
        )

    return issues


def export_meeting_gap_issues(
    *,
    output_path: Path | None = None,
    data_root: Path | None = None,
    review_path: Path | None = None,
) -> Path:
    target_path = output_path or DEFAULT_ISSUES_PATH
    issues = list_meeting_gap_issues(data_root=data_root, review_path=review_path)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(issues),
        "issues": [issue.to_dict() for issue in issues],
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target_path


def load_meeting_gap_reviews(review_path: Path | None = None) -> dict[str, dict[str, object]]:
    path = review_path or DEFAULT_REVIEW_PATH
    payload = load_optional_json(path)
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def update_meeting_gap_issue_review(
    *,
    council_id: str,
    ignored: bool,
    note: str,
    review_path: Path | None = None,
) -> None:
    path = review_path or DEFAULT_REVIEW_PATH
    payload = load_meeting_gap_reviews(review_path=path)
    payload[council_id] = {
        "ignored": ignored,
        "note": note,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def format_round_ranges(rounds: list[int]) -> str:
    if not rounds:
        return ""

    ranges: list[str] = []
    start = rounds[0]
    end = rounds[0]

    for number in rounds[1:]:
        if number == end + 1:
            end = number
            continue
        ranges.append(_format_round_range(start, end))
        start = number
        end = number

    ranges.append(_format_round_range(start, end))
    return ",".join(ranges)


def _format_round_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}~{end}"


def build_issue_display(
    *,
    missing_rounds: list[int],
    exceeds_latest_round: bool,
    total_meeting_count: int,
    max_round: int,
) -> str:
    parts: list[str] = []
    if missing_rounds:
        parts.append(f"欠番: {format_round_ranges(missing_rounds)}")
    if exceeds_latest_round:
        parts.append(f"開催記録数超過: {total_meeting_count}件 / 最新{max_round}回")
    return " / ".join(parts)


def _has_strict_round_reset(meetings: list[dict[str, object]]) -> bool:
    numbered_meetings = [meeting for meeting in meetings if meeting.get("round_label") is not None]
    if len(numbered_meetings) < 2:
        return False

    previous_round: int | None = None
    for meeting in numbered_meetings:
        round_label = int(meeting["round_label"])
        if previous_round is not None and round_label < previous_round:
            return True
        previous_round = round_label

    return False


def load_json_files(directory: Path) -> list[dict[str, object]]:
    if not directory.exists():
        return []
    return [load_json(path) for path in sorted(directory.glob("*.json"))]


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return load_json(path)
