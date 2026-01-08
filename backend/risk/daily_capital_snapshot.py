from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from backend.time.nyse_time import UTC, is_trading_day, market_close_dt, market_open_dt, to_utc


class DailyCapitalSnapshotError(RuntimeError):
    """
    Raised when daily-capital snapshot invariants are violated.

    This is intentionally a "fail hard" error: it should prevent trading rather than
    allowing implicit fallbacks or silent date drift.
    """


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_float(v: Any, *, field: str) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s == "":
            return 0.0
        try:
            return float(s)
        except ValueError as e:  # pragma: no cover
            raise DailyCapitalSnapshotError(f"Invalid numeric string for {field}: {v!r}") from e
    raise DailyCapitalSnapshotError(f"Unsupported type for {field}: {type(v).__name__}")


def _fingerprint_payload(payload: dict[str, Any]) -> str:
    """
    Stable content fingerprint to detect post-creation mutation/tampering.
    """
    dumped = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(dumped.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DailyCapitalSnapshot:
    """
    Immutable daily-capital snapshot.

    Key invariants:
    - Created once per (tenant_id, uid, trading_date)
    - Must not be mutated after creation (fingerprint-enforced)
    - Must be valid for the current trading day; otherwise trading is blocked
    """

    tenant_id: str
    uid: str
    trading_date_ny: date

    created_at_utc: datetime
    valid_from_utc: datetime
    expires_at_utc: datetime

    starting_equity_usd: float
    starting_cash_usd: float
    starting_buying_power_usd: float

    source: str
    source_updated_at_iso: Optional[str]

    fingerprint: str

    @staticmethod
    def for_today_from_account_snapshot(
        *,
        tenant_id: str,
        uid: str,
        trading_date_ny: date,
        account_snapshot: dict[str, Any],
        now_utc: Optional[datetime] = None,
        source: str = "account_snapshot",
    ) -> "DailyCapitalSnapshot":
        """
        Build a snapshot for a given NY trading date from an account snapshot payload.
        """
        if not is_trading_day(trading_date_ny):
            raise DailyCapitalSnapshotError(f"Refusing to create snapshot on non-trading day: {trading_date_ny.isoformat()}")

        now_utc = to_utc(now_utc or _utc_now())

        open_ny = market_open_dt(trading_date_ny)
        close_ny = market_close_dt(trading_date_ny)
        valid_from_utc = to_utc(open_ny)
        expires_at_utc = to_utc(close_ny)

        # Capital fields (best-effort). These are the "daily bankroll" anchors.
        starting_equity = _as_float(account_snapshot.get("equity"), field="equity")
        starting_cash = _as_float(account_snapshot.get("cash"), field="cash")
        starting_bp = _as_float(account_snapshot.get("buying_power"), field="buying_power")

        source_updated_at_iso = None
        if isinstance(account_snapshot.get("updated_at_iso"), str):
            source_updated_at_iso = account_snapshot.get("updated_at_iso")

        base: dict[str, Any] = {
            "tenant_id": str(tenant_id),
            "uid": str(uid),
            "trading_date_ny": trading_date_ny.isoformat(),
            "created_at_utc": now_utc.astimezone(UTC).isoformat(),
            "valid_from_utc": valid_from_utc.astimezone(UTC).isoformat(),
            "expires_at_utc": expires_at_utc.astimezone(UTC).isoformat(),
            "starting_equity_usd": float(starting_equity),
            "starting_cash_usd": float(starting_cash),
            "starting_buying_power_usd": float(starting_bp),
            "source": str(source),
            "source_updated_at_iso": source_updated_at_iso,
        }
        fp = _fingerprint_payload(base)
        return DailyCapitalSnapshot(
            tenant_id=str(tenant_id),
            uid=str(uid),
            trading_date_ny=trading_date_ny,
            created_at_utc=now_utc.astimezone(UTC),
            valid_from_utc=valid_from_utc.astimezone(UTC),
            expires_at_utc=expires_at_utc.astimezone(UTC),
            starting_equity_usd=float(starting_equity),
            starting_cash_usd=float(starting_cash),
            starting_buying_power_usd=float(starting_bp),
            source=str(source),
            source_updated_at_iso=source_updated_at_iso,
            fingerprint=fp,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "uid": self.uid,
            "trading_date_ny": self.trading_date_ny.isoformat(),
            "created_at_utc": self.created_at_utc.astimezone(UTC),
            "valid_from_utc": self.valid_from_utc.astimezone(UTC),
            "expires_at_utc": self.expires_at_utc.astimezone(UTC),
            "starting_equity_usd": float(self.starting_equity_usd),
            "starting_cash_usd": float(self.starting_cash_usd),
            "starting_buying_power_usd": float(self.starting_buying_power_usd),
            "source": self.source,
            "source_updated_at_iso": self.source_updated_at_iso,
            "fingerprint": self.fingerprint,
            "schema_version": 1,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "DailyCapitalSnapshot":
        try:
            trading_date_ny = date.fromisoformat(str(d.get("trading_date_ny") or ""))
        except Exception as e:  # pragma: no cover
            raise DailyCapitalSnapshotError("Invalid trading_date_ny in snapshot") from e

        created_at_utc = to_utc(d.get("created_at_utc"))
        valid_from_utc = to_utc(d.get("valid_from_utc"))
        expires_at_utc = to_utc(d.get("expires_at_utc"))

        base: dict[str, Any] = {
            "tenant_id": str(d.get("tenant_id") or ""),
            "uid": str(d.get("uid") or ""),
            "trading_date_ny": trading_date_ny.isoformat(),
            "created_at_utc": created_at_utc.astimezone(UTC).isoformat(),
            "valid_from_utc": valid_from_utc.astimezone(UTC).isoformat(),
            "expires_at_utc": expires_at_utc.astimezone(UTC).isoformat(),
            "starting_equity_usd": float(d.get("starting_equity_usd") or 0.0),
            "starting_cash_usd": float(d.get("starting_cash_usd") or 0.0),
            "starting_buying_power_usd": float(d.get("starting_buying_power_usd") or 0.0),
            "source": str(d.get("source") or ""),
            "source_updated_at_iso": d.get("source_updated_at_iso") if isinstance(d.get("source_updated_at_iso"), str) else None,
        }
        expected = _fingerprint_payload(base)
        got = str(d.get("fingerprint") or "")
        if not got or got != expected:
            raise DailyCapitalSnapshotError(
                "DailyCapitalSnapshot fingerprint mismatch (snapshot mutated or corrupted)"
            )

        tenant_id = str(d.get("tenant_id") or "").strip()
        uid = str(d.get("uid") or "").strip()
        if not tenant_id or not uid:
            raise DailyCapitalSnapshotError("Snapshot missing tenant_id/uid")

        return DailyCapitalSnapshot(
            tenant_id=tenant_id,
            uid=uid,
            trading_date_ny=trading_date_ny,
            created_at_utc=created_at_utc,
            valid_from_utc=valid_from_utc,
            expires_at_utc=expires_at_utc,
            starting_equity_usd=float(d.get("starting_equity_usd") or 0.0),
            starting_cash_usd=float(d.get("starting_cash_usd") or 0.0),
            starting_buying_power_usd=float(d.get("starting_buying_power_usd") or 0.0),
            source=str(d.get("source") or ""),
            source_updated_at_iso=d.get("source_updated_at_iso") if isinstance(d.get("source_updated_at_iso"), str) else None,
            fingerprint=got,
        )

    def assert_trade_window(self, *, now_utc: Optional[datetime] = None) -> None:
        """
        Enforce:
        - no trades before snapshot is valid (market open)
        - no trades after snapshot expires (market close)
        """
        now = to_utc(now_utc or _utc_now())
        if now < self.valid_from_utc:
            raise DailyCapitalSnapshotError(
                f"Trading blocked: snapshot not yet valid (now={now.isoformat()} < valid_from={self.valid_from_utc.isoformat()})"
            )
        if now >= self.expires_at_utc:
            raise DailyCapitalSnapshotError(
                f"Trading blocked: snapshot expired (now={now.isoformat()} >= expires_at={self.expires_at_utc.isoformat()})"
            )

    def assert_date_match(self, *, trading_date_ny: date) -> None:
        """
        Fail hard if the snapshot's trading date mismatches the expected trading day.
        """
        if self.trading_date_ny != trading_date_ny:
            raise DailyCapitalSnapshotError(
                f"Trading day mismatch: snapshot_date={self.trading_date_ny.isoformat()} expected={trading_date_ny.isoformat()}"
            )


class DailyCapitalSnapshotStore:
    """
    Firestore-backed store for DailyCapitalSnapshot.

    Path:
      tenants/{tenant_id}/users/{uid}/daily_capital_snapshots/{YYYY-MM-DD}
    """

    def __init__(self, *, db: Any):
        self._db = db

    @staticmethod
    def doc_id_for_date(trading_date_ny: date) -> str:
        return trading_date_ny.isoformat()

    def _doc_ref(self, *, tenant_id: str, uid: str, trading_date_ny: date):
        return (
            self._db.collection("tenants")
            .document(str(tenant_id))
            .collection("users")
            .document(str(uid))
            .collection("daily_capital_snapshots")
            .document(self.doc_id_for_date(trading_date_ny))
        )

    def get(self, *, tenant_id: str, uid: str, trading_date_ny: date) -> Optional[DailyCapitalSnapshot]:
        doc = self._doc_ref(tenant_id=tenant_id, uid=uid, trading_date_ny=trading_date_ny).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        return DailyCapitalSnapshot.from_dict(data)

    def create_once(
        self,
        *,
        tenant_id: str,
        uid: str,
        trading_date_ny: date,
        account_snapshot: dict[str, Any],
        now_utc: Optional[datetime] = None,
        source: str = "account_snapshot",
    ) -> DailyCapitalSnapshot:
        snap = DailyCapitalSnapshot.for_today_from_account_snapshot(
            tenant_id=tenant_id,
            uid=uid,
            trading_date_ny=trading_date_ny,
            account_snapshot=account_snapshot,
            now_utc=now_utc,
            source=source,
        )
        ref = self._doc_ref(tenant_id=tenant_id, uid=uid, trading_date_ny=trading_date_ny)
        # Firestore create() enforces immutability: it fails if doc already exists.
        ref.create(snap.to_dict())
        return snap

    def get_or_create_once(
        self,
        *,
        tenant_id: str,
        uid: str,
        trading_date_ny: date,
        account_snapshot: dict[str, Any],
        now_utc: Optional[datetime] = None,
        source: str = "account_snapshot",
    ) -> DailyCapitalSnapshot:
        existing = self.get(tenant_id=tenant_id, uid=uid, trading_date_ny=trading_date_ny)
        if existing is not None:
            return existing
        try:
            return self.create_once(
                tenant_id=tenant_id,
                uid=uid,
                trading_date_ny=trading_date_ny,
                account_snapshot=account_snapshot,
                now_utc=now_utc,
                source=source,
            )
        except Exception:
            # If a concurrent creator won, load again (but still validate fingerprint).
            loaded = self.get(tenant_id=tenant_id, uid=uid, trading_date_ny=trading_date_ny)
            if loaded is None:
                raise
            return loaded

