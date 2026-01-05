from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.common.timeutils import UTC, ensure_aware_utc, parse_timestamp, utc_now
from backend.marketdata.candles.models import EmittedCandle
from backend.marketdata.candles.timeframes import Timeframe, bucket_range_utc, parse_timeframes

logger = logging.getLogger(__name__)


def _get_field(obj: Any, *names: str) -> Any:
    """
    Fetch a field from dict-like or attribute-like objects.
    Returns None if not found.
    """
    if isinstance(obj, dict):
        for n in names:
            if n in obj:
                return obj[n]
        # Also allow case-insensitive lookup for common keys.
        lower_map = {str(k).lower(): v for k, v in obj.items()}
        for n in names:
            v = lower_map.get(n.lower())
            if v is not None:
                return v
        return None

    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _parse_trade_event(event: Any) -> tuple[str, datetime, float, int]:
    """
    Parse a trade-like event.
    Required fields:
      - symbol: symbol / sym / S
      - timestamp: timestamp / t / ts / time
      - price: price / p
      - size: size / s / qty / q
    """
    symbol = _get_field(event, "symbol", "sym", "S")
    ts = _get_field(event, "timestamp", "t", "ts", "time")
    price = _get_field(event, "price", "p")
    size = _get_field(event, "size", "s", "qty", "q")

    if symbol is None or ts is None or price is None or size is None:
        raise ValueError("missing required trade fields")

    symbol_s = str(symbol).strip().upper()
    if not symbol_s:
        raise ValueError("empty symbol")

    ts_utc = parse_timestamp(ts)

    p = float(price)
    s = int(size)
    if s < 0:
        raise ValueError("negative size")
    return symbol_s, ts_utc, p, s


@dataclass(slots=True)
class _CandleState:
    symbol: str
    timeframe: str
    ts_start_utc: datetime
    ts_end_utc: datetime

    open: float
    high: float
    low: float
    close: float
    volume: int

    trade_count: int
    pv_sum: float  # sum(price * size) for vwap
    v_sum: int

    first_event_ts: datetime
    last_event_ts: datetime

    final_emitted: bool = False
    dirty_since_final: bool = False

    @classmethod
    def new(
        cls,
        *,
        symbol: str,
        timeframe: str,
        ts_start_utc: datetime,
        ts_end_utc: datetime,
        price: float,
        size: int,
        event_ts: datetime,
    ) -> "_CandleState":
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            ts_start_utc=ensure_aware_utc(ts_start_utc),
            ts_end_utc=ensure_aware_utc(ts_end_utc),
            open=price,
            high=price,
            low=price,
            close=price,
            volume=size,
            trade_count=1,
            pv_sum=price * size,
            v_sum=size,
            first_event_ts=ensure_aware_utc(event_ts),
            last_event_ts=ensure_aware_utc(event_ts),
            final_emitted=False,
            dirty_since_final=False,
        )

    def apply(self, *, price: float, size: int, event_ts: datetime) -> None:
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        # Close follows last-received event time ordering (not exchange sequence).
        if ensure_aware_utc(event_ts) >= self.last_event_ts:
            self.close = price
            self.last_event_ts = ensure_aware_utc(event_ts)
        self.volume += size
        self.trade_count += 1
        self.pv_sum += price * size
        self.v_sum += size
        if self.final_emitted:
            self.dirty_since_final = True

    def vwap(self) -> float | None:
        if self.v_sum <= 0:
            return None
        return self.pv_sum / float(self.v_sum)

    def to_emitted(self, *, is_final: bool, source_event_ts: datetime | None) -> EmittedCandle:
        return EmittedCandle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            ts_start_utc=self.ts_start_utc,
            ts_end_utc=self.ts_end_utc,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            vwap=self.vwap(),
            trade_count=self.trade_count,
            is_final=is_final,
            source_event_ts=source_event_ts,
        )


class CandleAggregator:
    """
    Production-oriented real-time candle aggregation with bounded lateness.

    - Maintains rolling state per (symbol, timeframe, bucket_start).
    - Emits candle updates continuously (one per ingest per timeframe by default).
    - Emits final candles on rollover and on flush (watermark-based).
    """

    def __init__(
        self,
        timeframes: list[str],
        lateness_seconds: int = 5,
        tz_market: str = "America/New_York",
        *,
        session_daily: bool = False,
        emit_updates: bool = True,
    ) -> None:
        self.tz_market = tz_market
        self.session_daily = session_daily
        self.emit_updates = emit_updates

        if lateness_seconds < 0:
            raise ValueError("lateness_seconds must be >= 0")
        self.lateness = timedelta(seconds=int(lateness_seconds))

        self._tfs: list[Timeframe] = parse_timeframes(timeframes)
        self._states: dict[tuple[str, str, datetime], _CandleState] = {}
        self._watermark: dict[tuple[str, str], datetime] = {}
        self._latest_bucket_start: dict[tuple[str, str], datetime] = {}

        # Observability counters
        self.candles_emitted_final = 0
        self.candles_emitted_update = 0
        self.late_events_dropped = 0
        self.parse_errors = 0

    @property
    def timeframes(self) -> list[str]:
        return [tf.text for tf in self._tfs]

    def ingest(self, event: dict) -> list[EmittedCandle]:
        try:
            symbol, event_ts_utc, price, size = _parse_trade_event(event)
        except Exception as e:
            self.parse_errors += 1
            logger.debug("trade parse error: %s | event=%r", e, event)
            return []

        emitted: list[EmittedCandle] = []
        for tf in self._tfs:
            emitted.extend(self._ingest_one(symbol, tf, event_ts_utc, price, size))
        return emitted

    def _ingest_one(
        self,
        symbol: str,
        tf: Timeframe,
        event_ts_utc: datetime,
        price: float,
        size: int,
    ) -> list[EmittedCandle]:
        event_ts_utc = ensure_aware_utc(event_ts_utc)
        bucket_start, bucket_end = bucket_range_utc(
            event_ts_utc, tf, tz_market=self.tz_market, session_daily=self.session_daily
        )
        tf_key = (symbol, tf.text)

        prev_wm = self._watermark.get(tf_key)
        wm = event_ts_utc if prev_wm is None else max(prev_wm, event_ts_utc)
        cutoff = wm - self.lateness
        if event_ts_utc < cutoff:
            self.late_events_dropped += 1
            return []
        self._watermark[tf_key] = wm

        # On bucket rollover, emit a final for the previous "latest" bucket (TradingView-like stream behavior).
        emitted: list[EmittedCandle] = []
        prev_latest = self._latest_bucket_start.get(tf_key)
        if prev_latest is not None and bucket_start > prev_latest:
            prev_state = self._states.get((symbol, tf.text, prev_latest))
            if prev_state is not None:
                emitted.append(self._emit_final(prev_state, source_event_ts=event_ts_utc))
            self._latest_bucket_start[tf_key] = bucket_start
        elif prev_latest is None:
            self._latest_bucket_start[tf_key] = bucket_start

        key = (symbol, tf.text, bucket_start)
        st = self._states.get(key)
        if st is None:
            st = _CandleState.new(
                symbol=symbol,
                timeframe=tf.text,
                ts_start_utc=bucket_start,
                ts_end_utc=bucket_end,
                price=price,
                size=size,
                event_ts=event_ts_utc,
            )
            self._states[key] = st
        else:
            st.apply(price=price, size=size, event_ts=event_ts_utc)

        if self.emit_updates:
            emitted.append(st.to_emitted(is_final=False, source_event_ts=event_ts_utc))
            self.candles_emitted_update += 1

        emitted.extend(self._finalize_ready(tf_key, now_utc=wm))
        self._evict_old(tf_key, now_utc=wm)
        return emitted

    def _emit_final(self, st: _CandleState, *, source_event_ts: datetime | None) -> EmittedCandle:
        st.final_emitted = True
        st.dirty_since_final = False
        self.candles_emitted_final += 1
        return st.to_emitted(is_final=True, source_event_ts=source_event_ts)

    def _finalize_ready(self, tf_key: tuple[str, str], *, now_utc: datetime) -> list[EmittedCandle]:
        """
        Finalize candles whose ts_end is behind watermark by lateness.
        Also re-finalize candles that were updated after a prior final emission.
        """
        now_utc = ensure_aware_utc(now_utc)
        finalize_before = now_utc - self.lateness
        symbol, tf_text = tf_key

        out: list[EmittedCandle] = []
        for (sym, tft, start), st in list(self._states.items()):
            if sym != symbol or tft != tf_text:
                continue
            if st.ts_end_utc <= finalize_before and (not st.final_emitted or st.dirty_since_final):
                out.append(self._emit_final(st, source_event_ts=now_utc))
        return out

    def _evict_old(self, tf_key: tuple[str, str], *, now_utc: datetime) -> None:
        """
        Remove states that are safely behind the watermark to keep memory bounded.
        """
        now_utc = ensure_aware_utc(now_utc)
        symbol, tf_text = tf_key
        # Keep a small buffer behind lateness so late updates can still be applied.
        keep_after = now_utc - (self.lateness + timedelta(seconds=max(60, int(self.lateness.total_seconds()) * 3)))

        for (sym, tft, start), st in list(self._states.items()):
            if sym != symbol or tft != tf_text:
                continue
            if st.final_emitted and not st.dirty_since_final and st.ts_end_utc <= keep_after:
                self._states.pop((sym, tft, start), None)

    def flush(self, now: datetime | None = None) -> list[EmittedCandle]:
        """
        Finalize any candles older than (now - lateness). Intended for periodic timers/shutdown.
        """
        now_utc = ensure_aware_utc(now or utc_now())
        emitted: list[EmittedCandle] = []

        # Finalize across all symbols/timeframes using now_utc as the watermark.
        finalize_before = now_utc - self.lateness
        for st in list(self._states.values()):
            if st.ts_end_utc <= finalize_before and (not st.final_emitted or st.dirty_since_final):
                emitted.append(self._emit_final(st, source_event_ts=now_utc))

        # Best-effort eviction across all states after flush.
        for key in list(self._watermark.keys()):
            self._evict_old(key, now_utc=now_utc)

        return emitted

    def ops_snapshot(self) -> dict[str, Any]:
        """
        Lightweight snapshot for ops markers / logs.
        """
        last_ts_by_tf: dict[str, datetime] = {}
        for (_, tf_text), start in self._latest_bucket_start.items():
            cur = last_ts_by_tf.get(tf_text)
            if cur is None or start > cur:
                last_ts_by_tf[tf_text] = start

        return {
            "timeframes": self.timeframes,
            "candles_emitted_final": self.candles_emitted_final,
            "candles_emitted_update": self.candles_emitted_update,
            "late_events_dropped": self.late_events_dropped,
            "parse_errors": self.parse_errors,
            "active_candle_states": len(self._states),
            "last_candle_ts_by_timeframe": {k: v.astimezone(UTC).isoformat() for k, v in last_ts_by_tf.items()},
        }

