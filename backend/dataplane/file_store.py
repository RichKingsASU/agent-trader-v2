from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from backend.common.timeutils import ensure_aware_utc, parse_timestamp

from .interfaces import CandleStore, ProposalStore, TickStore


def default_data_root() -> Path:
    """
    Root directory for the file-based data plane.

    Defaults to `data/` in the current working directory, overridable with:
    - DATA_PLANE_ROOT=/some/path
    """

    return Path(os.getenv("DATA_PLANE_ROOT") or "data")


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_symbol(symbol: str) -> str:
    """
    Convert a symbol into a filename-safe token.

    Examples:
    - 'BTC/USD' -> 'BTC_USD'
    - 'BRK.B' -> 'BRK.B'
    - 'ES=F' -> 'ES_F'
    """

    s = (symbol or "").strip().upper()
    s = _SAFE_FILENAME_RE.sub("_", s)
    s = re.sub(r"_+", "_", s).strip("._-")
    return s or "UNKNOWN"


def _json_line(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=str)


def _iter_dates(start_utc: datetime, end_utc: datetime) -> list[date]:
    s = ensure_aware_utc(start_utc).date()
    e = ensure_aware_utc(end_utc).date()
    if e < s:
        return []
    out: list[date] = []
    cur = s
    while cur <= e:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


def _dt_to_utc_iso(value: Any) -> str:
    return ensure_aware_utc(parse_timestamp(value)).isoformat()


def _as_dict(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if is_dataclass(obj):
        return asdict(obj)
    to_row = getattr(obj, "to_row", None)
    if callable(to_row):
        r = to_row()
        if isinstance(r, dict):
            return dict(r)
    # Pydantic v2 / v1 fallback
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        r = model_dump(mode="json")
        if isinstance(r, dict):
            return dict(r)
    dict_m = getattr(obj, "dict", None)
    if callable(dict_m):
        r = dict_m()
        if isinstance(r, dict):
            return dict(r)
    # Best-effort attrs
    out: dict[str, Any] = {}
    for k in dir(obj):
        if k.startswith("_"):
            continue
        try:
            v = getattr(obj, k)
        except Exception:
            continue
        if callable(v):
            continue
        out[k] = v
    return out


class _FileStoreBase:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_data_root()

    def _append_lines(self, path: Path, lines: Iterable[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            for line in lines:
                if not line.endswith("\n"):
                    line = line + "\n"
                f.write(line)


class FileTickStore(_FileStoreBase, TickStore):
    """
    Partitioned NDJSON tick store.

    Layout:
      data/ticks/YYYY/MM/DD/<symbol>.ndjson
    """

    def _tick_path(self, d: date, symbol: str) -> Path:
        s = sanitize_symbol(symbol)
        return self.root / "ticks" / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}" / f"{s}.ndjson"

    def write_ticks(self, symbol: str, ticks: Sequence[Mapping[str, Any]]) -> None:
        if not ticks:
            return

        by_day: dict[date, list[str]] = {}
        for t in ticks:
            td = dict(t)
            td.setdefault("symbol", symbol)
            # Normalize timestamp for partitioning and replay-friendliness.
            ts_val = td.get("timestamp", td.get("ts"))
            if ts_val is None:
                raise ValueError("tick missing timestamp/ts")
            ts_iso = _dt_to_utc_iso(ts_val)
            td["timestamp"] = ts_iso
            td.setdefault("ts", ts_iso)

            d = ensure_aware_utc(parse_timestamp(ts_iso)).date()
            by_day.setdefault(d, []).append(_json_line(td))

        for d, lines in by_day.items():
            self._append_lines(self._tick_path(d, symbol), lines)

    def query_ticks(self, symbol: str, start_utc: datetime, end_utc: datetime) -> list[dict[str, Any]]:
        start = ensure_aware_utc(start_utc)
        end = ensure_aware_utc(end_utc)
        out: list[dict[str, Any]] = []
        for d in _iter_dates(start, end):
            p = self._tick_path(d, symbol)
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts_val = rec.get("timestamp", rec.get("ts"))
                    if ts_val is None:
                        continue
                    ts = ensure_aware_utc(parse_timestamp(ts_val))
                    if start <= ts <= end:
                        out.append(rec)

        out.sort(key=lambda r: ensure_aware_utc(parse_timestamp(r.get("timestamp", r.get("ts")))))
        return out


class FileCandleStore(_FileStoreBase, CandleStore):
    """
    Partitioned NDJSON candle store.

    Layout:
      data/candles/<timeframe>/YYYY/MM/DD/<symbol>.ndjson
    """

    def _candle_path(self, d: date, timeframe: str, symbol: str) -> Path:
        s = sanitize_symbol(symbol)
        tf = (timeframe or "").strip()
        if not tf:
            raise ValueError("timeframe required")
        return self.root / "candles" / tf / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}" / f"{s}.ndjson"

    def write_candles(self, symbol: str, timeframe: str, candles: Sequence[Any]) -> None:
        if not candles:
            return

        by_day: dict[date, list[str]] = {}
        for c in candles:
            cd = _as_dict(c)
            cd.setdefault("symbol", symbol)
            cd.setdefault("timeframe", timeframe)

            # Accept both ts_start/ts_end and ts_start_utc/ts_end_utc
            ts_start = cd.get("ts_start_utc", cd.get("ts_start"))
            ts_end = cd.get("ts_end_utc", cd.get("ts_end"))
            if ts_start is None or ts_end is None:
                raise ValueError("candle missing ts_start/ts_end")

            cd["ts_start_utc"] = _dt_to_utc_iso(ts_start)
            cd["ts_end_utc"] = _dt_to_utc_iso(ts_end)
            cd.pop("ts_start", None)
            cd.pop("ts_end", None)

            d = ensure_aware_utc(parse_timestamp(cd["ts_start_utc"])).date()
            by_day.setdefault(d, []).append(_json_line(cd))

        for d, lines in by_day.items():
            self._append_lines(self._candle_path(d, timeframe, symbol), lines)

    def query_candles(
        self, symbol: str, timeframe: str, start_utc: datetime, end_utc: datetime
    ) -> list[dict[str, Any]]:
        start = ensure_aware_utc(start_utc)
        end = ensure_aware_utc(end_utc)
        out: list[dict[str, Any]] = []
        for d in _iter_dates(start, end):
            p = self._candle_path(d, timeframe, symbol)
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    ts_start = rec.get("ts_start_utc")
                    if ts_start is None:
                        continue
                    ts = ensure_aware_utc(parse_timestamp(ts_start))
                    if start <= ts <= end:
                        out.append(rec)

        out.sort(key=lambda r: ensure_aware_utc(parse_timestamp(r["ts_start_utc"])))
        return out


class FileProposalStore(_FileStoreBase, ProposalStore):
    """
    Partitioned NDJSON proposal store.

    Layout:
      data/proposals/YYYY/MM/DD/proposals.ndjson
    """

    def _proposal_path(self, d: date) -> Path:
        return self.root / "proposals" / f"{d:%Y}" / f"{d:%m}" / f"{d:%d}" / "proposals.ndjson"

    def write_proposals(self, proposals: Sequence[Any]) -> None:
        if not proposals:
            return

        by_day: dict[date, list[str]] = {}
        for p in proposals:
            pd = _as_dict(p)
            # Most proposal models use created_at_utc; fall back to created_at/ts.
            created = pd.get("created_at_utc", pd.get("created_at", pd.get("ts")))
            if created is None:
                # Avoid naive `utcnow()`; keep explicit UTC offset/Z.
                created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                pd["created_at_utc"] = created
            pd["created_at_utc"] = _dt_to_utc_iso(created)

            d = ensure_aware_utc(parse_timestamp(pd["created_at_utc"])).date()
            by_day.setdefault(d, []).append(_json_line(pd))

        for d, lines in by_day.items():
            self._append_lines(self._proposal_path(d), lines)

    def query_proposals(self, **filters: Any) -> list[dict[str, Any]]:
        """
        Scaffold query. Supported filters:
        - start_utc, end_utc (datetime)
        - symbol
        - strategy_name
        - status
        """

        start_utc = filters.get("start_utc")
        end_utc = filters.get("end_utc")
        if start_utc is None or end_utc is None:
            raise ValueError("query_proposals requires start_utc and end_utc")
        start = ensure_aware_utc(start_utc)
        end = ensure_aware_utc(end_utc)

        sym_f = (filters.get("symbol") or "").strip().upper() or None
        strat_f = (filters.get("strategy_name") or "").strip() or None
        status_f = (filters.get("status") or "").strip().upper() or None

        out: list[dict[str, Any]] = []
        for d in _iter_dates(start, end):
            p = self._proposal_path(d)
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    created = rec.get("created_at_utc", rec.get("created_at", rec.get("ts")))
                    if created is None:
                        continue
                    ts = ensure_aware_utc(parse_timestamp(created))
                    if not (start <= ts <= end):
                        continue
                    if sym_f is not None and str(rec.get("symbol", "")).strip().upper() != sym_f:
                        continue
                    if strat_f is not None and str(rec.get("strategy_name", "")).strip() != strat_f:
                        continue
                    if status_f is not None and str(rec.get("status", "")).strip().upper() != status_f:
                        continue
                    out.append(rec)

        out.sort(key=lambda r: ensure_aware_utc(parse_timestamp(r.get("created_at_utc", r.get("created_at")))))
        return out

