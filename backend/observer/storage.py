from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .models import ExplanationRecord, utcnow


def _env_flag(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


class ExplanationStorage:
    """
    In-memory store with optional JSONL persistence for observer explanations.

    - No Firestore
    - No DB writes
    - No automatic execution hooks (callers opt in by using this API)
    """

    def __init__(
        self,
        *,
        persist_to_disk: bool | None = None,
        base_dir: str | Path = "./tmp/observer_logs",
    ) -> None:
        self._lock = RLock()
        self._records: list[ExplanationRecord] = []
        self._by_id: dict[str, ExplanationRecord] = {}

        if persist_to_disk is None:
            # Default: off. Callers can enable via env var for local replay.
            persist_to_disk = _env_flag("OBSERVER_PERSIST_EXPLANATIONS", default=False)

        self.persist_to_disk = bool(persist_to_disk)
        self.base_dir = Path(base_dir)

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def add(self, record: ExplanationRecord) -> ExplanationRecord:
        """
        Add a record to memory and optionally persist it to disk.

        If a record with the same `record_id` already exists, it is ignored and
        the existing record is returned.
        """
        with self._lock:
            existing = self._by_id.get(record.record_id)
            if existing is not None:
                return existing

            self._records.append(record)
            self._by_id[record.record_id] = record

            if self.persist_to_disk:
                self._append_to_disk(record)

            return record

    def save(
        self,
        *,
        observer: str,
        input: Mapping[str, Any] | None = None,
        explanation: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
        record_id: str | None = None,
    ) -> ExplanationRecord:
        kwargs: dict[str, Any] = {
            "observer": str(observer or "").strip() or "unknown_observer",
            "input": dict(input) if isinstance(input, Mapping) else {},
            "explanation": dict(explanation) if isinstance(explanation, Mapping) else {},
            "metadata": dict(metadata) if isinstance(metadata, Mapping) else {},
            "created_at": created_at or utcnow(),
        }
        if record_id:
            kwargs["record_id"] = str(record_id)
        return self.add(ExplanationRecord(**kwargs))

    def list(self, *, observer: str | None = None) -> list[ExplanationRecord]:
        with self._lock:
            if observer is None:
                return list(self._records)
            obs = str(observer)
            return [r for r in self._records if r.observer == obs]

    def get(self, record_id: str) -> ExplanationRecord | None:
        with self._lock:
            return self._by_id.get(str(record_id))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            self._by_id.clear()

    def disk_paths(self, *, observer: str | None = None) -> list[Path]:
        """
        Return the JSONL files that would be scanned for reload/replay.
        """
        base = self.base_dir
        if observer is not None:
            d = base / ExplanationRecord.sanitize_observer_name(observer)
            if not d.exists():
                return []
            return sorted([p for p in d.rglob("*.jsonl") if p.is_file()])
        if not base.exists():
            return []
        return sorted([p for p in base.rglob("*.jsonl") if p.is_file()])

    def load_from_disk(self, *, observer: str | None = None, limit: int | None = None) -> int:
        """
        Load records from disk into memory (deduped by record_id).

        Returns the number of *new* records added to memory.
        """
        paths = self.disk_paths(observer=observer)
        added = 0
        for path in paths:
            try:
                with path.open("r", encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if not s:
                            continue
                        try:
                            rec = ExplanationRecord.from_json(s)
                        except Exception:
                            continue
                        before = len(self)
                        self.add(rec)
                        if len(self) > before:
                            added += 1
                            if limit is not None and added >= int(limit):
                                return added
            except FileNotFoundError:
                continue
            except Exception:
                continue
        return added

    def _append_to_disk(self, record: ExplanationRecord) -> None:
        """
        Append a record to a JSONL file partitioned by observer/date:
          ./tmp/observer_logs/<observer>/<YYYYMMDD>.jsonl
        """
        obs_dir = self.base_dir / ExplanationRecord.sanitize_observer_name(record.observer)
        obs_dir.mkdir(parents=True, exist_ok=True)

        # Partition by day (UTC).
        dt = record.created_at
        day = dt.strftime("%Y%m%d")
        path = obs_dir / f"{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(record.to_json())
            f.write("\n")


_DEFAULT_STORAGE: ExplanationStorage | None = None


def get_default_storage() -> ExplanationStorage:
    """
    Returns a process-wide default store.

    Default behavior:
    - In-memory always enabled
    - Disk persistence disabled unless `OBSERVER_PERSIST_EXPLANATIONS=1`
    """
    global _DEFAULT_STORAGE
    if _DEFAULT_STORAGE is None:
        _DEFAULT_STORAGE = ExplanationStorage()
    return _DEFAULT_STORAGE

