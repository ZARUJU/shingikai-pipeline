from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError, URLError

from shingikai.councils.mhlw import (
    CouncilPageParseResult,
    MHLW_SUPPORTED_HIERARCHY_ROOT_IDS,
    _normalize_anonymous_medical_committee_agenda,
    build_mhlw_export_plan,
    load_mhlw_council,
    parse_mhlw_hierarchy,
)
from shingikai.councils.mofa import (
    MOFA_COUNCIL_ID,
    MOFA_JINJI_COUNCIL_ID,
    MOFA_SUPPORTED_HIERARCHY_ROOT_IDS,
    build_mofa_export_plan,
    load_mofa_council,
    parse_mofa_hierarchy,
)
from shingikai.fetch_errors import clear_fetch_error, has_recorded_404, record_fetch_error
from shingikai.models.council import Council
from shingikai.quality import DEFAULT_ISSUES_PATH, DEFAULT_REVIEW_PATH, export_meeting_gap_issues
from shingikai.utils.io import (
    load_council,
    remove_files,
    write_council,
    write_documents,
    write_meetings,
    write_rosters,
)
from ui.export import export_static_site

ALL_KEYWORD = "all"
logger = logging.getLogger(__name__)
KNOWN_MOFA_COUNCIL_IDS = {MOFA_COUNCIL_ID, MOFA_JINJI_COUNCIL_ID}
ROOT_COUNCIL_IDS = {"mhlw", MOFA_COUNCIL_ID}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="審議会データを扱う CLI")
    subparsers = parser.add_subparsers(dest="resource", required=True)

    ops_parser = subparsers.add_parser("ops", help="運用単位で処理する")
    ops_subparsers = ops_parser.add_subparsers(dest="action", required=True)

    ops_add_parser = ops_subparsers.add_parser("add", help="新規登録向けに会議体データ一式を生成")
    ops_add_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    _add_shared_export_args(ops_add_parser, allow_stdout=False, allow_fixture=False)
    ops_add_parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="品質確認JSONの再生成を省略する",
    )
    ops_add_parser.set_defaults(handler=_handle_ops_add)

    ops_update_parser = ops_subparsers.add_parser("update", help="定期更新向けに開催記録を再取得する")
    ops_update_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    _add_shared_export_args(ops_update_parser, allow_stdout=False, allow_fixture=False)
    ops_update_parser.add_argument(
        "--refresh-hours",
        type=int,
        default=24,
        help="キャッシュがこの時間より古いページだけ再取得する",
    )
    ops_update_parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="品質確認JSONの再生成を省略する",
    )
    ops_update_parser.set_defaults(handler=_handle_ops_update)

    ops_repair_parser = ops_subparsers.add_parser("repair", help="修正後に対象会議体を再生成して品質確認する")
    ops_repair_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    _add_shared_export_args(ops_repair_parser, allow_stdout=False, allow_fixture=False)
    ops_repair_parser.add_argument(
        "--skip-quality",
        action="store_true",
        help="品質確認JSONの再生成を省略する",
    )
    ops_repair_parser.set_defaults(handler=_handle_ops_repair)

    council_parser = subparsers.add_parser("council", help="会議体データを扱う")
    council_subparsers = council_parser.add_subparsers(dest="action", required=True)

    council_show_parser = council_subparsers.add_parser("show", help="会議体の基本情報を表示")
    council_show_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    council_show_parser.set_defaults(handler=_handle_council_show)

    council_export_parser = council_subparsers.add_parser("export", help="会議体の基本情報を保存または表示")
    council_export_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    council_export_parser.add_argument("--stdout", action="store_true", help="保存せず標準出力に JSON を表示")
    council_export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="出力先のデータディレクトリ",
    )
    council_export_parser.set_defaults(handler=_handle_council_export)

    meetings_parser = subparsers.add_parser("meetings", help="開催状況データを扱う")
    meetings_subparsers = meetings_parser.add_subparsers(dest="action", required=True)

    meetings_export_parser = meetings_subparsers.add_parser("export", help="会議体ごとの開催状況を生成")
    meetings_export_parser.add_argument("council_id", help=f"会議体 ID (`{ALL_KEYWORD}` で全件)")
    _add_shared_export_args(meetings_export_parser, allow_stdout=True)
    meetings_export_parser.set_defaults(handler=_handle_meetings_export)

    family_export_parser = meetings_subparsers.add_parser(
        "export-family",
        help="親会議体配下を順番に処理して開催状況を生成",
    )
    family_export_parser.add_argument("council_id", help=f"親会議体 ID (`{ALL_KEYWORD}` で全階層起点)")
    _add_shared_export_args(family_export_parser, allow_stdout=False)
    family_export_parser.set_defaults(handler=_handle_family_export)

    hierarchy_parser = subparsers.add_parser("hierarchy", help="会議体階層データを扱う")
    hierarchy_subparsers = hierarchy_parser.add_subparsers(dest="action", required=True)

    hierarchy_export_parser = hierarchy_subparsers.add_parser(
        "export",
        help="一覧ページから会議体階層を生成",
    )
    hierarchy_export_parser.add_argument("council_id", help=f"起点会議体 ID (`{ALL_KEYWORD}` で全対応起点)")
    _add_shared_export_args(hierarchy_export_parser, allow_stdout=True)
    hierarchy_export_parser.set_defaults(handler=_handle_hierarchy_export)

    quality_parser = subparsers.add_parser("quality", help="品質確認データを扱う")
    quality_subparsers = quality_parser.add_subparsers(dest="action", required=True)

    quality_export_parser = quality_subparsers.add_parser(
        "export",
        help="欠番などの品質確認情報をJSONへ書き出す",
    )
    quality_export_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_ISSUES_PATH,
        help="出力先JSONファイル",
    )
    quality_export_parser.add_argument(
        "--review-path",
        type=Path,
        default=DEFAULT_REVIEW_PATH,
        help="欠番レビューJSONのパス",
    )
    quality_export_parser.add_argument(
        "--stdout",
        action="store_true",
        help="保存せず標準出力に JSON を表示",
    )
    quality_export_parser.set_defaults(handler=_handle_quality_export)

    ui_parser = subparsers.add_parser("ui", help="閲覧用UIを扱う")
    ui_subparsers = ui_parser.add_subparsers(dest="action", required=True)

    ui_export_parser = ui_subparsers.add_parser(
        "export",
        help="GitHub Pages 向けの静的 UI を書き出す",
    )
    ui_export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("site"),
        help="静的UIの出力先ディレクトリ",
    )
    ui_export_parser.add_argument(
        "--review-path",
        type=Path,
        default=DEFAULT_REVIEW_PATH,
        help="欠番レビューJSONのパス",
    )
    ui_export_parser.add_argument(
        "--base-path",
        default="",
        help="Pages 配下で公開するときのベースパス。例: /shingikai-pipeline",
    )
    ui_export_parser.set_defaults(handler=_handle_ui_export)

    return parser


def main() -> None:
    log_level_name = os.environ.get("SHINGIKAI_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = build_parser()
    args = parser.parse_args()
    logger.info("cli start: resource=%s action=%s", args.resource, getattr(args, "action", None))
    args.handler(args)


def _handle_council_show(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info("council show: targets=%s", ",".join(council_ids))
    councils = [load_council(council_id) for council_id in council_ids]
    if len(councils) == 1:
        print(json.dumps(councils[0].to_dict(), ensure_ascii=False, indent=2))
        return
    print(json.dumps([council.to_dict() for council in councils], ensure_ascii=False, indent=2))


def _handle_council_export(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info("council export: targets=%s output_dir=%s", ",".join(council_ids), args.output_dir)
    councils = [_build_known_council(council_id) for council_id in council_ids]
    if args.stdout:
        payload: object
        if len(councils) == 1:
            payload = councils[0].to_dict()
        else:
            payload = [council.to_dict() for council in councils]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    paths = [write_council(council, base_dir=args.output_dir) for council in councils]
    if len(paths) == 1:
        print(paths[0])
        return
    print(f"{len(paths)} council files written")


def _handle_ops_add(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info(
        "ops add: targets=%s output_dir=%s force=%s",
        ",".join(council_ids),
        args.output_dir,
        args.force,
    )
    _write_councils(council_ids, output_dir=args.output_dir)
    summaries = _export_many_council_meetings(
        council_ids,
        use_fixture=False,
        force=args.force,
        output_dir=args.output_dir,
    )
    if not args.skip_quality:
        summaries.append(_quality_summary(output_dir=args.output_dir))
    for line in summaries:
        print(line)


def _handle_ops_update(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info(
        "ops update: targets=%s output_dir=%s force=%s",
        ",".join(council_ids),
        args.output_dir,
        args.force,
    )
    for line in _export_many_council_meetings(
        council_ids,
        use_fixture=False,
        force=args.force,
        output_dir=args.output_dir,
        max_cache_age_hours=args.refresh_hours,
        reuse_existing_outputs=True,
    ):
        print(line)
    if not args.skip_quality:
        print(_quality_summary(output_dir=args.output_dir))


def _handle_ops_repair(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info(
        "ops repair: targets=%s output_dir=%s force=%s",
        ",".join(council_ids),
        args.output_dir,
        args.force,
    )
    _write_councils(council_ids, output_dir=args.output_dir)
    summaries = _export_many_council_meetings(
        council_ids,
        use_fixture=False,
        force=args.force,
        output_dir=args.output_dir,
    )
    if not args.skip_quality:
        summaries.append(_quality_summary(output_dir=args.output_dir))
    for line in summaries:
        print(line)


def _handle_meetings_export(args: argparse.Namespace) -> None:
    council_ids = _resolve_target_council_ids(args.council_id)
    logger.info(
        "meetings export: targets=%s output_dir=%s force=%s",
        ",".join(council_ids),
        args.output_dir,
        args.force,
    )
    if args.stdout and len(council_ids) > 1:
        payload = {}
        for council_id in council_ids:
            result = _export_council_meetings(
                council_id=council_id,
                use_fixture=args.use_fixture,
                force=args.force,
                stdout=False,
                output_dir=args.output_dir,
                print_result=False,
            )
            payload[council_id] = {
                "meetings": [meeting.model_dump(mode="json") for meeting in result.meetings],
                "documents": [document.model_dump(mode="json") for document in result.documents],
                "rosters": [roster.model_dump(mode="json") for roster in result.rosters],
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    if len(council_ids) == 1:
        _export_council_meetings(
            council_id=council_ids[0],
            use_fixture=args.use_fixture,
            force=args.force,
            stdout=args.stdout,
            output_dir=args.output_dir,
        )
        return

    for council_id in council_ids:
        try:
            result = _export_council_meetings(
                council_id=council_id,
                use_fixture=args.use_fixture,
                force=args.force,
                stdout=False,
                output_dir=args.output_dir,
                print_result=False,
            )
        except ValueError as exc:
            print(f"{council_id}: skipped ({exc})")
            continue
        print(
            f"{council_id}: "
            f"{len(result.meetings)} meeting files, "
            f"{len(result.documents)} document files, "
            f"{len(result.rosters)} roster files"
        )


def _handle_family_export(args: argparse.Namespace) -> None:
    results = []
    root_ids = _resolve_family_root_ids(args.council_id)
    logger.info(
        "meetings export-family: roots=%s output_dir=%s force=%s",
        ",".join(root_ids),
        args.output_dir,
        args.force,
    )
    for root_id in root_ids:
        for council in _list_council_family(root_id):
            try:
                result = _export_council_meetings(
                    council_id=council.council_id,
                    use_fixture=args.use_fixture,
                    force=args.force,
                    stdout=False,
                    output_dir=args.output_dir,
                    print_result=False,
                )
            except ValueError as exc:
                results.append(f"{council.council_id}: skipped ({exc})")
                continue
            results.append(
                f"{council.council_id}: "
                f"{len(result.meetings)} meeting files, "
                f"{len(result.documents)} document files, "
                f"{len(result.rosters)} roster files"
            )

    for line in results:
        print(line)


def _handle_hierarchy_export(args: argparse.Namespace) -> None:
    root_ids = _resolve_hierarchy_root_ids(args.council_id)
    logger.info(
        "hierarchy export: roots=%s output_dir=%s force=%s",
        ",".join(root_ids),
        args.output_dir,
        args.force,
    )
    payload: dict[str, list[dict[str, object]]] = {}
    written_count = 0

    for root_id in root_ids:
        if root_id in KNOWN_MOFA_COUNCIL_IDS:
            councils = parse_mofa_hierarchy(council_id=root_id, use_fixture=args.use_fixture, force=args.force)
        else:
            councils = parse_mhlw_hierarchy(council_id=root_id, use_fixture=args.use_fixture, force=args.force)
        if args.stdout:
            payload[root_id] = [council.to_dict() for council in councils]
            continue
        paths = [write_council(council, base_dir=args.output_dir) for council in councils]
        written_count += len(paths)

    if args.stdout:
        if len(root_ids) == 1:
            print(json.dumps(payload[root_ids[0]], ensure_ascii=False, indent=2))
            return
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"{written_count} council files written")


def _handle_quality_export(args: argparse.Namespace) -> None:
    logger.info("quality export: output=%s review_path=%s", args.output, args.review_path)
    if args.stdout:
        path = export_meeting_gap_issues(output_path=args.output, review_path=args.review_path)
        print(path.read_text(encoding="utf-8"), end="")
        return
    path = export_meeting_gap_issues(output_path=args.output, review_path=args.review_path)
    print(path)


def _handle_ui_export(args: argparse.Namespace) -> None:
    logger.info(
        "ui export: output_dir=%s review_path=%s base_path=%s",
        args.output_dir,
        args.review_path,
        args.base_path,
    )
    paths = export_static_site(
        args.output_dir,
        review_path=args.review_path,
        base_path=args.base_path,
    )
    print(f"{len(paths)} files written to {args.output_dir}")


def _write_councils(council_ids: list[str], *, output_dir: Path) -> None:
    councils = [_build_known_council(council_id) for council_id in council_ids]
    for council in councils:
        write_council(council, base_dir=output_dir)


def _export_many_council_meetings(
    council_ids: list[str],
    *,
    use_fixture: bool,
    force: bool,
    output_dir: Path,
    max_cache_age_hours: int | None = None,
    reuse_existing_outputs: bool = False,
) -> list[str]:
    summaries: list[str] = []
    for council_id in council_ids:
        try:
            result = _export_council_meetings(
                council_id=council_id,
                use_fixture=use_fixture,
                force=force,
                stdout=False,
                output_dir=output_dir,
                print_result=False,
                max_cache_age_hours=max_cache_age_hours,
                reuse_existing_outputs=reuse_existing_outputs,
            )
        except ValueError as exc:
            summaries.append(f"{council_id}: skipped ({exc})")
            continue
        summaries.append(
            f"{council_id}: "
            f"{len(result.meetings)} meeting files, "
            f"{len(result.documents)} document files, "
            f"{len(result.rosters)} roster files"
        )
    return summaries


def _quality_summary(*, output_dir: Path) -> str:
    path = export_meeting_gap_issues(
        output_path=output_dir / "_quality" / "meeting_gap_issues.json",
        data_root=output_dir / "councils",
        review_path=output_dir / "_reviews" / "meeting_gap_reviews.json",
    )
    return f"quality: {path}"


def _add_shared_export_args(
    parser: argparse.ArgumentParser,
    *,
    allow_stdout: bool,
    allow_fixture: bool = True,
) -> None:
    if allow_fixture:
        parser.add_argument(
            "--use-fixture",
            action="store_true",
            help="キャッシュ済み HTML を優先して使う（開発用）",
        )
    parser.add_argument(
        "--force",
        action="store_true",
        help="キャッシュを使わず再取得して更新する",
    )
    if allow_stdout:
        parser.add_argument(
            "--stdout",
            action="store_true",
            help="保存せず標準出力に JSON を表示",
        )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data"),
        help="出力先のデータディレクトリ",
    )


def _build_known_council(council_id: str) -> Council:
    if council_id in KNOWN_MOFA_COUNCIL_IDS:
        return load_mofa_council(council_id)
    return load_mhlw_council(council_id)


def _resolve_target_council_ids(council_id: str) -> list[str]:
    if council_id != ALL_KEYWORD:
        return [council_id]
    return _list_all_council_ids()


def _resolve_family_root_ids(council_id: str) -> list[str]:
    if council_id != ALL_KEYWORD:
        return [council_id]
    return [*MHLW_SUPPORTED_HIERARCHY_ROOT_IDS, *MOFA_SUPPORTED_HIERARCHY_ROOT_IDS]


def _resolve_hierarchy_root_ids(council_id: str) -> list[str]:
    if council_id != ALL_KEYWORD:
        return [council_id]
    return [*MHLW_SUPPORTED_HIERARCHY_ROOT_IDS, *MOFA_SUPPORTED_HIERARCHY_ROOT_IDS]


def _list_all_council_ids() -> list[str]:
    council_ids: list[str] = []
    for council_dir in sorted(Path("data/councils").iterdir()):
        if not council_dir.is_dir():
            continue
        if not (council_dir / "council.json").exists():
            continue
        council_ids.append(council_dir.name)
    return council_ids


def _export_council_meetings(
    *,
    council_id: str,
    use_fixture: bool,
    force: bool,
    stdout: bool,
    output_dir: Path,
    print_result: bool = True,
    max_cache_age_hours: int | None = None,
    reuse_existing_outputs: bool = False,
):
    council = load_council(council_id)
    if council.council_id in ROOT_COUNCIL_IDS:
        result = CouncilPageParseResult(meetings=[], documents=[], rosters=[])
        if stdout:
            payload = {
                "meetings": [],
                "documents": [],
                "rosters": [],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return result
        write_council(council, base_dir=output_dir)
        if print_result:
            print("0 meeting files written, 0 document files written, 0 roster files written")
        return result
    if council.council_id in KNOWN_MOFA_COUNCIL_IDS:
        plan = build_mofa_export_plan(
            council=council,
            use_fixture=use_fixture,
            force=force,
            output_dir=output_dir,
            max_cache_age_hours=max_cache_age_hours,
            reuse_existing_outputs=reuse_existing_outputs,
        )
    else:
        plan = build_mhlw_export_plan(
            council=council,
            use_fixture=use_fixture,
            force=force,
            output_dir=output_dir,
            max_cache_age_hours=max_cache_age_hours,
            reuse_existing_outputs=reuse_existing_outputs,
        )
    result = plan.result
    related_councils = plan.related_councils
    related_results = plan.related_results
    stale_paths = plan.stale_paths
    skip_write = getattr(plan, "skip_write", False)

    if stdout:
        payload = {
            "meetings": [meeting.model_dump(mode="json") for meeting in result.meetings],
            "documents": [document.model_dump(mode="json") for document in result.documents],
            "rosters": [roster.model_dump(mode="json") for roster in result.rosters],
        }
        if related_councils:
            payload["related_councils"] = {
                related_council.council_id: {
                    "council": related_council.model_dump(mode="json", by_alias=True),
                    "meetings": [
                        meeting.model_dump(mode="json")
                        for meeting in related_results[related_council.council_id].meetings
                    ],
                    "documents": [
                        document.model_dump(mode="json")
                        for document in related_results[related_council.council_id].documents
                    ],
                    "rosters": [
                        roster.model_dump(mode="json")
                        for roster in related_results[related_council.council_id].rosters
                    ],
                }
                for related_council in related_councils
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return result

    meeting_paths = []
    document_paths = []
    roster_paths = []
    if not skip_write:
        write_council(council, base_dir=output_dir)
        meeting_paths = write_meetings(council_id, result.meetings, base_dir=output_dir)
        document_paths = write_documents(council_id, result.documents, base_dir=output_dir)
        roster_paths = write_rosters(council_id, result.rosters, base_dir=output_dir)
        for related_council in related_councils:
            related_result = related_results[related_council.council_id]
            write_council(related_council, base_dir=output_dir)
            write_meetings(related_council.council_id, related_result.meetings, base_dir=output_dir)
            write_documents(related_council.council_id, related_result.documents, base_dir=output_dir)
            write_rosters(related_council.council_id, related_result.rosters, base_dir=output_dir)
    if stale_paths:
        remove_files(stale_paths)
    if print_result:
        if skip_write:
            print(
                f"{len(result.meetings)} meeting files unchanged, "
                f"{len(result.documents)} document files unchanged, "
                f"{len(result.rosters)} roster files unchanged"
            )
        else:
            print(
                f"{len(meeting_paths)} meeting files written, "
                f"{len(document_paths)} document files written, "
                f"{len(roster_paths)} roster files written"
            )
    return result


def _list_council_family(root_council_id: str) -> list[Council]:
    councils = []
    for council_dir in sorted(Path("data/councils").iterdir()):
        if not council_dir.is_dir():
            continue
        council_path = council_dir / "council.json"
        if not council_path.exists():
            continue
        council = load_council(council_dir.name)
        if council.council_id == root_council_id:
            councils.append(council)
            continue
        parent = council.parent
        while True:
            try:
                parent_council = load_council(parent)
            except FileNotFoundError:
                break
            if parent_council.council_id == root_council_id:
                councils.append(council)
                break
            parent = parent_council.parent
    councils.sort(key=lambda item: item.council_id)
    return councils


def _load_cached_html(*, url: str, path: Path, fetcher, use_fixture: bool, force: bool, required: bool = True) -> str | None:
    del use_fixture
    if not force and path.exists():
        logger.debug("cache hit: %s", path)
        return path.read_text(encoding="utf-8")
    if not force and has_recorded_404(url):
        logger.info("skip fetch due to recorded 404: %s", url)
        if required:
            raise ValueError(f"recorded 404 for url: {url}")
        return None
    logger.info("cache miss: %s", path)
    try:
        html = fetcher()
        clear_fetch_error(url)
        return html
    except HTTPError as exc:
        if exc.code == 404:
            record_fetch_error(url, status_code=404, reason=str(exc.reason))
        if required:
            raise
        logger.warning("optional fetch failed: %s (%s)", path, exc)
        return None
    except URLError as exc:
        if required:
            raise
        logger.warning("optional fetch failed: %s (%s)", path, exc)
        return None
