from __future__ import annotations

import re


DATE_PATTERN = re.compile(r"(?P<year>\d{4})年(?P<month>\d{1,2})月(?P<day>\d{1,2})日")


def normalize_dash(text: str) -> str | None:
    stripped = text.strip()
    if stripped in {"－", "-"}:
        return None
    return stripped or None


def parse_round_label(text: str | None) -> int | None:
    round_labels = parse_round_labels(text)
    if not round_labels:
        return None
    return round_labels[0]


def parse_round_labels(text: str | None) -> list[int]:
    if text is None:
        return []
    digits = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    values = [int(value) for value in re.findall(r"\d+", digits)]
    deduped: list[int] = []
    for value in values:
        if value not in deduped:
            deduped.append(value)
    return deduped


def parse_held_on_text(text: str) -> str:
    parts = [part.strip() for part in text.split("\n") if part.strip()]
    if not parts:
        raise ValueError("held_on cell is empty")

    western = parts[0]
    match = DATE_PATTERN.search(western)
    if match is None:
        raise ValueError(f"held_on is not a supported format: {western}")

    return (
        f"{int(match.group('year')):04d}-{int(match.group('month')):02d}-{int(match.group('day')):02d}"
    )


def parse_agenda_text(text: str | None) -> list[str]:
    if text is None:
        return []

    raw_text = text.replace("\u3000", " ")
    raw_lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    normalized = (
        text.translate(str.maketrans("１２３４５６７８９０", "1234567890"))
        .replace("\u3000", " ")
    )
    normalized = re.sub(r"\d+\s+[\.\．、)\)]", lambda m: m.group(0).replace(" ", ""), normalized)
    lines = [line.strip() for line in normalized.split("\n") if line.strip()]

    items: list[str] = []
    current = ""
    for raw_line in lines:
        for line in _split_embedded_agenda_markers(raw_line):
            if _is_agenda_marker_only(line):
                if current:
                    items.append(current.strip())
                current = ""
                continue
            if _starts_agenda_item(line):
                if current:
                    items.append(current.strip())
                current = _strip_agenda_prefix(line)
                continue
            if current:
                current = f"{current}{line}"
            else:
                current = line

    if current:
        items.append(current.strip())

    if not items:
        return []
    if len(items) == 1 and len(raw_lines) >= 2:
        return raw_lines
    if len(items) == 1 and items[0] == normalized.strip():
        return [items[0]] if "答申" in items[0] else []
    return items


def _split_embedded_agenda_markers(line: str) -> list[str]:
    return [
        segment.strip()
        for segment in re.split(
            r"(?<!^)(?:(?<=\s)(?=(?:\(\d+\)|（\d+）|\d+[\.\．、)]))|(?<![-A-Za-zＡ-Ｚａ-ｚ0-9０-９])(?=\d+\s+\S))",
            line,
        )
        if segment.strip()
    ]


def is_roster_link_title(title: str) -> bool:
    normalized = title.replace(" ", "").replace("\u3000", "")
    return "委員名簿" in normalized


def _starts_agenda_item(line: str) -> bool:
    return bool(re.match(r"^(?:\(\d+\)|（\d+）|\d+(?:[\.\．、)\)]\s*|\s+))", line))


def _strip_agenda_prefix(line: str) -> str:
    return re.sub(r"^(?:\(\d+\)|（\d+）|\d+(?:[\.\．、)\)]\s*|\s+))", "", line).strip()


def _is_agenda_marker_only(line: str) -> bool:
    return bool(re.fullmatch(r"(?:\(\d+\)|（\d+）|\d+(?:[\.\．、)\)]|\s*))", line))
