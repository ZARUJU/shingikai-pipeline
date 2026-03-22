from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from pydantic import BaseModel

from shingikai.fetch_errors import clear_fetch_error, has_recorded_404, record_fetch_error
from shingikai.models.council import Council, SourceUrls
from shingikai.models.document import CouncilDocument
from shingikai.models.meeting import Meeting, MeetingLink
from shingikai.models.roster import CouncilRoster
from shingikai.utils.cache import cached_html_path, is_cache_fresh
from shingikai.utils.fetch import USER_AGENT, fetch_html, resolve_html_fetch_url
from shingikai.utils.html import extract_agenda_from_detail_page
from shingikai.utils.io import load_council

logger = logging.getLogger(__name__)

MOFA_COUNCIL_ID = "mofa"
MOFA_JINJI_COUNCIL_ID = "mofa-jinji-council"
MOFA_SUPPORTED_HIERARCHY_ROOT_IDS = [MOFA_COUNCIL_ID]
MOFA_INDEX_SOURCE_URL = "https://www.mofa.go.jp/mofaj/annai/shingikai/index.html"
MOFA_JINJI_PORTAL_URL = "https://www.mofa.go.jp/mofaj/annai/shingikai/jinji/index.html"
MOFA_JINJI_MEETINGS_URL = "https://www.mofa.go.jp/mofaj/annai/shingikai/jinji/kaigogaiyo/index.html"
MOFA_JINJI_WARP_ARCHIVE_URL = (
    "https://warp.ndl.go.jp/20250207/20250202091155/"
    "https://www.mofa.go.jp/mofaj/annai/shingikai/jinji/kaigogaiyo/index.html"
)
MOFA_JINJI_TITLE = "外務人事審議会"

_MOFA_REIWA_YEAR_BLOCK_PATTERN = re.compile(r"^令和([0-9０-９元]+)年$")
_MOFA_HEISEI_YEAR_BLOCK_PATTERN = re.compile(r"^平成([0-9０-９元]+)年(?:（令和元年）)?$")
_MOFA_ROUND_PATTERN = re.compile(r"^第([0-9０-９]+)回")
_MOFA_HELD_ON_PATTERN = re.compile(r"（([0-9０-９]+)月([0-9０-９]+)日）")
_MOFA_WARP_REPLAY_PATTERN = re.compile(
    r"^(https://warp\.ndl\.go\.jp/(?P<collection>\d+)/(?P<timestamp>\d{14})(?P<modifier>[a-z_]*)/)(?P<target>.+)$"
)
_MOFA_ACCESS_DENIED_PATTERN = re.compile(r"<title>\s*Access Denied\s*</title>", re.IGNORECASE)


class CouncilPageParseResult(BaseModel):
    meetings: list[Meeting]
    documents: list[CouncilDocument]
    rosters: list[CouncilRoster]


@dataclass
class MofaExportPlan:
    result: CouncilPageParseResult
    related_councils: list[Council] = field(default_factory=list)
    related_results: dict[str, CouncilPageParseResult] = field(default_factory=dict)
    stale_paths: list[Path] = field(default_factory=list)


def fixture_html_path(url: str) -> Path:
    return cached_html_path(url)


def fetch_mofa_html(url: str, timeout: int = 30) -> str:
    try:
        html = fetch_html(url, timeout=timeout)
        _raise_if_access_denied_html(url=url, html=html)
        return html
    except HTTPError as exc:
        if exc.code != 403:
            raise
        logger.info("urllib fetch got 403; retry with curl: %s", url)
        html = _fetch_mofa_html_via_curl(url, timeout=timeout)
        _raise_if_access_denied_html(url=url, html=html)
        return html


def load_mofa_council(council_id: str) -> Council:
    if council_id == MOFA_COUNCIL_ID:
        return Council(
            council_id=MOFA_COUNCIL_ID,
            title="外務省",
            parent="省庁",
            source_urls=SourceUrls(
                portal=MOFA_INDEX_SOURCE_URL,
                meetings=MOFA_INDEX_SOURCE_URL,
            ),
        )
    if council_id == MOFA_JINJI_COUNCIL_ID:
        return Council(
            council_id=MOFA_JINJI_COUNCIL_ID,
            title=MOFA_JINJI_TITLE,
            parent=MOFA_COUNCIL_ID,
            source_urls=SourceUrls(
                portal=MOFA_JINJI_PORTAL_URL,
                meetings=MOFA_JINJI_MEETINGS_URL,
                meetings_archives=[MOFA_JINJI_WARP_ARCHIVE_URL],
            ),
        )
    return load_council(council_id)


def parse_mofa_hierarchy(
    *,
    council_id: str,
    use_fixture: bool,
    force: bool,
    max_cache_age_hours: int | None = None,
) -> list[Council]:
    if council_id != MOFA_COUNCIL_ID:
        raise ValueError(f"hierarchy export is not supported for council: {council_id}")

    html = _load_mofa_html(
        url=MOFA_INDEX_SOURCE_URL,
        use_fixture=use_fixture,
        force=force,
        max_cache_age_hours=max_cache_age_hours,
    )
    assert html is not None
    return parse_hierarchy_page(html, page_url=MOFA_INDEX_SOURCE_URL)


def parse_hierarchy_page(html: str, *, page_url: str) -> list[Council]:
    soup = BeautifulSoup(html, "html.parser")
    links = {urljoin(page_url, anchor["href"]): anchor.get_text(strip=True) for anchor in soup.select("a[href]")}
    if MOFA_JINJI_PORTAL_URL not in links:
        raise ValueError("mofa jinji council entry not found")

    return [
        load_mofa_council(MOFA_COUNCIL_ID),
        load_mofa_council(MOFA_JINJI_COUNCIL_ID),
    ]


def build_mofa_export_plan(
    *,
    council: Council,
    use_fixture: bool,
    force: bool,
    output_dir: Path,
    max_cache_age_hours: int | None = None,
    reuse_existing_outputs: bool = False,
) -> MofaExportPlan:
    del output_dir, reuse_existing_outputs

    if council.council_id == MOFA_COUNCIL_ID:
        return MofaExportPlan(result=CouncilPageParseResult(meetings=[], documents=[], rosters=[]))

    if council.council_id != MOFA_JINJI_COUNCIL_ID:
        raise ValueError(f"unknown mofa council: {council.council_id}")

    html = _load_mofa_html(
        url=council.source_urls.meetings,
        use_fixture=use_fixture,
        force=force,
        max_cache_age_hours=max_cache_age_hours,
    )
    assert html is not None
    result = parse_meeting_page(
        html,
        council_id=council.council_id,
        source_url=council.source_urls.meetings,
    )
    for archive_url in council.source_urls.meetings_archives:
        archive_html = _load_mofa_html(
            url=archive_url,
            use_fixture=use_fixture,
            force=force,
            max_cache_age_hours=max_cache_age_hours,
        )
        if archive_html is None:
            continue
        archive_result = parse_meeting_page(
            archive_html,
            council_id=council.council_id,
            source_url=archive_url,
        )
        result = _merge_parse_results(result, archive_result)
    _enrich_meetings_from_detail_pages(
        result,
        load_html=lambda url: _load_mofa_html(
            url=url,
            use_fixture=use_fixture,
            force=force,
            required=False,
            max_cache_age_hours=max_cache_age_hours,
        ),
    )
    return MofaExportPlan(result=result)


def parse_meeting_page(
    html: str,
    *,
    council_id: str,
    source_url: str,
) -> CouncilPageParseResult:
    soup = BeautifulSoup(html, "html.parser")
    meetings: list[Meeting] = []
    current_year: int | None = None

    for node in soup.find_all(["h1", "h2", "a"]):
        if node.name == "h2":
            text = node.get_text(strip=True)
            parsed_year = _parse_japanese_era_year_heading(text)
            if parsed_year is not None:
                current_year = parsed_year
            continue
        if node.name != "a" or current_year is None:
            continue

        href = node.get("href")
        if href is None:
            continue
        title = node.get_text(strip=True)
        if "外務人事審議会" in title or "WARP" in title:
            continue
        if "回" not in title and "臨時会議" not in title:
            continue

        held_on = _parse_held_on(title=title, year=current_year)
        if held_on is None:
            continue
        round_label = _parse_round_label(title)
        detail_url = _resolve_meeting_link_url(source_url=source_url, href=href)
        meetings.append(
            Meeting(
                id=_build_meeting_id(held_on=held_on, round_label=round_label, title=title),
                council_id=council_id,
                round_label=round_label,
                held_on=held_on,
                agenda=[],
                source_url=detail_url,
                minutes_links=[MeetingLink(title=title, url=detail_url)],
                materials_links=[],
                announcement_links=[],
            )
        )

    meetings.sort(key=lambda item: (item.held_on, item.round_label or -1))
    return CouncilPageParseResult(meetings=meetings, documents=[], rosters=[])


def _merge_parse_results(
    left: CouncilPageParseResult,
    right: CouncilPageParseResult,
) -> CouncilPageParseResult:
    merged_meetings: dict[str, Meeting] = {meeting.id: meeting for meeting in left.meetings}
    for meeting in right.meetings:
        existing = merged_meetings.get(meeting.id)
        if existing is None:
            merged_meetings[meeting.id] = meeting
            continue
        if meeting.agenda and not existing.agenda:
            existing.agenda = meeting.agenda
        if not existing.minutes_links and meeting.minutes_links:
            existing.minutes_links = meeting.minutes_links
        if _is_warp_replay_url(existing.source_url) and not _is_warp_replay_url(meeting.source_url):
            existing.source_url = meeting.source_url
            existing.minutes_links = meeting.minutes_links or existing.minutes_links
    meetings = sorted(merged_meetings.values(), key=lambda item: (item.held_on, item.round_label or -1))
    return CouncilPageParseResult(meetings=meetings, documents=[], rosters=[])


def _enrich_meetings_from_detail_pages(result: CouncilPageParseResult, *, load_html) -> None:
    for meeting in result.meetings:
        if not meeting.source_url.endswith(".html"):
            continue
        detail_html = load_html(meeting.source_url)
        if detail_html is None:
            continue
        agenda = extract_agenda_from_detail_page(detail_html)
        if agenda:
            meeting.agenda = agenda


def _load_mofa_html(
    *,
    url: str,
    use_fixture: bool,
    force: bool,
    required: bool = True,
    max_cache_age_hours: int | None = None,
) -> str | None:
    path = fixture_html_path(url)
    if use_fixture:
        if path.exists():
            html = path.read_text(encoding="utf-8")
            if not _is_access_denied_html(html):
                return html
            if required:
                raise ValueError(f"fixture html is access denied: {path}")
            return None
        if required:
            raise ValueError(f"fixture html not found: {path}")
        return None
    if not force and path.exists() and max_cache_age_hours is None:
        html = path.read_text(encoding="utf-8")
        if not _is_access_denied_html(html):
            return html
    if not force and path.exists() and max_cache_age_hours is not None and is_cache_fresh(path, max_age_hours=max_cache_age_hours):
        html = path.read_text(encoding="utf-8")
        if not _is_access_denied_html(html):
            return html
    if not force and has_recorded_404(url):
        if required:
            raise ValueError(f"recorded 404 for url: {url}")
        return None
    try:
        html = fetch_mofa_html(url)
        clear_fetch_error(url)
        return html
    except HTTPError as exc:
        if exc.code == 404:
            record_fetch_error(url, status_code=404, reason=str(exc.reason))
        if required:
            raise
        logger.warning("optional fetch failed: %s (%s)", url, exc)
        return None
    except URLError as exc:
        if required:
            raise
        logger.warning("optional fetch failed: %s (%s)", url, exc)
        return None


def _fetch_mofa_html_via_curl(url: str, *, timeout: int) -> str:
    request_url = resolve_html_fetch_url(url)
    result = subprocess.run(
        [
            "curl",
            "-L",
            "--max-time",
            str(timeout),
            "-A",
            USER_AGENT,
            request_url,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    html = result.stdout
    cache_path = cached_html_path(url)
    cache_path.write_text(html, encoding="utf-8")
    logger.info("fetch done via curl: %s -> %s", url, cache_path)
    return html


def _is_access_denied_html(html: str) -> bool:
    return _MOFA_ACCESS_DENIED_PATTERN.search(html) is not None and "You don't have permission to access" in html


def _raise_if_access_denied_html(*, url: str, html: str) -> None:
    if not _is_access_denied_html(html):
        return
    cache_path = cached_html_path(url)
    if cache_path.exists():
        cache_path.unlink()
    raise HTTPError(url=url, code=403, msg="Access Denied", hdrs=None, fp=None)


def _parse_japanese_era_year_heading(text: str) -> int | None:
    normalized_text = _normalize_digits(text)
    reiwa_match = _MOFA_REIWA_YEAR_BLOCK_PATTERN.fullmatch(normalized_text)
    if reiwa_match is not None:
        return 2018 + _parse_japanese_year_number(reiwa_match.group(1))
    heisei_match = _MOFA_HEISEI_YEAR_BLOCK_PATTERN.fullmatch(normalized_text)
    if heisei_match is not None:
        return 1988 + _parse_japanese_year_number(heisei_match.group(1))
    return None


def _parse_japanese_year_number(text: str) -> int:
    if text == "元":
        return 1
    return int(text)


def _parse_round_label(title: str) -> int | None:
    match = _MOFA_ROUND_PATTERN.match(_normalize_digits(title))
    if match is None:
        return None
    return int(match.group(1))


def _parse_held_on(*, title: str, year: int) -> str | None:
    match = _MOFA_HELD_ON_PATTERN.search(_normalize_digits(title))
    if match is None:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _build_meeting_id(*, held_on: str, round_label: int | None, title: str) -> str:
    if round_label is not None:
        return f"{held_on}-{round_label:03d}"
    if "臨時会議" in title:
        return f"{held_on}-special"
    suffix = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not suffix:
        suffix = "no-round"
    return f"{held_on}-{suffix}"


def _resolve_meeting_link_url(*, source_url: str, href: str) -> str:
    match = _MOFA_WARP_REPLAY_PATTERN.match(source_url)
    if match is None:
        return urljoin(source_url, href)

    target_url = urljoin(match.group("target"), href)
    return f"{match.group(1)}{target_url}"


def _is_warp_replay_url(url: str) -> bool:
    return _MOFA_WARP_REPLAY_PATTERN.match(url) is not None


def _normalize_digits(text: str) -> str:
    return text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
