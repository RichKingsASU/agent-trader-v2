"""
Delta Momentum Bot for AgentTrader (options).

Strategy (stateful):
- Track open positions in-memory by `option_symbol -> entry_price`.
- If already in a position:
  - Compute PnL% = (current_price - entry_price) / entry_price
  - If PnL% > 0.20 (TP) or < -0.10 (SL), publish a SELL order and remove position.
- If not in a position:
  - If delta > 0.60, publish a BUY order and store entry_price.

Order publishing:
- Publishes a payload shaped like the `paper_orders` schema.
  (See `scripts/insert_paper_order.py` and `backend/strategy_service/models.py`.)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional, Tuple

from nats.aio.client import Client as NATS

from agenttrader.backend.utils.ops_markers import OpsMarker

logger = logging.getLogger("agenttrader.delta_momentum_bot")


def _resolve_quotes_subject() -> str:
    """
    Resolve the quotes subject for this bot.

    Precedence:
    1) `NATS_QUOTES_SUBJECT` (explicit override)
    2) Tenant-scoped default subject derived from `TENANT_ID`
    """
    override = os.getenv("NATS_QUOTES_SUBJECT")
    if override:
        return override

    tenant_id = (os.getenv("TENANT_ID") or "").strip()
    if not tenant_id:
        raise RuntimeError(
            "TENANT_ID environment variable is required when NATS_QUOTES_SUBJECT is not set"
        )

    # Convention: option market events are tenant-scoped.
    return f"market.{tenant_id}.options"


def _extract_option_symbol_price_delta(payload: Dict[str, Any]) -> Tuple[str, float, Optional[float]]:
    """
    Best-effort extraction for option symbol + current price + delta.

    Supports a few common shapes:
    - {"option_symbol":"...","price":1.23,"delta":0.65}
    - {"option_symbol":"...","mid":1.23,"greeks":{"delta":0.65}}
    - {"symbol":"...","last":1.23,"delta":0.65}
    - {"S":"...","p":1.23,"d":0.65} (compact variants)
    """
    option_symbol = (
        payload.get("option_symbol")
        or payload.get("optionContractSymbol")
        or payload.get("symbol")
        or payload.get("S")
        or payload.get("sym")
    )
    if not option_symbol or not isinstance(option_symbol, str):
        raise ValueError("Missing/invalid option_symbol")

    price = payload.get("mid")
    if price is None:
        price = payload.get("price")
    if price is None:
        price = payload.get("last")
    if price is None:
        price = payload.get("p")
    if price is None:
        bid = payload.get("bid")
        ask = payload.get("ask")
        if bid is not None and ask is not None:
            price = (float(bid) + float(ask)) / 2.0
    if price is None:
        raise ValueError("Missing current_price")

    delta: Optional[float] = None
    raw_delta = payload.get("delta")
    if raw_delta is None:
        raw_delta = payload.get("d")
    if raw_delta is None:
        greeks = payload.get("greeks") or payload.get("g")
        if isinstance(greeks, dict):
            raw_delta = greeks.get("delta") or greeks.get("d")
    if raw_delta is not None:
        try:
            delta = float(raw_delta)
        except Exception:
            delta = None

    return str(option_symbol).strip().upper(), float(price), delta


@dataclass(frozen=True)
class BotConfig:
    # NATS
    nats_url: str = os.getenv("NATS_URL", "nats://localhost:4222")
    quotes_subject: str = field(default_factory=_resolve_quotes_subject)
    orders_subject: str = os.getenv("NATS_ORDERS_SUBJECT", "execution.user_001.orders")
    durable_name: str = os.getenv("NATS_DURABLE_NAME", "delta-momentum-bot")

    # Identity / ops
    service_id: str = os.getenv("SERVICE_ID", "delta-momentum-bot")
    service_type: str = os.getenv("SERVICE_TYPE", "alpha-agent")

    # Strategy parameters
    delta_entry_threshold: float = float(os.getenv("DELTA_ENTRY_THRESHOLD", "0.60"))
    take_profit_pct: float = float(os.getenv("TAKE_PROFIT_PCT", "0.20"))
    stop_loss_pct: float = float(os.getenv("STOP_LOSS_PCT", "-0.10"))

    # Order parameters (paper_orders schema)
    user_id: str = os.getenv("USER_ID", "")
    broker_account_id: str = os.getenv("BROKER_ACCOUNT_ID", "")
    strategy_id: str = os.getenv("STRATEGY_ID", "")
    instrument_type: str = os.getenv("INSTRUMENT_TYPE", "option")
    order_type: str = os.getenv("ORDER_TYPE", "market")
    time_in_force: str = os.getenv("TIME_IN_FORCE", "day")
    notional: float = float(os.getenv("ORDER_NOTIONAL", "200"))
    quantity: Optional[float] = (
        float(os.getenv("ORDER_QUANTITY", "1")) if os.getenv("ORDER_QUANTITY") else None
    )

    # Reconnect controls
    reconnect_backoff_s: float = float(os.getenv("RECONNECT_BACKOFF_S", "1.5"))
    max_backoff_s: float = float(os.getenv("MAX_BACKOFF_S", "15"))


class DeltaMomentumBot:
    def __init__(
        self,
        nats_url: Optional[str] = None,
        strategy_params: Optional[Dict[str, Any]] = None,
        cfg: Optional[BotConfig] = None,
    ):
        """
        Stateful bot:
        - `self.positions` tracks open positions by option_symbol -> entry_price.
        """
        base_cfg = cfg or BotConfig()
        params = strategy_params or {}

        overrides: Dict[str, Any] = {}
        # Subjects / identifiers
        if "quotes_subject" in params:
            overrides["quotes_subject"] = str(params["quotes_subject"])
        if "orders_subject" in params:
            overrides["orders_subject"] = str(params["orders_subject"])
        if "durable_name" in params:
            overrides["durable_name"] = str(params["durable_name"])
        if "service_id" in params:
            overrides["service_id"] = str(params["service_id"])
        if "service_type" in params:
            overrides["service_type"] = str(params["service_type"])

        # Strategy tunables
        if "delta_entry_threshold" in params:
            overrides["delta_entry_threshold"] = float(params["delta_entry_threshold"])
        if "take_profit_pct" in params:
            overrides["take_profit_pct"] = float(params["take_profit_pct"])
        if "stop_loss_pct" in params:
            overrides["stop_loss_pct"] = float(params["stop_loss_pct"])

        # Order / identity fields
        for key in (
            "user_id",
            "broker_account_id",
            "strategy_id",
            "instrument_type",
            "order_type",
            "time_in_force",
        ):
            if key in params:
                overrides[key] = str(params[key])
        if "notional" in params:
            overrides["notional"] = float(params["notional"])
        if "quantity" in params:
            overrides["quantity"] = None if params["quantity"] is None else float(params["quantity"])

        # Reconnect controls
        if "reconnect_backoff_s" in params:
            overrides["reconnect_backoff_s"] = float(params["reconnect_backoff_s"])
        if "max_backoff_s" in params:
            overrides["max_backoff_s"] = float(params["max_backoff_s"])

        cfg_final = replace(base_cfg, **overrides) if overrides else base_cfg
        if nats_url:
            cfg_final = replace(cfg_final, nats_url=str(nats_url))

        self.cfg = cfg_final
        self.ops = OpsMarker()
        self._stop = asyncio.Event()
        self._nats_closed = asyncio.Event()

        self._nc: Optional[NATS] = None
        self._js: Any = None

        # Required by the task: initialize positions dict.
        self.positions: Dict[str, float] = {}

    async def stop(self) -> None:
        self._stop.set()
        if self._nc and self._nc.is_connected:
            with contextlib.suppress(Exception):
                await self._nc.drain()
            with contextlib.suppress(Exception):
                await self._nc.close()

    async def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self.ops.heartbeat(
                self.cfg.service_id,
                self.cfg.service_type,
                status="running",
                metadata={
                    "nats_url": self.cfg.nats_url,
                    "quotes_subject": self.cfg.quotes_subject,
                    "orders_subject": self.cfg.orders_subject,
                    "delta_entry_threshold": self.cfg.delta_entry_threshold,
                    "take_profit_pct": self.cfg.take_profit_pct,
                    "stop_loss_pct": self.cfg.stop_loss_pct,
                },
                version=os.getenv("SERVICE_VERSION"),
            )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                continue

    async def _connect(self) -> None:
        self._nats_closed = asyncio.Event()

        async def _on_error(e: Exception) -> None:
            logger.error("NATS error: %s", e)

        async def _on_disconnected() -> None:
            logger.warning("Disconnected from NATS")

        async def _on_reconnected() -> None:
            try:
                url = self._nc.connected_url.netloc if self._nc else "unknown"
            except Exception:
                url = "unknown"
            logger.info("Reconnected to NATS (%s)", url)

        async def _on_closed() -> None:
            logger.warning("NATS connection closed")
            self._nats_closed.set()

        self._nc = NATS()
        await self._nc.connect(
            servers=[self.cfg.nats_url],
            reconnect_time_wait=1,
            max_reconnect_attempts=-1,
            ping_interval=10,
            max_outstanding_pings=2,
            error_cb=_on_error,
            disconnected_cb=_on_disconnected,
            reconnected_cb=_on_reconnected,
            closed_cb=_on_closed,
        )
        self._js = self._nc.jetstream()

    def _build_paper_order_payload(
        self,
        *,
        symbol: str,
        side: str,
        notional: float,
        quantity: Optional[float],
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Construct a payload aligned to `public.paper_orders` schema.
        """
        side_norm = str(side).strip().lower()
        if side_norm not in ("buy", "sell"):
            raise ValueError(f"Invalid side: {side}")

        if not self.cfg.user_id or not self.cfg.broker_account_id or not self.cfg.strategy_id:
            raise RuntimeError(
                "Missing USER_ID / BROKER_ACCOUNT_ID / STRATEGY_ID (required for paper_orders payload)"
            )

        raw_order = {
            "instrument_type": self.cfg.instrument_type,
            "symbol": symbol,
            "side": side_norm,
            "order_type": self.cfg.order_type,
            "time_in_force": self.cfg.time_in_force,
            "notional": float(notional),
            "quantity": quantity,
            "strategy_id": self.cfg.strategy_id,
            "broker_account_id": self.cfg.broker_account_id,
            "user_id": self.cfg.user_id,
            # extra metadata is safe in jsonb and useful for audit/debug
            "meta": metadata,
        }

        return {
            "user_id": self.cfg.user_id,
            "broker_account_id": self.cfg.broker_account_id,
            "strategy_id": self.cfg.strategy_id,
            "symbol": symbol,
            "instrument_type": self.cfg.instrument_type,
            "side": side_norm,
            "order_type": self.cfg.order_type,
            "time_in_force": self.cfg.time_in_force,
            "notional": float(notional),
            "quantity": quantity,
            "risk_allowed": True,
            "risk_scope": "strategy",
            "risk_reason": None,
            "raw_order": raw_order,
            "status": "simulated",
        }

    async def send_order(
        self,
        *,
        symbol: str,
        side: str,
        current_price: float,
        delta: Optional[float],
        entry_price: Optional[float],
        pnl_pct: Optional[float],
        raw_payload: Dict[str, Any],
    ) -> None:
        """
        Publish a paper order payload (`paper_orders`-shaped) to NATS.
        """
        if self._nc is None:
            raise RuntimeError("NATS is not connected")

        metadata = {
            "ts": time.time(),
            "service_id": self.cfg.service_id,
            "current_price": float(current_price),
            "delta": delta,
            "entry_price": entry_price,
            "pnl_pct": pnl_pct,
            "market_payload": raw_payload,
        }

        payload = self._build_paper_order_payload(
            symbol=symbol,
            side=side,
            notional=self.cfg.notional,
            quantity=self.cfg.quantity,
            metadata=metadata,
        )

        await self._nc.publish(self.cfg.orders_subject, json.dumps(payload).encode("utf-8"))

    async def market_handler(self, payload: Dict[str, Any]) -> None:
        """
        Core strategy logic (requested behavior).
        """
        option_symbol, current_price, delta = _extract_option_symbol_price_delta(payload)

        # 1) Exit logic: if in position, compute PnL% and TP/SL.
        if option_symbol in self.positions:
            entry_price = float(self.positions[option_symbol])
            if entry_price <= 0:
                # Defensive: invalid entry price -> drop state.
                self.positions.pop(option_symbol, None)
                return

            pnl_pct = (float(current_price) - entry_price) / entry_price
            if pnl_pct > self.cfg.take_profit_pct or pnl_pct < self.cfg.stop_loss_pct:
                logger.info(
                    "Exit %s pnl_pct=%.4f (entry=%.4f current=%.4f tp=%.2f sl=%.2f)",
                    option_symbol,
                    pnl_pct,
                    entry_price,
                    float(current_price),
                    self.cfg.take_profit_pct,
                    self.cfg.stop_loss_pct,
                )
                await self.send_order(
                    symbol=option_symbol,
                    side="sell",
                    current_price=float(current_price),
                    delta=delta,
                    entry_price=entry_price,
                    pnl_pct=pnl_pct,
                    raw_payload=payload,
                )
                self.positions.pop(option_symbol, None)
            return

        # 2) Entry logic: if no position, enter when delta exceeds threshold.
        if delta is None:
            return
        if float(delta) > self.cfg.delta_entry_threshold:
            logger.info(
                "Entry %s delta=%.4f price=%.4f (threshold=%.2f)",
                option_symbol,
                float(delta),
                float(current_price),
                self.cfg.delta_entry_threshold,
            )
            await self.send_order(
                symbol=option_symbol,
                side="buy",
                current_price=float(current_price),
                delta=float(delta),
                entry_price=None,
                pnl_pct=None,
                raw_payload=payload,
            )
            self.positions[option_symbol] = float(current_price)

    async def _handle_message(self, msg: Any) -> None:
        raw_bytes = getattr(msg, "data", b"") or b""
        try:
            raw_text = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            raw_text = str(raw_bytes)

        try:
            payload = json.loads(raw_text)
            if not isinstance(payload, dict):
                raise ValueError("Payload is not a JSON object")

            await self.market_handler(payload)
        except Exception as e:
            self.ops.log_dead_letter(self.cfg.service_id, {"raw": raw_text}, str(e))
        finally:
            if hasattr(msg, "ack"):
                with contextlib.suppress(Exception):
                    await msg.ack()

    async def _subscribe_quotes(self) -> None:
        assert self._nc is not None
        assert self._js is not None

        async def _cb(msg: Any) -> None:
            await self._handle_message(msg)

        try:
            from nats.js.api import DeliverPolicy  # type: ignore

            await self._js.subscribe(
                self.cfg.quotes_subject,
                durable=self.cfg.durable_name,
                manual_ack=True,
                deliver_policy=DeliverPolicy.NEW,
                cb=_cb,
            )
            logger.info(
                "Subscribed (JetStream) to %s durable=%s",
                self.cfg.quotes_subject,
                self.cfg.durable_name,
            )
        except Exception as e:
            logger.warning(
                "JetStream subscribe failed (%s). Falling back to core subscribe for %s",
                e,
                self.cfg.quotes_subject,
            )
            await self._nc.subscribe(self.cfg.quotes_subject, cb=_cb)
            logger.info("Subscribed (core) to %s", self.cfg.quotes_subject)

    async def run(self) -> None:
        logging.basicConfig(level=logging.INFO)
        logger.info("Starting DeltaMomentumBot (service_id=%s)", self.cfg.service_id)

        hb_task = asyncio.create_task(self._heartbeat_loop())
        backoff = self.cfg.reconnect_backoff_s
        try:
            while not self._stop.is_set():
                try:
                    await self._connect()
                    await self._subscribe_quotes()
                    backoff = self.cfg.reconnect_backoff_s
                    while not self._stop.is_set() and not self._nats_closed.is_set():
                        await asyncio.sleep(1)
                    if self._nats_closed.is_set() and not self._stop.is_set():
                        raise RuntimeError("NATS connection closed")
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.exception("Run loop error: %s", e)
                    await asyncio.sleep(backoff)
                    backoff = min(self.cfg.max_backoff_s, backoff * 1.7)
                finally:
                    if self._nc:
                        with contextlib.suppress(Exception):
                            await self._nc.close()
                        self._nc = None
                        self._js = None
        finally:
            hb_task.cancel()
            with contextlib.suppress(Exception):
                await hb_task


async def _main() -> None:
    bot = DeltaMomentumBot()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(bot.stop()))
        except NotImplementedError:
            signal.signal(sig, lambda *_: asyncio.create_task(bot.stop()))

    await bot.run()


if __name__ == "__main__":
    asyncio.run(_main())

