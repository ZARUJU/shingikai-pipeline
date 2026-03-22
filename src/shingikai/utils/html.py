from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import NavigableString, Tag

from shingikai.models.meeting import MeetingLink
from shingikai.utils.normalize import parse_agenda_text


def cell_text(cell: Tag) -> str:
    text = cell.get_text("\n", strip=True)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_links(cell: Tag, *, source_url: str) -> list[MeetingLink]:
    links: list[MeetingLink] = []
    for anchor in cell.select("a[href]"):
        title = cell_text(anchor)
        href = anchor.get("href")
        if href is None:
            continue
        links.append(MeetingLink(title=title, url=urljoin(source_url, href)))
    return links


AGENDA_LABEL_PATTERN = re.compile(r"(?:議題(?:（案）)?|議事次第|会議次第|案件)")
AGENDA_STOP_PATTERN = re.compile(
    r"^(?:配[付布]資料|資料\d|資料[０-９一二三四五六七八九十]|参考資料|募集要領|照会先|宛先|記載事項|傍聴|YouTube|ユーチューブ|動画配信|ライブ配信|記者ブリーフィング)"
)
AGENDA_PLACEHOLDER_PATTERN = re.compile(r"(?:資料にてご確認願います|掲載場所|ホーム\s*>|ホーム\s*&gt;)")


def extract_agenda_from_detail_page(html: str) -> list[str]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "p", "div", "dt", "strong", "b"]):
        label = cell_text(node)
        if not _looks_like_agenda_label(label):
            continue

        for candidate in _iter_agenda_candidates(node):
            agenda = _parse_agenda_candidate(candidate)
            if agenda:
                return agenda

    return []


def _iter_agenda_candidates(node: Tag) -> list[str]:
    candidates: list[str] = []
    own_text = _strip_agenda_heading(cell_text(node))
    if own_text:
        candidates.append(own_text)

    if node.name in {"td", "th"}:
        sibling_cell = node.find_next_sibling(["td", "th"])
        if sibling_cell is not None:
            sibling_text = cell_text(sibling_cell)
            if sibling_text:
                candidates.append(sibling_text)

    inline_sibling_text = _collect_inline_sibling_text(node)
    if inline_sibling_text:
        candidates.append(inline_sibling_text)

    sibling = node.next_sibling
    while sibling is not None and len(candidates) < 4:
        if isinstance(sibling, NavigableString):
            sibling = sibling.next_sibling
            continue
        if not isinstance(sibling, Tag):
            sibling = sibling.next_sibling
            continue

        sibling_text = cell_text(sibling)
        if _looks_like_stop_label(sibling_text):
            break
        if sibling_text:
            candidates.append(sibling_text)
        sibling = sibling.next_sibling

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _collect_inline_sibling_text(node: Tag) -> str:
    fragments: list[str] = []
    sibling = node.next_sibling
    while sibling is not None:
        if isinstance(sibling, NavigableString):
            text = str(sibling).replace("\xa0", " ").strip()
            if text:
                fragments.append(text)
            sibling = sibling.next_sibling
            continue

        if not isinstance(sibling, Tag):
            sibling = sibling.next_sibling
            continue

        if sibling.name == "br":
            sibling = sibling.next_sibling
            continue

        sibling_text = cell_text(sibling)
        if _looks_like_stop_label(sibling_text):
            break
        break

    return "\n".join(fragments).strip()


def _parse_agenda_candidate(text: str) -> list[str]:
    cleaned = _strip_agenda_heading(text)
    if _looks_like_agenda_placeholder(cleaned):
        return []
    agenda = parse_agenda_text(cleaned)

    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]
    if len(lines) >= 2 and (not agenda or len(agenda) == 1):
        return lines
    if agenda:
        return agenda
    if len(lines) >= 2:
        return lines
    if len(lines) == 1 and not _looks_like_stop_label(lines[0]):
        return lines
    return []


def _looks_like_agenda_placeholder(text: str) -> bool:
    compact = text.replace("\n", " ").replace("\u3000", " ")
    return bool(AGENDA_PLACEHOLDER_PATTERN.search(compact))


def _looks_like_agenda_label(text: str) -> bool:
    first_line = text.split("\n", 1)[0].replace(" ", "").replace("\u3000", "").strip()
    if not first_line:
        return False
    first_line = re.sub(r"^[0-9０-９一二三四五六七八九十\(\)（）\.．、]+", "", first_line)
    return bool(AGENDA_LABEL_PATTERN.fullmatch(first_line))


def _looks_like_stop_label(text: str) -> bool:
    compact = text.replace("\n", "").replace(" ", "").replace("\u3000", "")
    if not compact:
        return False
    return bool(AGENDA_STOP_PATTERN.match(compact))


def _strip_agenda_heading(text: str) -> str:
    lines = [line.strip() for line in text.split("\n")]
    if not lines:
        return ""

    first = re.sub(r"^[0-9０-９一二三四五六七八九十]+[\.．、]?\s*", "", lines[0]).strip()
    first = re.sub(r"^(?:議\s*題(?:（案）)?|議\s*事\s*次\s*第|会\s*議\s*次\s*第|案\s*件)\s*", "", first).strip()
    lines[0] = first
    return "\n".join(line for line in lines if line.strip()).strip()
