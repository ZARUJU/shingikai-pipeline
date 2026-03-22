from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Callable

from flask import Flask, abort, redirect, render_template, request, url_for
from shingikai.quality import (
    list_meeting_gap_issues,
    update_meeting_gap_issue_review,
    DEFAULT_REVIEW_PATH as QUALITY_REVIEW_PATH,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = ROOT / "data" / "councils"
REVIEW_ROOT = ROOT / "data" / "_reviews"
MEETING_GAP_REVIEW_PATH = ROOT / QUALITY_REVIEW_PATH
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CouncilSummary:
    council_id: str
    title: str
    parent: str
    parent_label: str
    parent_is_council: bool
    portal_url: str
    meetings_url: str
    meeting_count: int
    document_count: int


@dataclass(slots=True)
class MonthlyMeetingGroup:
    month: str
    label: str
    meetings: list[dict[str, object]]


@dataclass(slots=True)
class TreeNode:
    key: str
    label: str
    kind: str
    href: str | None
    children: list["TreeNode"]


def create_app(
    review_path: Path | None = None,
    *,
    base_path: str = "",
    static_mode: bool = False,
) -> Flask:
    review_file = review_path or MEETING_GAP_REVIEW_PATH
    normalized_base_path = normalize_base_path(base_path)
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    app.jinja_env.globals["page_url"] = lambda page_name, **values: build_page_url(
        page_name,
        base_path=normalized_base_path,
        static_mode=static_mode,
        **values,
    )

    @app.get("/")
    def index() -> str:
        return render_template("index.html", **build_index_context())

    @app.get("/councils/treemap")
    def councils_treemap() -> str:
        return render_template(
            "council_treemap.html",
            **build_council_treemap_context(
                council_href_builder=lambda council_id: build_page_url(
                    "council_detail",
                    council_id=council_id,
                    base_path=normalized_base_path,
                    static_mode=static_mode,
                )
            ),
        )

    @app.get("/meetings/monthly")
    def monthly_meetings() -> str:
        return render_template("monthly_meetings.html", **build_monthly_meetings_context())

    @app.get("/quality/meeting-gaps")
    def meeting_gaps() -> str:
        tab = request.args.get("tab", "active")
        return render_template(
            "meeting_gaps.html",
            **build_meeting_gaps_context(
                tab=tab,
                review_path=review_file,
                allow_review_updates=not static_mode,
            ),
        )

    @app.get("/quality/meeting-gaps/ignored")
    def meeting_gaps_ignored() -> str:
        return render_template(
            "meeting_gaps.html",
            **build_meeting_gaps_context(
                tab="ignored",
                review_path=review_file,
                allow_review_updates=not static_mode,
            ),
        )

    @app.post("/quality/meeting-gaps/<council_id>")
    def update_meeting_gap_review(council_id: str):
        ignored = "true" in request.form.getlist("ignored")
        note = request.form.get("note", "").strip()
        tab = request.form.get("tab", "active")
        update_meeting_gap_issue_review(
            council_id=council_id,
            ignored=ignored,
            note=note,
            review_path=review_file,
        )
        return redirect(url_for("meeting_gaps", tab=tab))

    @app.get("/councils/<council_id>")
    def council_detail(council_id: str) -> str:
        return render_template("council_detail.html", **build_council_detail_context(council_id))

    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("ui start: data_root=%s", DATA_ROOT)
    app = create_app()
    app.run(debug=True, host="0.0.0.0", port=5050)


def list_councils() -> list[CouncilSummary]:
    councils: list[CouncilSummary] = []
    council_lookup = load_council_lookup()
    if not council_lookup:
        return councils

    for council_id, council in council_lookup.items():
        council_dir = DATA_ROOT / council_id
        meetings = load_json_files(council_dir / "meetings")
        documents = load_json_files(council_dir / "documents")
        parent_info = resolve_parent(council, council_lookup)
        councils.append(
            CouncilSummary(
                council_id=council["id"],
                title=council["title"],
                parent=str(council["parent"]),
                parent_label=parent_info["label"],
                parent_is_council=bool(parent_info["is_council"]),
                portal_url=council["source_urls"]["portal"],
                meetings_url=council["source_urls"]["meetings"],
                meeting_count=len(meetings),
                document_count=len(documents),
            )
        )
    return councils


def build_index_context() -> dict[str, object]:
    return {"councils": list_councils()}


def build_council_treemap_context(
    *,
    council_href_builder: Callable[[str], str] | None = None,
) -> dict[str, object]:
    return {"roots": build_council_tree(council_href_builder=council_href_builder)}


def build_monthly_meetings_context() -> dict[str, object]:
    return {"groups": list_monthly_meetings()}


def build_meeting_gaps_context(
    *,
    tab: str,
    review_path: Path,
    allow_review_updates: bool,
) -> dict[str, object]:
    issues = list_meeting_gap_issues(data_root=DATA_ROOT, review_path=review_path)
    active_issues = [issue for issue in issues if not issue.ignored]
    ignored_issues = [issue for issue in issues if issue.ignored]
    if tab not in {"active", "ignored"}:
        tab = "active"
    return {
        "tab": tab,
        "active_issues": active_issues,
        "ignored_issues": ignored_issues,
        "allow_review_updates": allow_review_updates,
    }


def build_council_detail_context(council_id: str) -> dict[str, object]:
    council_dir = DATA_ROOT / council_id
    if not council_dir.exists():
        abort(404)

    council = load_json(council_dir / "council.json")
    council_lookup = load_council_lookup()
    meetings = load_json_files(council_dir / "meetings")
    documents = load_json_files(council_dir / "documents")
    rosters = load_json_files(council_dir / "rosters")
    parent_info = resolve_parent(council, council_lookup)
    return {
        "council": council,
        "parent_info": parent_info,
        "meetings": meetings,
        "documents": documents,
        "rosters": rosters,
    }


def load_council_lookup() -> dict[str, dict[str, object]]:
    councils: dict[str, dict[str, object]] = {}
    if not DATA_ROOT.exists():
        return councils

    for council_dir in sorted(path for path in DATA_ROOT.iterdir() if path.is_dir()):
        council_path = council_dir / "council.json"
        if not council_path.exists():
            continue
        council = load_json(council_path)
        councils[str(council["id"])] = council
    return councils


def resolve_parent(
    council: dict[str, object],
    council_lookup: dict[str, dict[str, object]],
) -> dict[str, object]:
    parent = str(council["parent"])
    parent_council = council_lookup.get(parent)
    if parent_council is None:
        return {"id": None, "label": parent, "is_council": False}
    return {"id": parent, "label": parent_council["title"], "is_council": True}


def build_council_tree(
    *,
    council_href_builder: Callable[[str], str] | None = None,
) -> list[TreeNode]:
    council_lookup = load_council_lookup()
    children_by_parent: dict[str, list[dict[str, object]]] = {}
    root_labels: set[str] = set()

    for council in council_lookup.values():
        parent = str(council["parent"])
        if parent in council_lookup:
            children_by_parent.setdefault(parent, []).append(council)
        else:
            root_labels.add(parent)
            children_by_parent.setdefault(parent, []).append(council)

    roots: list[TreeNode] = []
    for label in sorted(root_labels):
        roots.append(
            TreeNode(
                key=label,
                label=label,
                kind="group",
                href=None,
                children=_build_child_nodes(
                    label,
                    children_by_parent,
                    council_href_builder=council_href_builder,
                ),
            )
        )
    return roots


def _build_child_nodes(
    parent_key: str,
    children_by_parent: dict[str, list[dict[str, object]]],
    *,
    council_href_builder: Callable[[str], str] | None = None,
) -> list[TreeNode]:
    children: list[TreeNode] = []
    for council in sorted(
        children_by_parent.get(parent_key, []), key=lambda item: str(item["title"])
    ):
        council_id = str(council["id"])
        children.append(
            TreeNode(
                key=council_id,
                label=str(council["title"]),
                kind="council",
                href=(
                    council_href_builder(council_id)
                    if council_href_builder is not None
                    else build_page_url("council_detail", council_id=council_id)
                ),
                children=_build_child_nodes(
                    council_id,
                    children_by_parent,
                    council_href_builder=council_href_builder,
                ),
            )
        )
    return children


def normalize_base_path(base_path: str) -> str:
    if not base_path or base_path == "/":
        return ""
    return "/" + base_path.strip("/")


def build_page_url(
    page_name: str,
    *,
    council_id: str | None = None,
    base_path: str = "",
    static_mode: bool = False,
) -> str:
    normalized_base_path = normalize_base_path(base_path)
    if static_mode:
        paths = {
            "index": "/",
            "councils_treemap": "/councils/treemap.html",
            "monthly_meetings": "/meetings/monthly.html",
            "meeting_gaps_active": "/quality/meeting-gaps.html",
            "meeting_gaps_ignored": "/quality/meeting-gaps-ignored.html",
            "meeting_gap_review": f"/quality/meeting-gaps/{council_id}",
            "council_detail": f"/councils/{council_id}.html",
        }
    else:
        paths = {
            "index": "/",
            "councils_treemap": "/councils/treemap",
            "monthly_meetings": "/meetings/monthly",
            "meeting_gaps_active": "/quality/meeting-gaps",
            "meeting_gaps_ignored": "/quality/meeting-gaps/ignored",
            "meeting_gap_review": f"/quality/meeting-gaps/{council_id}",
            "council_detail": f"/councils/{council_id}",
        }
    path = paths[page_name]
    if path == "/":
        return f"{normalized_base_path}/" if normalized_base_path else "/"
    return f"{normalized_base_path}{path}"


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


def list_monthly_meetings() -> list[MonthlyMeetingGroup]:
    groups: dict[str, list[dict[str, object]]] = {}

    for council_dir in sorted(path for path in DATA_ROOT.iterdir() if path.is_dir()):
        council_path = council_dir / "council.json"
        if not council_path.exists():
            continue

        council = load_json(council_path)
        for meeting in load_json_files(council_dir / "meetings"):
            held_on = str(meeting["held_on"])
            month = held_on[:7]
            groups.setdefault(month, []).append(
                {
                    **meeting,
                    "council_title": council["title"],
                    "council_id": council["id"],
                }
            )

    monthly_groups: list[MonthlyMeetingGroup] = []
    for month in sorted(groups.keys(), reverse=True):
        monthly_groups.append(
            MonthlyMeetingGroup(
                month=month,
                label=month,
                meetings=sorted(
                    groups[month], key=lambda item: str(item["held_on"]), reverse=True
                ),
            )
        )

    return monthly_groups
