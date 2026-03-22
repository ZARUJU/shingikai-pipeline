from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import BaseModel

from shingikai.fetch_errors import clear_fetch_error, has_recorded_404, record_fetch_error
from shingikai.models.council import Council, SourceUrls
from shingikai.models.document import CouncilDocument, DocumentBody
from shingikai.models.meeting import Meeting, MeetingLink
from shingikai.models.roster import CouncilRoster
from shingikai.utils.cache import cached_html_path, is_cache_fresh
from shingikai.utils.fetch import fetch_html
from shingikai.utils.html import cell_text, extract_agenda_from_detail_page, extract_links
from shingikai.utils.io import load_council, load_documents, load_meetings, load_rosters, meetings_dir, rosters_dir
from shingikai.utils.normalize import (
    is_roster_link_title,
    normalize_dash,
    parse_agenda_text,
    parse_held_on_text,
    parse_round_label,
    parse_round_labels,
)

logger = logging.getLogger(__name__)

SOCIAL_SECURITY_COUNCIL_ID = "social-security-council"
SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID = "social-security-council-statistics-subcommittee"
MHLW_SUPPORTED_HIERARCHY_ROOT_IDS = [SOCIAL_SECURITY_COUNCIL_ID]
ANONYMOUS_MEDICAL_COMMITTEE_ID = "index-13914"
MEDICAL_INSURANCE_SUBCOMMITTEE_ID = "newpage-28708"
CARE_BENEFIT_SUBCOMMITTEE_ID = "shingi-hosho-126698-00022"
JUDO_THERAPY_SUBCOMMITTEE_ID = "shingi-hosho-126707"
MHLW_INDEX_SOURCE_URL = "https://www.mhlw.go.jp/stf/shingi/indexshingi.html"
CARE_BENEFIT_INTERNAL_COMMITTEES = {
    "介護報酬改定検証・研究委員会": "shingi-hosho-126698-00022-kaigo-hoshu-kaitei-kensho-kenkyu-iinkai",
    "介護事業経営調査委員会": "shingi-hosho-126698-00022-kaigo-jigyo-keiei-chosa-iinkai",
}


class CouncilPageParseResult(BaseModel):
    """会議一覧ページの解析結果を保持する。"""

    meetings: list[Meeting]
    documents: list[CouncilDocument]
    rosters: list[CouncilRoster]


@dataclass(frozen=True)
class MhlwHierarchyRule:
    """厚労省一覧ページから階層を起こすための設定。"""

    root_href: str
    page_url: str
    root_parent: str
    known_council_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MhlwCouncilRule:
    """厚労省系会議体ごとの例外設定。

    `legacy_meeting_page_urls`:
    現行ページ以外に読み込むべき旧ページや WARP アーカイブ。

    `follow_related_meeting_pages`:
    一覧ページ内の「第X回まで」リンクをたどって追加ページを読むかどうか。

    `agenda_normalizer`:
    会議体固有の議題整形ルール名。

    `split_child_committees`:
    親ページに混在している内部委員会データを子会議体へ振り分ける設定。
    """

    hierarchy: MhlwHierarchyRule | None = None
    legacy_meeting_page_urls: tuple[str, ...] = ()
    follow_related_meeting_pages: bool = False
    agenda_normalizer: str | None = None
    split_child_committees: dict[str, str] = field(default_factory=dict)
    stale_meeting_ids: tuple[str, ...] = ()
    stale_roster_ids: tuple[str, ...] = ()


@dataclass
class MhlwExportPlan:
    """厚労省系会議体の出力計画。

    処理順序は次の通り。
    1. 現行の会議一覧を読む
    2. 必要なら旧ページや WARP を追加で読む
    3. 必要なら関連一覧ページをたどって補完する
    4. 詳細ページから議題と名簿リンクを補完する
    5. 会議体固有の議題整形を適用する
    6. 必要なら親ページ内の子会議体データを分離する
    7. 既存成果物のうち不要になるファイルを `stale_paths` に積む
    """

    result: CouncilPageParseResult
    related_councils: list[Council] = field(default_factory=list)
    related_results: dict[str, CouncilPageParseResult] = field(default_factory=dict)
    stale_paths: list[Path] = field(default_factory=list)


@dataclass(frozen=True)
class ExistingCouncilData:
    meetings: dict[str, Meeting]
    documents: dict[str, CouncilDocument]
    rosters: dict[str, CouncilRoster]


MHLW_COUNCIL_RULES: dict[str, MhlwCouncilRule] = {
    SOCIAL_SECURITY_COUNCIL_ID: MhlwCouncilRule(
        hierarchy=MhlwHierarchyRule(
            root_href="/stf/shingi/shingi-hosho_126692.html",
            page_url=MHLW_INDEX_SOURCE_URL,
            root_parent="厚生労働省",
            known_council_ids=(
                SOCIAL_SECURITY_COUNCIL_ID,
                SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID,
            ),
        ),
        stale_meeting_ids=(
            "2001-02-27-no-round",
            "2002-03-12-no-round",
            "2017-01-29-no-round",
        ),
        stale_roster_ids=("2017-01-29-no-round",),
    ),
    SOCIAL_SECURITY_COUNCIL_STATISTICS_SUBCOMMITTEE_ID: MhlwCouncilRule(
        legacy_meeting_page_urls=(
            "https://warp.ndl.go.jp/20240620/20240601094408/www.mhlw.go.jp/stf/shingi/shingi-hosho_126693.html",
        ),
    ),
    ANONYMOUS_MEDICAL_COMMITTEE_ID: MhlwCouncilRule(
        agenda_normalizer="anonymous_medical",
    ),
    MEDICAL_INSURANCE_SUBCOMMITTEE_ID: MhlwCouncilRule(
        follow_related_meeting_pages=True,
        agenda_normalizer="medical_insurance",
    ),
    JUDO_THERAPY_SUBCOMMITTEE_ID: MhlwCouncilRule(
        legacy_meeting_page_urls=(
            "https://www.mhlw.go.jp/stf/shingi/shingi-hosho_126707_old.html",
        ),
    ),
    CARE_BENEFIT_SUBCOMMITTEE_ID: MhlwCouncilRule(
        follow_related_meeting_pages=True,
        split_child_committees=CARE_BENEFIT_INTERNAL_COMMITTEES,
    ),
}


def fetch_mhlw_html(url: str, timeout: int = 30) -> str:
    """厚労省系ページを取得する。"""

    return fetch_html(url, timeout=timeout)


def fixture_html_path(url: str) -> Path:
    """URL に対応するキャッシュ HTML パスを返す。"""

    return cached_html_path(url)


def load_mhlw_council(council_id: str) -> Council:
    """厚労省系 council を読み込む。

    通常は `data/councils/*/council.json` を読む。
    JSON を持たない合成 council だけはコード上で組み立てる。
    """

    if council_id in CARE_BENEFIT_INTERNAL_COMMITTEES.values():
        return _build_care_benefit_internal_committee_council(council_id)
    return load_council(council_id)


def get_mhlw_council_rule(council_id: str) -> MhlwCouncilRule | None:
    """会議体固有の特殊ルールを返す。"""

    return MHLW_COUNCIL_RULES.get(council_id)


def get_mhlw_hierarchy_rule(council_id: str) -> MhlwHierarchyRule:
    """階層構築ルールを返す。"""

    rule = _require_mhlw_rule(council_id)
    if rule.hierarchy is None:
        raise ValueError(f"hierarchy export is not supported for council: {council_id}")
    return rule.hierarchy


def parse_mhlw_hierarchy(
    *,
    council_id: str,
    use_fixture: bool,
    force: bool,
    max_cache_age_hours: int | None = None,
) -> list[Council]:
    """厚労省一覧ページから指定 root 配下の階層を構築する。"""

    hierarchy = get_mhlw_hierarchy_rule(council_id)
    html = _load_cached_html(
        url=hierarchy.page_url,
        path=fixture_html_path(hierarchy.page_url),
        fetcher=lambda: fetch_mhlw_html(hierarchy.page_url),
        use_fixture=use_fixture,
        force=force,
        max_cache_age_hours=max_cache_age_hours,
    )
    return parse_hierarchy_page(
        html,
        root_href=hierarchy.root_href,
        page_url=hierarchy.page_url,
        root_parent=hierarchy.root_parent,
        known_ids=_build_known_ids(hierarchy.known_council_ids),
    )


def build_mhlw_export_plan(
    *,
    council: Council,
    use_fixture: bool,
    force: bool,
    output_dir: Path,
    max_cache_age_hours: int | None = None,
    reuse_existing_outputs: bool = False,
) -> MhlwExportPlan:
    """厚労省系 council の会議データをどう組み立てるかを返す。"""

    rule = MHLW_COUNCIL_RULES.get(council.council_id)
    existing_data = None
    if reuse_existing_outputs:
        existing_data = _load_existing_council_data(council_id=council.council_id, output_dir=output_dir)
    result = _build_base_parse_result(
        council=council,
        rule=rule,
        use_fixture=use_fixture,
        force=force,
        max_cache_age_hours=max_cache_age_hours,
        existing_data=existing_data,
    )
    _normalize_agenda_for_council(result, rule=rule)

    related_councils: list[Council] = []
    related_results: dict[str, CouncilPageParseResult] = {}
    stale_paths = _build_stale_paths(rule=rule, council_id=council.council_id, output_dir=output_dir)

    split_child_committees = rule.split_child_committees if rule is not None else {}
    if split_child_committees:
        result, related_councils, related_results, split_stale_paths = _split_care_benefit_internal_committee_data(
            council=council,
            result=result,
            output_dir=output_dir,
        )
        stale_paths.extend(split_stale_paths)

    return MhlwExportPlan(
        result=result,
        related_councils=related_councils,
        related_results=related_results,
        stale_paths=stale_paths,
    )


def parse_hierarchy_page(
    html: str,
    *,
    root_href: str,
    page_url: str,
    root_parent: str,
    known_ids: dict[str, str] | None = None,
) -> list[Council]:
    """厚労省一覧ページの `<ul class="m-listLink">` を再帰的に解析する。"""

    soup = BeautifulSoup(html, "html.parser")
    root_anchor = soup.find("a", href=lambda href: href == root_href)
    if root_anchor is None:
        raise ValueError("root council entry not found")

    root_item = root_anchor.find_parent("li")
    if root_item is None:
        raise ValueError("root council list item not found")

    seen: set[str] = set()
    return _parse_hierarchy_item(
        root_item,
        parent=root_parent,
        page_url=page_url,
        seen=seen,
        known_ids=known_ids or {},
    )


def parse_meeting_page(
    html: str,
    *,
    council_id: str,
    source_url: str,
    title: str,
) -> CouncilPageParseResult:
    """会議一覧表を会議・文書・名簿に分解する。

    厚労省ページは会議体ごとに HTML の揺れが大きい。
    この関数はまず 6 列構成の表を探し、行ごとに
    「回次」「開催日」「議題」「議事録」「資料」「開催案内」
    を抽出して共通モデルへ寄せる。
    """

    soup = BeautifulSoup(html, "html.parser")
    table = _find_meeting_table(soup)
    if table is None:
        raise ValueError("meeting table not found")

    meetings: list[Meeting] = []
    documents: list[CouncilDocument] = []
    rosters: list[CouncilRoster] = []

    for row in table.select("tr"):
        cells = _extract_row_cells(row)
        if not cells or all(cell.name == "th" for cell in cells):
            continue
        if len(cells) != 6:
            continue

        round_label_text = normalize_dash(cell_text(cells[0]))
        round_label = parse_round_label(round_label_text)
        round_labels = parse_round_labels(round_label_text)
        held_on_text = normalize_dash(cell_text(cells[1]))
        if held_on_text is None:
            continue
        held_on = parse_held_on_text(held_on_text)
        agenda_text = normalize_dash(cell_text(cells[2]))
        agenda = parse_agenda_text(agenda_text)
        if not agenda and agenda_text:
            agenda = ["".join(part.strip() for part in agenda_text.splitlines() if part.strip())]
        minutes_links = extract_links(cells[3], source_url=source_url)
        materials_links = extract_links(cells[4], source_url=source_url)
        announcement_links = extract_links(cells[5], source_url=source_url)
        item_source_url = _pick_source_url(
            announcement_links=announcement_links,
            materials_links=materials_links,
            minutes_links=minutes_links,
            default_source_url=source_url,
        )
        document_kind = _detect_document_kind(
            round_label=round_label,
            agenda=agenda,
            agenda_text=agenda_text,
            minutes_links=minutes_links,
            announcement_links=announcement_links,
            materials_links=materials_links,
        )
        document_title = _build_document_title(
            agenda=agenda,
            agenda_text=agenda_text,
            held_on=held_on,
            council_title=title,
            document_kind=document_kind[0] if document_kind is not None else None,
        )
        roster_links = _extract_roster_links(materials_links)

        if roster_links:
            rosters.append(
                CouncilRoster(
                    id=held_on,
                    council_id=council_id,
                    as_of=held_on,
                    source_url=roster_links[0].url,
                    links=roster_links,
                )
            )

        if document_kind is not None:
            documents.append(
                CouncilDocument(
                    id=_build_document_id(held_on=held_on, document_type=document_kind[0]),
                    council_id=council_id,
                    title=document_title,
                    published_on=held_on,
                    document_type=document_kind[1],
                    source_url=item_source_url,
                    links=materials_links,
                    body=DocumentBody(status="not_built"),
                )
            )
            continue

        if _is_roster_only_row(
            round_label=round_label,
            agenda=agenda,
            minutes_links=minutes_links,
            materials_links=materials_links,
            announcement_links=announcement_links,
        ):
            continue

        expanded_round_labels = round_labels or [round_label]
        agendas_by_round = _split_joint_meeting_agenda(expanded_round_labels, agenda)
        for index, expanded_round_label in enumerate(expanded_round_labels):
            meetings.append(
                Meeting(
                    id=_build_meeting_id(held_on=held_on, round_label=expanded_round_label),
                    council_id=council_id,
                    round_label=expanded_round_label,
                    held_on=held_on,
                    agenda=agendas_by_round[index],
                    source_url=item_source_url,
                    minutes_links=minutes_links,
                    materials_links=materials_links,
                    announcement_links=announcement_links,
                )
            )

    return CouncilPageParseResult(meetings=meetings, documents=documents, rosters=_dedupe_rosters(rosters))


def extract_roster_links_from_material_page(html: str, page_url: str) -> list[MeetingLink]:
    """資料詳細ページから名簿リンクだけを拾う。"""

    soup = BeautifulSoup(html, "html.parser")
    links: list[MeetingLink] = []

    for anchor in soup.select("a[href]"):
        title = cell_text(anchor)
        href = anchor.get("href")
        if href is None or not is_roster_link_title(title):
            continue
        links.append(MeetingLink(title=title, url=urljoin(page_url, href)))

    deduped: dict[str, MeetingLink] = {}
    for link in links:
        deduped[link.url] = link
    return list(deduped.values())


def extract_related_meeting_page_links(html: str, page_url: str) -> list[str]:
    """会議一覧から旧ページへのリンクを抽出する。"""

    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    archive_link_pattern = re.compile(
        r"^(?:"
        r"～?第[０-９0-9]+回までの会議|"
        r"第[０-９0-9]+回～第[０-９0-9]+回会議|"
        r"過去の開催内容（第[０-９0-9]+回[～~\-−ー－]第[０-９0-9]+回）"
        r")$"
    )
    for anchor in soup.select("a[href]"):
        text = cell_text(anchor)
        if not archive_link_pattern.fullmatch(text):
            continue
        href = anchor.get("href")
        if href is None:
            continue
        links.append(urljoin(page_url, href))
    deduped: list[str] = []
    for link in links:
        if link == page_url or link in deduped:
            continue
        deduped.append(link)
    return deduped


def _require_mhlw_rule(council_id: str) -> MhlwCouncilRule:
    rule = MHLW_COUNCIL_RULES.get(council_id)
    if rule is None:
        raise ValueError(f"unknown mhlw council rule: {council_id}")
    return rule


def _build_known_ids(council_ids: tuple[str, ...]) -> dict[str, str]:
    known_ids: dict[str, str] = {}
    for council_id in council_ids:
        council = load_mhlw_council(council_id)
        known_ids[council.source_urls.meetings] = council_id
    return known_ids


def _build_base_parse_result(
    *,
    council: Council,
    rule: MhlwCouncilRule | None,
    use_fixture: bool,
    force: bool,
    max_cache_age_hours: int | None,
    existing_data: ExistingCouncilData | None,
) -> CouncilPageParseResult:
    page_url = council.source_urls.meetings
    html = _load_mhlw_html(
        url=page_url,
        use_fixture=use_fixture,
        force=force,
        max_cache_age_hours=max_cache_age_hours,
    )
    result = parse_meeting_page(
        html,
        council_id=council.council_id,
        source_url=page_url,
        title=council.title,
    )

    archive_page_urls = list(council.source_urls.meetings_archives)
    if rule is not None:
        archive_page_urls.extend(rule.legacy_meeting_page_urls)
    if rule is not None and rule.follow_related_meeting_pages:
        archive_page_urls.extend(extract_related_meeting_page_links(html, page_url))

    seen_archive_page_urls: set[str] = set()
    for archive_page_url in archive_page_urls:
        if archive_page_url in seen_archive_page_urls:
            continue
        seen_archive_page_urls.add(archive_page_url)
        archive_html = _load_mhlw_html(
            url=archive_page_url,
            use_fixture=use_fixture,
            force=force,
            max_cache_age_hours=max_cache_age_hours,
        )
        archive_result = parse_meeting_page(
            archive_html,
            council_id=council.council_id,
            source_url=archive_page_url,
            title=council.title,
        )
        result = _merge_parse_results(result, archive_result)

    meeting_ids_to_enrich: set[str] | None = None
    if existing_data is not None:
        result, meeting_ids_to_enrich = _reuse_existing_outputs(result, existing_data=existing_data)

    _enrich_parse_result_from_detail_pages(
        result,
        load_html=lambda url: _load_mhlw_html(
            url=url,
            use_fixture=use_fixture,
            force=force,
            required=False,
            max_cache_age_hours=max_cache_age_hours,
        ),
        target_meeting_ids=meeting_ids_to_enrich,
    )
    return result


def _build_stale_paths(*, rule: MhlwCouncilRule | None, council_id: str, output_dir: Path) -> list[Path]:
    if rule is None:
        return []

    stale_paths = [meetings_dir(council_id, base_dir=output_dir) / f"{meeting_id}.json" for meeting_id in rule.stale_meeting_ids]
    stale_paths.extend(
        rosters_dir(council_id, base_dir=output_dir) / f"{roster_id}.json" for roster_id in rule.stale_roster_ids
    )
    return stale_paths


def _load_mhlw_html(
    *,
    url: str,
    use_fixture: bool,
    force: bool,
    required: bool = True,
    max_cache_age_hours: int | None = None,
) -> str | None:
    return _load_cached_html(
        url=url,
        path=fixture_html_path(url),
        fetcher=lambda: fetch_mhlw_html(url),
        use_fixture=use_fixture,
        force=force,
        required=required,
        max_cache_age_hours=max_cache_age_hours,
    )


def _load_cached_html(
    *,
    url: str,
    path: Path,
    fetcher,
    use_fixture: bool,
    force: bool,
    required: bool = True,
    max_cache_age_hours: int | None = None,
) -> str | None:
    if use_fixture:
        if path.exists():
            logger.debug("fixture hit: %s", path)
            return path.read_text(encoding="utf-8")
        if required:
            raise ValueError(f"fixture html not found: {path}")
        return None
    if not force and path.exists() and max_cache_age_hours is None:
        logger.debug("cache hit: %s", path)
        return path.read_text(encoding="utf-8")
    if not force and path.exists() and max_cache_age_hours is not None and is_cache_fresh(path, max_age_hours=max_cache_age_hours):
        logger.debug("fresh cache hit: %s", path)
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


def _find_meeting_table(soup):
    table = soup.select_one("table.m-tableFlex")
    if table is not None:
        return table

    candidates: list[tuple[int, int, object]] = []
    for candidate in soup.find_all("table"):
        parsed_rows = 0
        round_rows = 0
        for row in candidate.select("tr"):
            cells = _extract_row_cells(row)
            if len(cells) != 6:
                continue
            parsed_rows += 1
            round_label_text = normalize_dash(cell_text(cells[0]))
            if round_label_text is None:
                continue
            if parse_round_label(round_label_text) is not None or parse_round_labels(round_label_text):
                round_rows += 1
        if round_rows == 0:
            continue
        candidates.append((round_rows, parsed_rows, candidate))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def _parse_hierarchy_item(
    li,
    *,
    parent: str,
    page_url: str,
    seen: set[str],
    known_ids: dict[str, str],
) -> list[Council]:
    anchor = li.find("a", href=True)
    if anchor is None:
        return []

    source_url = urljoin(page_url, anchor["href"])
    council_id = _derive_council_id(source_url, known_ids=known_ids)
    if council_id in seen:
        return []

    seen.add(council_id)
    title = anchor.get_text(strip=True)
    councils = [
        Council(
            council_id=council_id,
            title=title,
            parent=parent,
            source_urls=SourceUrls(
                portal=source_url,
                meetings=source_url,
            ),
        )
    ]

    for child_list in li.find_all("ul", class_="m-listLink", recursive=False):
        for child_item in child_list.find_all("li", recursive=False):
            councils.extend(
                _parse_hierarchy_item(
                    child_item,
                    parent=council_id,
                    page_url=page_url,
                    seen=seen,
                    known_ids=known_ids,
                )
            )

    return councils


def _derive_council_id(source_url: str, *, known_ids: dict[str, str]) -> str:
    if source_url in known_ids:
        return known_ids[source_url]

    basename = source_url.rstrip("/").split("/")[-1]
    stem = basename.rsplit(".", 1)[0]
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")


def _extract_row_cells(row) -> list:
    cells = row.find_all(["th", "td"], recursive=False)
    if len(cells) == 6:
        return cells
    if len(cells) != 3:
        return cells

    nested_link_cells = cells[2].find_all("td")
    if len(nested_link_cells) < 3:
        return cells

    agenda_cell = BeautifulSoup(str(cells[2]), "html.parser").find("td")
    if agenda_cell is None:
        return cells
    for nested_cell in agenda_cell.find_all("td"):
        nested_cell.decompose()

    return [cells[0], cells[1], agenda_cell, *nested_link_cells[-3:]]


def _extract_roster_links(links: list[MeetingLink]) -> list[MeetingLink]:
    return [link for link in links if is_roster_link_title(link.title)]


def _split_joint_meeting_agenda(round_labels: list[int | None], agenda: list[str]) -> list[list[str]]:
    if len(round_labels) <= 1:
        return [agenda]

    normalized_round_labels = [round_label for round_label in round_labels if round_label is not None]
    if len(normalized_round_labels) != len(round_labels):
        return [agenda for _ in round_labels]

    split_agenda = _split_embedded_round_markers(agenda, normalized_round_labels)
    grouped_agenda: list[list[str]] = [[] for _ in round_labels]
    current_index = 0
    marker_found = False

    for item in split_agenda:
        round_index = _match_round_index(item, normalized_round_labels)
        if round_index is not None:
            current_index = round_index
            marker_found = True
            continue
        grouped_agenda[current_index].append(item)

    if not marker_found:
        return [agenda[:] for _ in round_labels]

    for index, items in enumerate(grouped_agenda):
        if items:
            continue
        grouped_agenda[index] = agenda[:]
    return grouped_agenda


def _split_embedded_round_markers(agenda: list[str], round_labels: list[int]) -> list[str]:
    marker_pattern = "|".join(
        [rf"第{round_label}回" for round_label in round_labels]
        + [rf"{round_label}回" for round_label in round_labels]
        + [rf"第{str(round_label).translate(str.maketrans('0123456789', '０１２３４５６７８９'))}回" for round_label in round_labels]
        + [rf"{str(round_label).translate(str.maketrans('0123456789', '０１２３４５６７８９'))}回" for round_label in round_labels]
    )
    marker_regex = re.compile(marker_pattern)
    split_items: list[str] = []
    for item in agenda:
        last_index = 0
        parts: list[str] = []
        for match in marker_regex.finditer(item):
            if match.start() == 0:
                continue
            parts.append(item[last_index:match.start()])
            last_index = match.start()
        parts.append(item[last_index:])
        for part in parts:
            normalized = part.strip()
            if normalized:
                split_items.append(normalized)
    return split_items


def _match_round_index(item: str, round_labels: list[int]) -> int | None:
    match = re.match(r"^第?\s*([0-9０-９]+)回", item)
    if match is None:
        return None
    value = int(match.group(1).translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    try:
        return round_labels.index(value)
    except ValueError:
        return None


def _pick_source_url(
    *,
    announcement_links: list[MeetingLink],
    materials_links: list[MeetingLink],
    minutes_links: list[MeetingLink],
    default_source_url: str,
) -> str:
    for links in (announcement_links, materials_links, minutes_links):
        if links:
            return links[0].url
    return default_source_url


def _build_document_title(
    agenda: list[str],
    agenda_text: str | None,
    held_on: str,
    council_title: str,
    document_kind: str | None,
) -> str:
    if document_kind == "material" and agenda:
        return "".join(agenda)
    if agenda:
        return agenda[0]
    if agenda_text:
        return agenda_text
    return f"{held_on} {council_title}"


def _is_roster_only_row(
    *,
    round_label: int | None,
    agenda: list[str],
    minutes_links: list[MeetingLink],
    materials_links: list[MeetingLink],
    announcement_links: list[MeetingLink],
) -> bool:
    if round_label is not None:
        return False
    if agenda:
        return False
    if minutes_links or announcement_links:
        return False
    return bool(materials_links) and all(is_roster_link_title(link.title) for link in materials_links)


def _detect_document_kind(
    *,
    round_label: int | None,
    agenda: list[str],
    agenda_text: str | None,
    minutes_links: list[MeetingLink],
    announcement_links: list[MeetingLink],
    materials_links: list[MeetingLink],
) -> tuple[str, str] | None:
    if round_label is not None:
        return None
    if any("答申" in item for item in agenda):
        return ("toshin", "答申")
    if any("答申" in link.title for link in materials_links):
        return ("toshin", "答申")
    compact_agenda_text = (agenda_text or "").replace(" ", "").replace("\u3000", "")
    if "意見書" in compact_agenda_text:
        return ("ikensho", "意見書")
    if any("意見書" in link.title for link in materials_links):
        return ("ikensho", "意見書")
    if materials_links and not minutes_links and not announcement_links:
        if all(is_roster_link_title(link.title) for link in materials_links):
            return None
        return ("material", "資料")
    if agenda and materials_links and not minutes_links and not announcement_links:
        return ("material", "資料")
    return None


def _build_document_id(*, held_on: str, document_type: str) -> str:
    return f"{held_on}-{document_type}"


def _build_meeting_id(*, held_on: str, round_label: int | None) -> str:
    if round_label is None:
        return f"{held_on}-no-round"
    return f"{held_on}-{round_label:03d}"


def _dedupe_rosters(rosters: list[CouncilRoster]) -> list[CouncilRoster]:
    deduped: dict[str, CouncilRoster] = {}
    for roster in rosters:
        deduped[roster.id] = roster
    return [deduped[key] for key in sorted(deduped.keys())]


def _merge_parse_results(
    left: CouncilPageParseResult,
    right: CouncilPageParseResult,
) -> CouncilPageParseResult:
    meeting_map = {meeting.id: meeting for meeting in left.meetings}
    meeting_map.update({meeting.id: meeting for meeting in right.meetings})
    document_map = {document.id: document for document in left.documents}
    document_map.update({document.id: document for document in right.documents})
    roster_map = {roster.id: roster for roster in left.rosters}
    roster_map.update({roster.id: roster for roster in right.rosters})
    return CouncilPageParseResult(
        meetings=sorted(meeting_map.values(), key=lambda meeting: (meeting.held_on, meeting.round_label or -1)),
        documents=sorted(document_map.values(), key=lambda document: document.published_on),
        rosters=sorted(roster_map.values(), key=lambda roster: roster.as_of),
    )


def _load_existing_council_data(*, council_id: str, output_dir: Path) -> ExistingCouncilData:
    return ExistingCouncilData(
        meetings={meeting.id: meeting for meeting in load_meetings(council_id, base_dir=output_dir)},
        documents={document.id: document for document in load_documents(council_id, base_dir=output_dir)},
        rosters={roster.id: roster for roster in load_rosters(council_id, base_dir=output_dir)},
    )


def _reuse_existing_outputs(
    result: CouncilPageParseResult,
    *,
    existing_data: ExistingCouncilData,
) -> tuple[CouncilPageParseResult, set[str]]:
    meetings: list[Meeting] = []
    documents: list[CouncilDocument] = []
    rosters: list[CouncilRoster] = []
    meeting_ids_to_enrich: set[str] = set()

    for meeting in result.meetings:
        existing = existing_data.meetings.get(meeting.id)
        if existing is not None and _can_reuse_existing_meeting(parsed=meeting, existing=existing):
            meetings.append(existing.model_copy(deep=True))
            continue
        meetings.append(meeting)
        meeting_ids_to_enrich.add(meeting.id)

    for document in result.documents:
        existing = existing_data.documents.get(document.id)
        if existing is not None and _document_signature(document) == _document_signature(existing):
            documents.append(existing.model_copy(deep=True))
            continue
        documents.append(document)

    for roster in result.rosters:
        existing = existing_data.rosters.get(roster.id)
        if existing is not None and _roster_signature(roster) == _roster_signature(existing):
            rosters.append(existing.model_copy(deep=True))
            continue
        rosters.append(roster)

    return (
        CouncilPageParseResult(meetings=meetings, documents=documents, rosters=rosters),
        meeting_ids_to_enrich,
    )


def _can_reuse_existing_meeting(*, parsed: Meeting, existing: Meeting) -> bool:
    if _meeting_link_signature(parsed) != _meeting_link_signature(existing):
        return False
    if parsed.round_label != existing.round_label or parsed.held_on != existing.held_on:
        return False
    if parsed.agenda == existing.agenda:
        return True
    if not parsed.agenda and existing.agenda:
        return True
    return bool(parsed.agenda) and _is_subsequence(parsed.agenda, existing.agenda)


def _meeting_link_signature(meeting: Meeting) -> tuple[object, ...]:
    return (
        meeting.id,
        meeting.source_url,
        tuple((link.title, link.url) for link in meeting.minutes_links),
        tuple((link.title, link.url) for link in meeting.materials_links),
        tuple((link.title, link.url) for link in meeting.announcement_links),
    )


def _document_signature(document: CouncilDocument) -> tuple[object, ...]:
    return (
        document.id,
        document.title,
        document.published_on,
        document.document_type,
        document.source_url,
        tuple((link.title, link.url) for link in document.links),
    )


def _roster_signature(roster: CouncilRoster) -> tuple[object, ...]:
    return (
        roster.id,
        roster.as_of,
        roster.source_url,
        tuple((link.title, link.url) for link in roster.links),
    )


def _is_subsequence(candidate: list[str], existing: list[str]) -> bool:
    if not candidate:
        return True
    if len(candidate) > len(existing):
        return False
    index = 0
    for item in existing:
        if item != candidate[index]:
            continue
        index += 1
        if index == len(candidate):
            return True
    return False


def _enrich_parse_result_from_detail_pages(
    result: CouncilPageParseResult,
    *,
    load_html,
    target_meeting_ids: set[str] | None = None,
) -> None:
    """詳細ページを読んで議題と名簿を補完する。"""

    rosters = {roster.id: roster for roster in result.rosters}

    for meeting in result.meetings:
        if target_meeting_ids is not None and meeting.id not in target_meeting_ids:
            continue
        detail_pages: dict[str, str] = {}

        for link in [*meeting.announcement_links, *meeting.materials_links]:
            if not link.url.endswith(".html"):
                continue
            detail_html = load_html(link.url)
            if detail_html is None:
                continue
            detail_pages[link.url] = detail_html

            if "資料" not in link.title:
                continue
            detail_roster_links = extract_roster_links_from_material_page(detail_html, link.url)
            if not detail_roster_links:
                continue
            rosters[meeting.held_on] = CouncilRoster(
                id=meeting.held_on,
                council_id=meeting.council_id,
                as_of=meeting.held_on,
                source_url=detail_roster_links[0].url,
                links=detail_roster_links,
            )

        if not meeting.agenda and meeting.source_url.endswith(".html") and meeting.source_url not in detail_pages:
            detail_html = load_html(meeting.source_url)
            if detail_html is not None:
                detail_pages[meeting.source_url] = detail_html

        for detail_html in detail_pages.values():
            agenda = extract_agenda_from_detail_page(detail_html)
            if not agenda:
                continue
            if not meeting.agenda or len(agenda) > len(meeting.agenda):
                meeting.agenda = agenda
                break

    result.rosters = [rosters[key] for key in sorted(rosters.keys())]


def _normalize_agenda_for_council(result: CouncilPageParseResult, *, rule: MhlwCouncilRule | None) -> None:
    """会議体ごとの議題正規化と文書再分類を適用する。"""

    if rule is None or rule.agenda_normalizer is None:
        return

    for meeting in result.meetings:
        if rule.agenda_normalizer == "anonymous_medical":
            meeting.agenda = _normalize_anonymous_medical_committee_agenda(meeting.agenda)
            continue
        if rule.agenda_normalizer == "medical_insurance":
            meeting.agenda = _normalize_medical_insurance_subcommittee_agenda(meeting.agenda)
    if rule.agenda_normalizer == "medical_insurance":
        _reclassify_medical_insurance_subcommittee_no_round_items(result)


def _normalize_anonymous_medical_committee_agenda(agenda: list[str]) -> list[str]:
    normalized_items: list[str] = []
    for item in agenda:
        normalized_items.extend(_split_anonymous_medical_committee_agenda_item(item))

    deduped: list[str] = []
    for item in normalized_items:
        stripped = item.strip()
        if not stripped:
            continue
        deduped.append(stripped)
    return deduped


def _split_anonymous_medical_committee_agenda_item(item: str) -> list[str]:
    normalized = item.replace("(非公開)", "（非公開）").replace("⒈", "1. ").replace("⒉", "2. ").replace("⒊", "3. ")
    normalized = normalized.replace("⒋", "4. ").replace("⒌", "5. ").replace("⒍", "6. ")
    normalized = re.sub(r"(?<!^)(?=(?:[0-9０-９]+[\.．、)]\s*))", "\n", normalized)
    normalized = re.sub(r"(?<=について)(?=(?!（)[^\s])", "\n", normalized)
    normalized = re.sub(r"(?<=（非公開）)(?=(?!\s*$)[^\s])", "\n", normalized)

    parts = [part.strip() for part in normalized.split("\n") if part.strip()]
    cleaned: list[str] = []
    for part in parts:
        cleaned_part = re.sub(r"^[0-9０-９]+[\.．、)]\s*", "", part).strip()
        if cleaned_part:
            cleaned.append(cleaned_part)
    return cleaned


def _normalize_medical_insurance_subcommittee_agenda(agenda: list[str]) -> list[str]:
    normalized_items: list[str] = []
    for item in agenda:
        normalized_items.extend(_split_medical_insurance_subcommittee_agenda_item(item))

    cleaned: list[str] = []
    for item in normalized_items:
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


def _split_medical_insurance_subcommittee_agenda_item(item: str) -> list[str]:
    normalized = item.replace("(報告)", "（報告）").replace("(報告事項)", "（報告事項）").replace("(案)", "（案）")
    normalized = re.sub(r"(?<!^)(?=(?:[0-9０-９]+[\.．、)]\s*))", "\n", normalized)
    normalized = re.sub(r"(について（[^）]+）)(?=[^\s])", r"\1\n", normalized)
    normalized = re.sub(r"(?<=について)(?=(?!（)[^\s])", "\n", normalized)
    normalized = re.sub(r"(（報告事項）)(?=[^\s])", r"\1\n", normalized)
    normalized = re.sub(r"(（報告）)(?=[^\s])", r"\1\n", normalized)
    normalized = re.sub(r"(（案）)(?=[^\s])", r"\1\n", normalized)

    parts = [part.strip() for part in normalized.split("\n") if part.strip()]
    cleaned: list[str] = []
    for part in parts:
        cleaned_part = re.sub(r"^[0-9０-９]+[\.．、)]\s*", "", part).strip()
        if cleaned_part:
            cleaned.append(cleaned_part)
    return cleaned


def _reclassify_medical_insurance_subcommittee_no_round_items(result: CouncilPageParseResult) -> None:
    meetings: list[Meeting] = []
    documents = {document.id: document for document in result.documents}

    for meeting in result.meetings:
        if meeting.round_label is not None:
            meetings.append(meeting)
            continue

        title = _medical_insurance_no_round_title(meeting)
        document_type = _medical_insurance_no_round_document_type(meeting, title=title)
        documents[f"{meeting.held_on}-{document_type}"] = CouncilDocument(
            id=f"{meeting.held_on}-{document_type}",
            council_id=meeting.council_id,
            title=title,
            published_on=meeting.held_on,
            document_type=document_type,
            source_url=meeting.source_url,
            links=[*meeting.announcement_links, *meeting.materials_links],
            body=DocumentBody(status="not_built"),
        )

    result.meetings = meetings
    result.documents = sorted(documents.values(), key=lambda document: document.published_on)


def _medical_insurance_no_round_title(meeting: Meeting) -> str:
    if meeting.agenda:
        return "".join(meeting.agenda)
    for links in (meeting.announcement_links, meeting.materials_links):
        for link in links:
            if link.title in {"資料", "資料等", "基本方針", "開催案内"}:
                continue
            return link.title
    if meeting.materials_links:
        return meeting.materials_links[0].title
    if meeting.announcement_links:
        return meeting.announcement_links[0].title
    return f"{meeting.held_on} 医療保険部会"


def _medical_insurance_no_round_document_type(meeting: Meeting, *, title: str) -> str:
    if any("開催中止" in link.title for link in meeting.announcement_links):
        return "開催中止"
    if any("基本方針" in link.title for link in meeting.materials_links):
        return "基本方針"
    if "議論の整理" in title:
        return "議論の整理"
    return "資料"


def _build_care_benefit_internal_committee_council(council_id: str) -> Council:
    parent_council = load_council(CARE_BENEFIT_SUBCOMMITTEE_ID)
    title = next(title for title, child_id in CARE_BENEFIT_INTERNAL_COMMITTEES.items() if child_id == council_id)
    return Council(
        council_id=council_id,
        title=title,
        parent=parent_council.council_id,
        source_urls=parent_council.source_urls,
    )


def _split_care_benefit_internal_committee_data(
    *,
    council: Council,
    result: CouncilPageParseResult,
    output_dir: Path,
) -> tuple[CouncilPageParseResult, list[Council], dict[str, CouncilPageParseResult], list[Path]]:
    """介護給付費分科会配下の内部委員会データを親から分離する。"""

    child_councils = [
        _build_care_benefit_internal_committee_council(child_id)
        for child_id in CARE_BENEFIT_INTERNAL_COMMITTEES.values()
    ]
    child_meetings: dict[str, list[Meeting]] = {child.council_id: [] for child in child_councils}
    child_rosters: dict[str, list[CouncilRoster]] = {child.council_id: [] for child in child_councils}
    meeting_child_ids_by_date: dict[str, str] = {}
    parent_meetings: list[Meeting] = []
    stale_paths: list[Path] = []

    for meeting in result.meetings:
        child_council_id = _detect_care_benefit_internal_committee_meeting(meeting)
        if child_council_id is None:
            parent_meetings.append(meeting)
            continue

        child_meetings[child_council_id].append(
            meeting.model_copy(
                update={
                    "council_id": child_council_id,
                    "agenda": _normalize_care_benefit_internal_committee_agenda(
                        meeting.agenda,
                        child_council_id=child_council_id,
                    ),
                }
            )
        )
        meeting_child_ids_by_date[meeting.held_on] = child_council_id
        stale_paths.append(meetings_dir(council.council_id, base_dir=output_dir) / f"{meeting.id}.json")

    parent_rosters: list[CouncilRoster] = []
    for roster in result.rosters:
        child_council_id = _detect_care_benefit_internal_committee_roster(roster)
        if child_council_id is None:
            child_council_id = meeting_child_ids_by_date.get(roster.as_of)

        if child_council_id is None:
            parent_rosters.append(roster)
            continue

        child_rosters[child_council_id].append(
            roster.model_copy(
                update={
                    "council_id": child_council_id,
                }
            )
        )
        stale_paths.append(rosters_dir(council.council_id, base_dir=output_dir) / f"{roster.id}.json")

    filtered_child_councils = [
        child_council
        for child_council in child_councils
        if child_meetings[child_council.council_id] or child_rosters[child_council.council_id]
    ]
    child_results = {
        child_council.council_id: CouncilPageParseResult(
            meetings=child_meetings[child_council.council_id],
            documents=[],
            rosters=child_rosters[child_council.council_id],
        )
        for child_council in filtered_child_councils
    }
    parent_result = CouncilPageParseResult(
        meetings=parent_meetings,
        documents=result.documents,
        rosters=parent_rosters,
    )
    return parent_result, filtered_child_councils, child_results, stale_paths


def _detect_care_benefit_internal_committee_meeting(meeting: Meeting) -> str | None:
    matched_child_ids = {
        child_council_id
        for item in meeting.agenda
        for child_council_id in [_match_care_benefit_internal_committee_text(item)]
        if child_council_id is not None
    }
    if len(matched_child_ids) != 1:
        return None
    return next(iter(matched_child_ids))


def _detect_care_benefit_internal_committee_roster(roster: CouncilRoster) -> str | None:
    for link in roster.links:
        for title, council_id in CARE_BENEFIT_INTERNAL_COMMITTEES.items():
            if title in link.title:
                return council_id
    return None


def _match_care_benefit_internal_committee_text(text: str) -> str | None:
    normalized = _normalize_care_benefit_internal_committee_text(text)
    if not normalized:
        return None
    for title, council_id in CARE_BENEFIT_INTERNAL_COMMITTEES.items():
        for alias in _care_benefit_internal_committee_aliases(title):
            if alias in normalized:
                return council_id
    return None


def _normalize_care_benefit_internal_committee_agenda(
    agenda: list[str],
    *,
    child_council_id: str,
) -> list[str]:
    title = next(title for title, council_id in CARE_BENEFIT_INTERNAL_COMMITTEES.items() if council_id == child_council_id)
    cleaned_items: list[str] = []
    aliases = _care_benefit_internal_committee_aliases(title)
    for item in agenda:
        cleaned = _normalize_care_benefit_internal_committee_text(item)
        if not cleaned:
            continue
        if any(alias == cleaned for alias in aliases):
            continue
        if cleaned.endswith("名簿") and any(alias in cleaned for alias in aliases):
            continue
        cleaned = _strip_care_benefit_internal_committee_roster_prefix(cleaned, aliases=aliases)
        if not cleaned:
            continue
        cleaned_items.append(cleaned)
    return cleaned_items or agenda


def _normalize_care_benefit_internal_committee_text(text: str) -> str:
    normalized = re.sub(r"\[PDF:[^\]]+\]", "", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _care_benefit_internal_committee_aliases(title: str) -> tuple[str, ...]:
    aliases = [title]
    if title.endswith("委員会"):
        aliases.append(title.removesuffix("委員会") + "委員")
    return tuple(aliases)


def _strip_care_benefit_internal_committee_roster_prefix(text: str, *, aliases: tuple[str, ...]) -> str:
    for alias in aliases:
        text = re.sub(rf"^{re.escape(alias)}名簿", "", text).strip()
        text = re.sub(rf"^{re.escape(alias)}委員名簿", "", text).strip()
    return text
