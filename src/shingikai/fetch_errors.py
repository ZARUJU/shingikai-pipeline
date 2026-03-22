from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path


DEFAULT_FETCH_ERROR_PATH = Path("data/_quality/fetch_errors.json")


def load_fetch_errors(path: Path | None = None) -> dict[str, dict[str, object]]:
    target = path or DEFAULT_FETCH_ERROR_PATH
    if not target.exists():
        return {}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return {str(key): value for key, value in payload.items() if isinstance(value, dict)}


def has_recorded_404(url: str, *, path: Path | None = None) -> bool:
    payload = load_fetch_errors(path=path)
    entry = payload.get(url)
    if entry is None:
        return False
    return int(entry.get("status_code", 0)) == 404


def record_fetch_error(
    url: str,
    *,
    status_code: int,
    reason: str,
    path: Path | None = None,
) -> None:
    target = path or DEFAULT_FETCH_ERROR_PATH
    payload = load_fetch_errors(path=target)
    now = datetime.now(timezone.utc).isoformat()
    previous = payload.get(url, {})
    payload[url] = {
        "status_code": status_code,
        "reason": reason,
        "first_recorded_at": previous.get("first_recorded_at", now),
        "last_recorded_at": now,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clear_fetch_error(url: str, *, path: Path | None = None) -> None:
    target = path or DEFAULT_FETCH_ERROR_PATH
    payload = load_fetch_errors(path=target)
    if url not in payload:
        return
    del payload[url]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
