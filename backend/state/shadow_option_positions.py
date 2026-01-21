"""
Shadow-only option position tracking (in-process authority).

This module is intentionally:
- Firestore-free (no remote persistence)
- safe to import in any runtime (strategy runner, local tools, tests)

It provides:
- In-memory tracking of option positions by contract symbol
- Open / Close operations
- Expiry auto-close at end-of-day (NY time, 16:00 by default)
- Queries: net delta, net gamma, exposure by expiry
- Optional local JSON persistence (best-effort) for debugging / local iteration
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Mapping, MutableMapping, Optional

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _normalize_greeks(greeks: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not greeks:
        return {}
    out: Dict[str, Any] = {}
    for k, v in greeks.items():
        key = str(k).strip()
        if not key:
            continue
        if key.lower() in {"delta", "gamma", "theta", "vega", "rho", "iv", "implied_vol", "implied_volatility"}:
            fv = _safe_float(v)
            out[key] = fv
        else:
            out[key] = v
    return out


def _parse_expiry_date(contract_symbol: str) -> Optional[date]:
    """
    Best-effort expiry date parser.

    Supports common patterns:
    - OCC-ish: <ROOT><YYMMDD><C|P><...>
      Example: SPY240119C00450000
    - ISO-ish: <ROOT><YYYYMMDD><C|P><...>
      Example: SPY20240119C450
    """
    sym = str(contract_symbol or "").strip().replace(" ", "")
    if not sym:
        return None

    # Find the first occurrence of a call/put marker preceded by a date.
    # 8-digit date (YYYYMMDD)
    for i in range(8, len(sym)):
        if sym[i] in ("C", "P") and sym[i - 8 : i].isdigit():
            try:
                y = int(sym[i - 8 : i - 4])
                m = int(sym[i - 4 : i - 2])
                d = int(sym[i - 2 : i])
                return date(y, m, d)
            except Exception:
                break

    # 6-digit date (YYMMDD) - assume 2000-2079, else 1980-1999 (best-effort)
    for i in range(6, len(sym)):
        if sym[i] in ("C", "P") and sym[i - 6 : i].isdigit():
            try:
                yy = int(sym[i - 6 : i - 4])
                mm = int(sym[i - 4 : i - 2])
                dd = int(sym[i - 2 : i])
                century = 2000 if yy <= 79 else 1900
                return date(century + yy, mm, dd)
            except Exception:
                break

    return None


@dataclass(frozen=True)
class ShadowGreeksSnapshot:
    """
    Stores a greeks snapshot (raw + normalized) at a point in time.
    """

    as_of_utc: datetime
    values: Dict[str, Any] = field(default_factory=dict)

    @property
    def delta(self) -> float:
        return float(_safe_float(self.values.get("delta")) or 0.0)

    @property
    def gamma(self) -> float:
        return float(_safe_float(self.values.get("gamma")) or 0.0)


@dataclass
class ShadowOptionPosition:
    """
    Single net position per contract symbol (shadow-only).

    qty is signed: +N long, -N short.
    """

    contract_symbol: str
    qty: int
    entry_price: float
    entry_time_utc: datetime
    greeks: ShadowGreeksSnapshot = field(default_factory=lambda: ShadowGreeksSnapshot(as_of_utc=_utc_now(), values={}))
    expiry: Optional[date] = None
    updated_at_utc: datetime = field(default_factory=_utc_now)

    def net_delta(self, *, contract_multiplier: float = 100.0) -> float:
        return float(self.qty) * float(contract_multiplier) * float(self.greeks.delta)

    def net_gamma(self, *, contract_multiplier: float = 100.0) -> float:
        return float(self.qty) * float(contract_multiplier) * float(self.greeks.gamma)


@dataclass(frozen=True)
class ShadowOptionCloseEvent:
    contract_symbol: str
    qty_closed: int
    exit_price: Optional[float]
    exit_time_utc: datetime
    reason: str


class ShadowOptionPositions:
    """
    In-memory tracker for shadow-only option positions, with optional local persistence.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        *,
        persistence_path: str | None = None,
        auto_persist: bool = False,
        contract_multiplier: float = 100.0,
    ) -> None:
        self._lock = threading.RLock()
        self._positions: MutableMapping[str, ShadowOptionPosition] = {}
        self._close_events: list[ShadowOptionCloseEvent] = []
        self._contract_multiplier = float(contract_multiplier)
        self._persistence_path = (str(persistence_path).strip() if persistence_path else None) or None
        self._auto_persist = bool(auto_persist)

        if self._persistence_path:
            self.load_local(best_effort=True)

    # ---- persistence ----
    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "schema_version": int(self.SCHEMA_VERSION),
                "as_of_utc": _utc_now().isoformat(),
                "contract_multiplier": float(self._contract_multiplier),
                "positions": [self._position_to_json(p) for p in self._positions.values()],
                "close_events": [self._close_event_to_json(e) for e in self._close_events],
            }

    def save_local(self, *, path: str | None = None) -> None:
        target = (str(path).strip() if path else self._persistence_path) or None
        if not target:
            return
        data = self.to_dict()
        target_dir = os.path.dirname(target) or "."
        os.makedirs(target_dir, exist_ok=True)
        # Keep temp file in the same directory to ensure atomic replace works cross-filesystem.
        fd, tmp = tempfile.mkstemp(prefix="shadow_option_positions_", suffix=".json", dir=target_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            os.replace(tmp, target)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except Exception:
                pass

    def load_local(self, *, path: str | None = None, best_effort: bool = True) -> None:
        target = (str(path).strip() if path else self._persistence_path) or None
        if not target:
            return
        try:
            with open(target, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
            self._load_from_dict(raw)
        except Exception:
            if not best_effort:
                raise

    # ---- mutations ----
    def open(
        self,
        *,
        contract_symbol: str,
        qty: int,
        entry_price: float,
        entry_time_utc: datetime | None = None,
        greeks: Mapping[str, Any] | None = None,
        greeks_as_of_utc: datetime | None = None,
    ) -> ShadowOptionPosition:
        sym = str(contract_symbol or "").strip()
        if not sym:
            raise ValueError("contract_symbol must be non-empty")
        q = int(qty)
        if q == 0:
            raise ValueError("qty must be non-zero")
        px = float(entry_price)
        if px < 0:
            raise ValueError("entry_price must be non-negative")

        t_entry = _ensure_utc(entry_time_utc) if isinstance(entry_time_utc, datetime) else _utc_now()
        g_asof = _ensure_utc(greeks_as_of_utc) if isinstance(greeks_as_of_utc, datetime) else t_entry
        g = ShadowGreeksSnapshot(as_of_utc=g_asof, values=_normalize_greeks(greeks))
        expiry = _parse_expiry_date(sym)

        with self._lock:
            existing = self._positions.get(sym)
            if existing is None:
                pos = ShadowOptionPosition(
                    contract_symbol=sym,
                    qty=q,
                    entry_price=px,
                    entry_time_utc=t_entry,
                    greeks=g,
                    expiry=expiry,
                    updated_at_utc=_utc_now(),
                )
                self._positions[sym] = pos
            else:
                # Enforce open() as additive to the existing direction (use close() for reductions).
                if existing.qty != 0 and (existing.qty > 0) != (q > 0):
                    raise ValueError(
                        f"open() qty direction conflicts with existing position qty={existing.qty}; "
                        "use close() first, then open()"
                    )
                new_qty = int(existing.qty + q)
                # Weighted average entry price by absolute contract count.
                w_old = abs(int(existing.qty))
                w_new = abs(int(q))
                avg_px = (
                    (float(existing.entry_price) * w_old + float(px) * w_new) / float(max(1, w_old + w_new))
                    if (w_old + w_new) > 0
                    else float(px)
                )
                entry_time = min(existing.entry_time_utc, t_entry)
                pos = ShadowOptionPosition(
                    contract_symbol=sym,
                    qty=new_qty,
                    entry_price=float(avg_px),
                    entry_time_utc=entry_time,
                    greeks=g if g.values else existing.greeks,
                    expiry=existing.expiry or expiry,
                    updated_at_utc=_utc_now(),
                )
                self._positions[sym] = pos

            if self._auto_persist:
                self.save_local()
            return self._positions[sym]

    def close(
        self,
        *,
        contract_symbol: str,
        qty: int,
        exit_price: float | None = None,
        exit_time_utc: datetime | None = None,
        reason: str = "manual_close",
    ) -> ShadowOptionPosition | None:
        sym = str(contract_symbol or "").strip()
        if not sym:
            raise ValueError("contract_symbol must be non-empty")
        q_close = int(qty)
        if q_close <= 0:
            raise ValueError("qty must be positive for close()")
        px = float(exit_price) if exit_price is not None else None
        if px is not None and px < 0:
            raise ValueError("exit_price must be non-negative when provided")
        t_exit = _ensure_utc(exit_time_utc) if isinstance(exit_time_utc, datetime) else _utc_now()
        r = str(reason or "").strip() or "manual_close"

        with self._lock:
            pos = self._positions.get(sym)
            if pos is None or int(pos.qty) == 0:
                return None

            if q_close > abs(int(pos.qty)):
                raise ValueError(f"close qty exceeds open qty (requested={q_close} open={abs(int(pos.qty))})")

            sign = 1 if int(pos.qty) > 0 else -1
            new_qty = int(pos.qty - sign * q_close)
            self._close_events.append(
                ShadowOptionCloseEvent(
                    contract_symbol=sym,
                    qty_closed=int(q_close),
                    exit_price=px,
                    exit_time_utc=t_exit,
                    reason=r,
                )
            )

            if new_qty == 0:
                self._positions.pop(sym, None)
                if self._auto_persist:
                    self.save_local()
                return None

            updated = ShadowOptionPosition(
                contract_symbol=sym,
                qty=new_qty,
                entry_price=float(pos.entry_price),
                entry_time_utc=pos.entry_time_utc,
                greeks=pos.greeks,
                expiry=pos.expiry,
                updated_at_utc=_utc_now(),
            )
            self._positions[sym] = updated

            if self._auto_persist:
                self.save_local()
            return updated

    def update_greeks(
        self,
        *,
        contract_symbol: str,
        greeks: Mapping[str, Any],
        as_of_utc: datetime | None = None,
    ) -> ShadowOptionPosition | None:
        sym = str(contract_symbol or "").strip()
        if not sym:
            raise ValueError("contract_symbol must be non-empty")
        g_asof = _ensure_utc(as_of_utc) if isinstance(as_of_utc, datetime) else _utc_now()
        snap = ShadowGreeksSnapshot(as_of_utc=g_asof, values=_normalize_greeks(greeks))

        with self._lock:
            pos = self._positions.get(sym)
            if pos is None:
                return None
            updated = ShadowOptionPosition(
                contract_symbol=sym,
                qty=int(pos.qty),
                entry_price=float(pos.entry_price),
                entry_time_utc=pos.entry_time_utc,
                greeks=snap,
                expiry=pos.expiry,
                updated_at_utc=_utc_now(),
            )
            self._positions[sym] = updated
            if self._auto_persist:
                self.save_local()
            return updated

    def auto_close_expired_eod(
        self,
        *,
        now_utc: datetime | None = None,
        market_tz: str = "America/New_York",
        eod_local: time = time(16, 0),
    ) -> list[ShadowOptionCloseEvent]:
        """
        Auto-close positions whose expiry date has passed EOD in the given market TZ.

        Default behavior: treat EOD as 16:00 America/New_York.
        """
        t_now = _ensure_utc(now_utc) if isinstance(now_utc, datetime) else _utc_now()
        if ZoneInfo is None:
            # No timezone DB available; fail-closed (do nothing).
            return []
        tz = ZoneInfo(market_tz)
        now_local = t_now.astimezone(tz)
        local_date = now_local.date()
        cutoff_local = datetime.combine(local_date, eod_local, tzinfo=tz)

        to_close: list[tuple[str, int]] = []
        with self._lock:
            for sym, pos in list(self._positions.items()):
                exp = pos.expiry or _parse_expiry_date(sym)
                if exp is None:
                    continue
                expired = (local_date > exp) or (local_date == exp and now_local >= cutoff_local)
                if expired and int(pos.qty) != 0:
                    to_close.append((sym, abs(int(pos.qty))))

        closed: list[ShadowOptionCloseEvent] = []
        for sym, q in to_close:
            _ = self.close(contract_symbol=sym, qty=int(q), exit_price=None, exit_time_utc=t_now, reason="expiry_eod")
            # close() appends an event; pull the last one as the close event for this action
            with self._lock:
                if self._close_events:
                    closed.append(self._close_events[-1])
        return closed

    # ---- queries ----
    def positions(self) -> list[ShadowOptionPosition]:
        with self._lock:
            return list(self._positions.values())

    def close_events(self, *, limit: int | None = None) -> list[ShadowOptionCloseEvent]:
        with self._lock:
            if limit is None:
                return list(self._close_events)
            return list(self._close_events[-int(limit) :])

    def net_delta(self, *, contract_multiplier: float | None = None) -> float:
        mult = float(self._contract_multiplier if contract_multiplier is None else contract_multiplier)
        with self._lock:
            return float(sum(p.net_delta(contract_multiplier=mult) for p in self._positions.values()))

    def net_gamma(self, *, contract_multiplier: float | None = None) -> float:
        mult = float(self._contract_multiplier if contract_multiplier is None else contract_multiplier)
        with self._lock:
            return float(sum(p.net_gamma(contract_multiplier=mult) for p in self._positions.values()))

    def exposure_by_expiry(
        self,
        *,
        contract_multiplier: float | None = None,
    ) -> Dict[str, Dict[str, float]]:
        """
        Aggregate exposure by expiry date (ISO date string).

        Returns: { "YYYY-MM-DD": {"qty": ..., "net_delta": ..., "net_gamma": ...}, ... }
        """
        mult = float(self._contract_multiplier if contract_multiplier is None else contract_multiplier)
        out: Dict[str, Dict[str, float]] = {}
        with self._lock:
            for p in self._positions.values():
                exp = p.expiry or _parse_expiry_date(p.contract_symbol)
                key = exp.isoformat() if isinstance(exp, date) else "unknown"
                bucket = out.setdefault(key, {"qty": 0.0, "net_delta": 0.0, "net_gamma": 0.0})
                bucket["qty"] += float(p.qty)
                bucket["net_delta"] += float(p.net_delta(contract_multiplier=mult))
                bucket["net_gamma"] += float(p.net_gamma(contract_multiplier=mult))
        return out

    # ---- json helpers ----
    def _position_to_json(self, p: ShadowOptionPosition) -> Dict[str, Any]:
        d = asdict(p)
        d["entry_time_utc"] = _ensure_utc(p.entry_time_utc).isoformat()
        d["updated_at_utc"] = _ensure_utc(p.updated_at_utc).isoformat()
        d["expiry"] = p.expiry.isoformat() if isinstance(p.expiry, date) else None
        d["greeks"] = {
            "as_of_utc": _ensure_utc(p.greeks.as_of_utc).isoformat(),
            "values": dict(p.greeks.values or {}),
        }
        return d

    def _close_event_to_json(self, e: ShadowOptionCloseEvent) -> Dict[str, Any]:
        return {
            "contract_symbol": e.contract_symbol,
            "qty_closed": int(e.qty_closed),
            "exit_price": float(e.exit_price) if e.exit_price is not None else None,
            "exit_time_utc": _ensure_utc(e.exit_time_utc).isoformat(),
            "reason": str(e.reason),
        }

    def _load_from_dict(self, raw: Mapping[str, Any]) -> None:
        schema = int(raw.get("schema_version") or 0)
        if schema != int(self.SCHEMA_VERSION):
            # Unknown schema: ignore (best-effort)
            return
        positions = raw.get("positions") or []
        close_events = raw.get("close_events") or []

        def _parse_dt(s: Any) -> datetime:
            if isinstance(s, datetime):
                return _ensure_utc(s)
            if isinstance(s, str) and s.strip():
                return _ensure_utc(datetime.fromisoformat(s.replace("Z", "+00:00")))
            return _utc_now()

        def _parse_date(s: Any) -> Optional[date]:
            if isinstance(s, date) and not isinstance(s, datetime):
                return s
            if isinstance(s, str) and s.strip():
                try:
                    return date.fromisoformat(s.strip())
                except Exception:
                    return None
            return None

        new_positions: Dict[str, ShadowOptionPosition] = {}
        for item in positions:
            if not isinstance(item, Mapping):
                continue
            sym = str(item.get("contract_symbol") or "").strip()
            if not sym:
                continue
            greeks_raw = item.get("greeks") or {}
            g_asof = _parse_dt(greeks_raw.get("as_of_utc"))
            g_vals = _normalize_greeks(greeks_raw.get("values") if isinstance(greeks_raw, Mapping) else None)
            pos = ShadowOptionPosition(
                contract_symbol=sym,
                qty=int(item.get("qty") or 0),
                entry_price=float(item.get("entry_price") or 0.0),
                entry_time_utc=_parse_dt(item.get("entry_time_utc")),
                greeks=ShadowGreeksSnapshot(as_of_utc=g_asof, values=g_vals),
                expiry=_parse_date(item.get("expiry")) or _parse_expiry_date(sym),
                updated_at_utc=_parse_dt(item.get("updated_at_utc")),
            )
            if pos.qty != 0:
                new_positions[sym] = pos

        new_events: list[ShadowOptionCloseEvent] = []
        for item in close_events:
            if not isinstance(item, Mapping):
                continue
            sym = str(item.get("contract_symbol") or "").strip()
            if not sym:
                continue
            ev = ShadowOptionCloseEvent(
                contract_symbol=sym,
                qty_closed=int(item.get("qty_closed") or 0),
                exit_price=_safe_float(item.get("exit_price")),
                exit_time_utc=_parse_dt(item.get("exit_time_utc")),
                reason=str(item.get("reason") or "unknown"),
            )
            if ev.qty_closed > 0:
                new_events.append(ev)

        with self._lock:
            self._positions = new_positions
            self._close_events = new_events


# Module-level singleton (purely in-process). Callers may also instantiate their own trackers.
_STATE = ShadowOptionPositions()


def get_shadow_option_positions_state() -> ShadowOptionPositions:
    return _STATE

