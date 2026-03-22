from __future__ import annotations

import json
import logging
from pathlib import Path

from shingikai.models.council import Council
from shingikai.models.document import CouncilDocument
from shingikai.models.meeting import Meeting
from shingikai.models.roster import CouncilRoster


logger = logging.getLogger(__name__)


def load_council(council_id: str) -> Council:
    path = council_json_path(council_id)
    if not path.exists():
        raise FileNotFoundError(f"council data not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"council data must be a JSON object: {path}")

    return Council.from_dict(payload)


def load_meetings(council_id: str, base_dir: Path | None = None) -> list[Meeting]:
    return _load_model_files(meetings_dir(council_id, base_dir=base_dir), Meeting)


def load_documents(council_id: str, base_dir: Path | None = None) -> list[CouncilDocument]:
    return _load_model_files(documents_dir(council_id, base_dir=base_dir), CouncilDocument)


def load_rosters(council_id: str, base_dir: Path | None = None) -> list[CouncilRoster]:
    return _load_model_files(rosters_dir(council_id, base_dir=base_dir), CouncilRoster)


def write_council(council: Council, base_dir: Path | None = None) -> Path:
    path = council_json_path(council.council_id, base_dir=base_dir)
    write_json(path, council.model_dump(mode="json", by_alias=True))
    return path


def write_meetings(council_id: str, meetings: list[Meeting], base_dir: Path | None = None) -> list[Path]:
    return _write_model_files(meetings_dir(council_id, base_dir=base_dir), meetings)


def write_documents(
    council_id: str,
    documents: list[CouncilDocument],
    base_dir: Path | None = None,
) -> list[Path]:
    return _write_model_files(documents_dir(council_id, base_dir=base_dir), documents)


def write_rosters(council_id: str, rosters: list[CouncilRoster], base_dir: Path | None = None) -> list[Path]:
    return _write_model_files(rosters_dir(council_id, base_dir=base_dir), rosters)


def council_json_path(council_id: str, base_dir: Path | None = None) -> Path:
    root = base_dir or Path("data")
    return root / "councils" / council_id / "council.json"


def meetings_dir(council_id: str, base_dir: Path | None = None) -> Path:
    root = base_dir or Path("data")
    return root / "councils" / council_id / "meetings"


def documents_dir(council_id: str, base_dir: Path | None = None) -> Path:
    root = base_dir or Path("data")
    return root / "councils" / council_id / "documents"


def rosters_dir(council_id: str, base_dir: Path | None = None) -> Path:
    root = base_dir or Path("data")
    return root / "councils" / council_id / "rosters"


def remove_files(paths: list[Path]) -> None:
    for path in paths:
        if path.exists():
            path.unlink()


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    logger.debug("write json: %s", path)


def _write_model_files(directory: Path, items: list[object]) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for item in items:
        item_id = getattr(item, "id")
        path = directory / f"{item_id}.json"
        write_json(path, item.model_dump(mode="json"))
        paths.append(path)
    _remove_stale_json_files(directory, keep_paths=paths)
    return paths


def _remove_stale_json_files(directory: Path, *, keep_paths: list[Path]) -> None:
    keep_names = {path.name for path in keep_paths}
    for path in directory.glob("*.json"):
        if path.name in keep_names:
            continue
        path.unlink()
        logger.debug("remove stale json: %s", path)


def _load_model_files(directory: Path, model_cls):
    if not directory.exists():
        return []
    items = []
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        items.append(model_cls.model_validate(payload))
    return items
