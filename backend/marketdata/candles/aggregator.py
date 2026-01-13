from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, DefaultDict

from backend.marketdata.candles.models import Candle, Tick
from backend.marketdata.candles.timeframes import Timeframe, bar_range_utc, parse_timeframes
from backend.time.nyse_time import UTC, ensure_aware_utc, parse_ts, utc_now

logger = logging.getLogger(__name__)


def _get_field(d: dict[str, Any], *names: str) -> Any:
    for n in names:
        if n in d:
            return d[n]
    return None


def parse_timestamp(value: Any) -> datetime:
    return parse_ts(value)


def parse_trade_event(event: dict[str, Any]) -> tuple[str, datetime, float, int]:
    """
    Parse a dict-like trade event.

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

    sym = str(symbol).strip().upper()
    if not sym:
        raise ValueError("empty symbol")

    ts_utc = parse_ts(ts)
    p = float(price)
    s = int(size)
    if s < 0:
        raise ValueError("negative size")
    return sym, ts_utc, p, s


@dataclass(slots=True)
class _BarState:
    symbol: str
    timeframe: str
    start_ts: datetime
    end_ts: datetime

    open: float
    high: float
    low: float
    close: float
    volume: int

    trade_count: int
    pv_sum: float  # sum(price * size) for vwap
    v_sum: int

    open_ts: datetime
    close_ts: datetime

    @classmethod
    def new(
        cls,
        *,
        symbol: str,
        timeframe: str,
        start_ts: datetime,
        end_ts: datetime,
        tick: Tick,
    ) -> "_BarState":
        return cls(
            symbol=symbol,
            timeframe=timeframe,
            start_ts=ensure_aware_utc(start_ts),
            end_ts=ensure_aware_utc(end_ts),
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.size,
            trade_count=1,
            pv_sum=tick.price * tick.size,
            v_sum=tick.size,
            open_ts=ensure_aware_utc(tick.ts),
            close_ts=ensure_aware_utc(tick.ts),
        )

    def apply(self, tick: Tick) -> None:
        """
        Apply a tick into an existing bar.

        Determinism rules:
        - open: earliest tick by timestamp within the bar
        - close: latest tick by timestamp within the bar
        - high/low: across all ticks
        """
        ts = ensure_aware_utc(tick.ts)
        price = float(tick.price)
        size = int(tick.size)

        self.high = max(self.high, price)
        self.low = min(self.low, price)
        if ts < self.open_ts:
            self.open_ts = ts
            self.open = price
        if ts >= self.close_ts:
            self.close_ts = ts
            self.close = price

        self.volume += size
        self.trade_count += 1
        self.pv_sum += price * size
        self.v_sum += size

    def vwap(self) -> float | None:
        if self.v_sum <= 0:
            return None
        return self.pv_sum / float(self.v_sum)

    def to_candle(self, *, is_final: bool) -> Candle:
        return Candle(
            symbol=self.symbol,
            timeframe=self.timeframe,
            start_ts=self.start_ts,
            end_ts=self.end_ts,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            vwap=self.vwap(),
            trade_count=self.trade_count,
            is_final=is_final,
        )


class CandleAggregator:
    """
    Deterministic, TradingView-style candle aggregation over a tick stream.

    - Bars are aligned to wall-clock boundaries in `tz_market` (default: America/New_York).
    - Uses event-time watermarking with a bounded out-of-order tolerance.
    - Only emits *finalized* candles from `ingest_tick()` and `flush()`.
    """

    def __init__(
        self,
        timeframes: list[str],
        max_lateness_seconds: int = 2,
        tz_market: str = "America/New_York",
        *,
        session_daily: bool = False,
    ) -> None:
        self.tz_market = tz_market
        self.session_daily = session_daily

        if max_lateness_seconds < 0:
            raise ValueError("max_lateness_seconds must be >= 0")
        self.lateness = timedelta(seconds=int(max_lateness_seconds))

        self._tfs: list[Timeframe] = parse_timeframes(timeframes)
        self._bars: dict[tuple[str, str, datetime], _BarState] = {}
        self._watermark: dict[tuple[str, str], datetime] = {}  # (symbol, timeframe) -> max event ts

        # Observability counters
        self.candles_finalized = 0
        self.late_drops = 0

    @property
    def timeframes(self) -> list[str]:
        return [tf.text for tf in self._tfs]

    def ingest_tick(self, tick: Tick) -> list[Candle]:
        """
        Ingest a single tick and return any newly finalized candles.
        """
        tick = Tick(ts=tick.ts, price=tick.price, size=tick.size, symbol=tick.symbol)
        out: list[Candle] = []

        for tf in self._tfs:
            tf_key = (tick.symbol, tf.text)

            prev_wm = self._watermark.get(tf_key)
            wm = tick.ts if prev_wm is None else max(prev_wm, tick.ts)
            cutoff = wm - self.lateness
            if tick.ts < cutoff:
                self.late_drops += 1
                logger.info(
                    "late_drop tick (beyond tolerance) | symbol=%s tf=%s tick_ts=%s cutoff=%s",
                    tick.symbol,
                    tf.text,
                    ensure_aware_utc(tick.ts).isoformat(),
                    ensure_aware_utc(cutoff).isoformat(),
                )
                continue

            self._watermark[tf_key] = wm

            start_utc, end_utc = bar_range_utc(tick.ts, tf, tz=self.tz_market, session_daily=self.session_daily)
            bar_key = (tick.symbol, tf.text, start_utc)

            st = self._bars.get(bar_key)
            if st is None:
                self._bars[bar_key] = _BarState.new(
                    symbol=tick.symbol,
                    timeframe=tf.text,
                    start_ts=start_utc,
                    end_ts=end_utc,
                    tick=tick,
                )
            else:
                st.apply(tick)

            out.extend(self._finalize_ready(tf_key, watermark=wm))

        return out

    def _finalize_ready(self, tf_key: tuple[str, str], *, watermark: datetime) -> list[Candle]:
        watermark = ensure_aware_utc(watermark)
        finalize_before = watermark - self.lateness
        symbol, tf_text = tf_key

        finalized: list[Candle] = []
        for (sym, tft, start), st in list(self._bars.items()):
            if sym != symbol or tft != tf_text:
                continue
            if st.end_ts <= finalize_before:
                self._bars.pop((sym, tft, start), None)
                finalized.append(st.to_candle(is_final=True))
                self.candles_finalized += 1
        finalized.sort(key=lambda c: (c.symbol, c.timeframe, c.start_ts))
        return finalized

    def flush(self, now_ts: datetime | None = None) -> list[Candle]:
        """
        Finalize bars older than (now_ts - max_lateness_seconds).
        Intended for periodic timers and shutdown.
        """
        now_utc = ensure_aware_utc(now_ts or utc_now())
        finalize_before = now_utc - self.lateness

        for key, prev in list(self._watermark.items()):
            self._watermark[key] = max(prev, now_utc)

        finalized: list[Candle] = []
        for k, st in list(self._bars.items()):
            if st.end_ts <= finalize_before:
                self._bars.pop(k, None)
                finalized.append(st.to_candle(is_final=True))
                self.candles_finalized += 1
        finalized.sort(key=lambda c: (c.symbol, c.timeframe, c.start_ts))
        return finalized

    def get_open_bars(self) -> dict[str, dict[str, list[dict[str, Any]]]]:
        """
        Debug/ops visibility into currently open (not-finalized) bar states.
        """
        out: DefaultDict[str, DefaultDict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for (sym, tf, _), st in self._bars.items():
            out[sym][tf].append(
                {
                    "symbol": st.symbol,
                    "timeframe": st.timeframe,
                    "start_ts": st.start_ts.astimezone(UTC).isoformat(),
                    "end_ts": st.end_ts.astimezone(UTC).isoformat(),
                    "open": st.open,
                    "high": st.high,
                    "low": st.low,
                    "close": st.close,
                    "volume": st.volume,
                    "trade_count": st.trade_count,
                    "vwap": st.vwap(),
                }
            )
        return {sym: {tf: sorted(rows, key=lambda r: r["start_ts"]) for tf, rows in tfs.items()} for sym, tfs in out.items()}

    # ---------------------------------------------------------------------
    # Back-compat convenience: accept dict-like trade events
    # ---------------------------------------------------------------------

    def ingest(self, event: dict[str, Any]) -> list[Candle]:
        """
        Back-compat adapter for older scripts: accept a dict-like trade event.
        Returns finalized candles only (no partial updates).
        """
        try:
            symbol, ts, price, size = parse_trade_event(event)
        except Exception:
            logger.debug("trade parse error | event=%r", event, exc_info=True)
            return []
        return self.ingest_tick(Tick(ts=ts, price=price, size=size, symbol=symbol))

    def ops_snapshot(self) -> dict[str, Any]:
        return {
            "timeframes": self.timeframes,
            "tz_market": self.tz_market,
            "session_daily": self.session_daily,
            "max_lateness_seconds": int(self.lateness.total_seconds()),
            "candles_finalized": self.candles_finalized,
            "late_drops": self.late_drops,
            "open_bar_states": len(self._bars),
        }

