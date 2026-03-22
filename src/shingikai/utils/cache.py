from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path


def cached_html_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = Path("fixtures") / "html" / f"{digest}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def is_cache_fresh(path: Path, *, max_age_hours: int) -> bool:
    if not path.exists():
        return False
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified_at < timedelta(hours=max_age_hours)
