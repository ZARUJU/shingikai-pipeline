from __future__ import annotations

import shutil
from pathlib import Path

from flask import render_template

from ui.app import (
    MEETING_GAP_REVIEW_PATH,
    build_council_detail_context,
    build_council_treemap_context,
    build_index_context,
    build_meeting_gaps_context,
    build_monthly_meetings_index_context,
    build_monthly_meetings_context,
    create_app,
    load_council_lookup,
    list_monthly_meetings,
)


def export_static_site(
    output_dir: Path,
    *,
    review_path: Path | None = None,
    base_path: str = "",
) -> list[Path]:
    review_file = review_path or MEETING_GAP_REVIEW_PATH
    app = create_app(review_path=review_file, base_path=base_path, static_mode=True)
    resolved_output_dir = output_dir.resolve()

    if resolved_output_dir.exists():
        shutil.rmtree(resolved_output_dir)
    resolved_output_dir.mkdir(parents=True, exist_ok=True)

    written_paths: list[Path] = []
    with app.app_context():
        written_paths.append(
            _write_page(
                resolved_output_dir / "index.html",
                render_template("index.html", **build_index_context()),
            )
        )
        written_paths.append(
            _write_page(
                resolved_output_dir / "councils" / "treemap.html",
                render_template(
                    "council_treemap.html",
                    **build_council_treemap_context(
                        council_href_builder=lambda council_id: app.jinja_env.globals["page_url"](
                            "council_detail",
                            council_id=council_id,
                        )
                    ),
                ),
            )
        )
        written_paths.append(
            _write_page(
                resolved_output_dir / "meetings" / "monthly.html",
                render_template("monthly_meetings_index.html", **build_monthly_meetings_index_context()),
            )
        )
        for group in list_monthly_meetings():
            year, month = group.month.split("-", 1)
            written_paths.append(
                _write_page(
                    resolved_output_dir / "meetings" / year / month / "index.html",
                    render_template(
                        "monthly_meetings.html",
                        **build_monthly_meetings_context(year=int(year), month=int(month)),
                    ),
                )
            )
        written_paths.append(
            _write_page(
                resolved_output_dir / "quality" / "meeting-gaps.html",
                render_template(
                    "meeting_gaps.html",
                    **build_meeting_gaps_context(
                        tab="active",
                        review_path=review_file,
                        allow_review_updates=False,
                    ),
                ),
            )
        )
        written_paths.append(
            _write_page(
                resolved_output_dir / "quality" / "meeting-gaps-ignored.html",
                render_template(
                    "meeting_gaps.html",
                    **build_meeting_gaps_context(
                        tab="ignored",
                        review_path=review_file,
                        allow_review_updates=False,
                    ),
                ),
            )
        )

        for council_id in sorted(load_council_lookup().keys()):
            written_paths.append(
                _write_page(
                    resolved_output_dir / "councils" / f"{council_id}.html",
                    render_template("council_detail.html", **build_council_detail_context(council_id)),
                )
            )

    written_paths.append(_write_page(resolved_output_dir / ".nojekyll", ""))
    return written_paths


def _write_page(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
