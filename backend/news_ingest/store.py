from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_line(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


@dataclass(frozen=True)
class StoredBatch:
    count: int
    path: str


class FileNewsEventStore:
    """
    Append-only NDJSON store for raw news events.

    Layout:
      ${DATA_PLANE_ROOT:-data}/news/YYYY/MM/DD/events.ndjson

    Notes:
    - we do not attempt to normalize schemas; we store raw payloads + minimal metadata
    - this service is OBSERVE-only; the store is not consumed by any execution path
    """

    def __init__(self, *, data_root: Path) -> None:
        self.data_root = Path(data_root)

    def _events_path_for_today(self) -> Path:
        now = datetime.now(timezone.utc)
        return self.data_root / "news" / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}" / "events.ndjson"

    def append_events(self, *, source: str, events: Sequence[Mapping[str, Any]]) -> StoredBatch:
        if not events:
            p = self._events_path_for_today()
            return StoredBatch(count=0, path=str(p))

        p = self._events_path_for_today()
        p.parent.mkdir(parents=True, exist_ok=True)

        received_at = _utc_now_iso()
        lines = []
        for ev in events:
            payload = {
                "received_at_utc": received_at,
                "source": source,
                "raw": dict(ev),
            }
            lines.append(_json_line(payload))

        with p.open("a", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                f.write("\n")

        return StoredBatch(count=len(lines), path=str(p))


class FileCursorStore:
    """
    Minimal cursor persistence for polling loops.

    Stores a single JSON object like: {"cursor":"...","updated_at_utc":"..."}.
    """

    def __init__(self, *, cursor_path: Path) -> None:
        self.cursor_path = Path(cursor_path)

    def load(self) -> str | None:
        try:
            if not self.cursor_path.exists():
                return None
            raw = self.cursor_path.read_text(encoding="utf-8").strip()
            if not raw:
                return None
            obj = json.loads(raw)
            cur = obj.get("cursor")
            s = str(cur).strip() if cur is not None else ""
            return s or None
        except Exception:
            return None

    def save(self, cursor: str | None) -> None:
        if cursor is None or str(cursor).strip() == "":
            return
        self.cursor_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"cursor": str(cursor), "updated_at_utc": _utc_now_iso()}
        self.cursor_path.write_text(_json_line(payload) + "\n", encoding="utf-8")

