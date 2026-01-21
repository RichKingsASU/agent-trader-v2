from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Literal, Optional, Union

PROTOCOL_VERSION = "v1"

# NDJSON: one JSON object per line, UTF-8, '\n' terminated.
#
# Host -> guest messages:
# - {"type":"market_event", ...}
# - {"type":"shutdown"}
#
# Guest -> host messages:
# - {"type":"order_intent", ...}
# - {"type":"log", ...}

MessageTypeIn = Literal["market_event", "shutdown"]
MessageTypeOut = Literal["order_intent", "log"]

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop", "stop_limit"]
TimeInForce = Literal["day", "gtc", "ioc", "fok"]

OptionRight = Literal["CALL", "PUT"]
OptionOrderType = Literal["MARKET"]
OptionTimeInForce = Literal["DAY"]

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,127}$")


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ProtocolError(ValueError):
    pass


def _require(d: Dict[str, Any], key: str) -> Any:
    if key not in d:
        raise ProtocolError(f"missing required field: {key}")
    return d[key]


def _require_str(d: Dict[str, Any], key: str) -> str:
    v = _require(d, key)
    if not isinstance(v, str) or not v:
        raise ProtocolError(f"field {key} must be non-empty string")
    return v


def _require_id(d: Dict[str, Any], key: str) -> str:
    v = _require_str(d, key)
    if not _ID_RE.match(v):
        raise ProtocolError(f"field {key} must match {_ID_RE.pattern}")
    return v


def _require_dict(d: Dict[str, Any], key: str) -> Dict[str, Any]:
    v = _require(d, key)
    if not isinstance(v, dict):
        raise ProtocolError(f"field {key} must be object")
    return v


def _optional_float(d: Dict[str, Any], key: str) -> Optional[float]:
    if key not in d or d[key] is None:
        return None
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ProtocolError(f"field {key} must be number")
    return float(v)


def _optional_str(d: Dict[str, Any], key: str) -> Optional[str]:
    if key not in d or d[key] is None:
        return None
    v = d[key]
    if not isinstance(v, str) or not v:
        raise ProtocolError(f"field {key} must be non-empty string")
    return v


@dataclass(frozen=True)
class MarketEvent:
    """
    The ONLY input to a user strategy.
    """

    protocol: str
    type: Literal["market_event"]
    event_id: str
    ts: str
    symbol: str
    source: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "type": self.type,
            "event_id": self.event_id,
            "ts": self.ts,
            "symbol": self.symbol,
            "source": self.source,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class OrderIntent:
    """
    The ONLY output from a user strategy.
    """

    protocol: str
    type: Literal["order_intent"]
    intent_id: str
    event_id: str
    ts: str
    symbol: str
    side: Side
    qty: float
    order_type: OrderType
    limit_price: Optional[float] = None
    time_in_force: Optional[TimeInForce] = None
    client_tag: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "protocol": self.protocol,
            "type": self.type,
            "intent_id": self.intent_id,
            "event_id": self.event_id,
            "ts": self.ts,
            "symbol": self.symbol,
            "side": self.side,
            "qty": self.qty,
            "order_type": self.order_type,
        }
        if self.limit_price is not None:
            d["limit_price"] = self.limit_price
        if self.time_in_force is not None:
            d["time_in_force"] = self.time_in_force
        if self.client_tag is not None:
            d["client_tag"] = self.client_tag
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d


@dataclass(frozen=True)
class OptionOrderIntent:
    """
    Phase O1: single-leg option order intent.

    Safety boundary:
    - This is *parsed* and *validated* only.
    - OPTIONS EXECUTION NOT IMPLEMENTED: any attempt to hand this object to execution
      code must raise (see `to_execution_intent`).
    """

    protocol: str
    type: Literal["order_intent"]
    intent_id: str
    event_id: str
    ts: str

    # Discriminator
    asset_type: Literal["OPTION"]

    # Contract details (single-leg only)
    contract_symbol: str
    underlying: str
    expiration: str  # YYYY-MM-DD
    strike: float
    right: OptionRight

    # Contracts
    qty: float
    multiplier: int = 100

    # Phase O1: hard-coded routing constraints
    order_type: OptionOrderType = "MARKET"
    time_in_force: OptionTimeInForce = "DAY"

    client_tag: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_execution_intent(self) -> None:
        # OPTIONS EXECUTION NOT IMPLEMENTED
        raise NotImplementedError("OPTIONS EXECUTION NOT IMPLEMENTED")

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "protocol": self.protocol,
            "type": self.type,
            "intent_id": self.intent_id,
            "event_id": self.event_id,
            "ts": self.ts,
            "asset_type": self.asset_type,
            "contract_symbol": self.contract_symbol,
            "underlying": self.underlying,
            "expiration": self.expiration,
            "strike": self.strike,
            "right": self.right,
            "qty": self.qty,
            "multiplier": self.multiplier,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
        }
        if self.client_tag is not None:
            d["client_tag"] = self.client_tag
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d


@dataclass(frozen=True)
class LogMessage:
    protocol: str
    type: Literal["log"]
    ts: str
    level: Literal["debug", "info", "warn", "error"]
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "type": self.type,
            "ts": self.ts,
            "level": self.level,
            "message": self.message,
        }


def parse_inbound_message(obj: Dict[str, Any]) -> Union[MarketEvent, Dict[str, Any]]:
    protocol = _require_str(obj, "protocol")
    if protocol != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol: {protocol}")
    msg_type = _require_str(obj, "type")
    if msg_type == "market_event":
        event_id = _require_id(obj, "event_id")
        ts = _require_str(obj, "ts")
        symbol = _require_str(obj, "symbol")
        source = _require_str(obj, "source")
        payload = _require_dict(obj, "payload")
        return MarketEvent(
            protocol=protocol,
            type="market_event",
            event_id=event_id,
            ts=ts,
            symbol=symbol,
            source=source,
            payload=payload,
        )
    if msg_type == "shutdown":
        return obj
    raise ProtocolError(f"unsupported inbound type: {msg_type}")


def _require_iso_date(d: Dict[str, Any], key: str) -> str:
    v = _require_str(d, key)
    # YYYY-MM-DD (ISO date) enforcement.
    # Fail-closed: reject non-parseable values rather than normalizing.
    try:
        # Import locally to keep module import surface small.
        from datetime import date as _date  # noqa: WPS433

        _date.fromisoformat(v)
    except Exception:
        raise ProtocolError(f"field {key} must be ISO date YYYY-MM-DD")
    return v


def parse_order_intent(obj: Dict[str, Any]) -> Union[OrderIntent, OptionOrderIntent]:
    protocol = _require_str(obj, "protocol")
    if protocol != PROTOCOL_VERSION:
        raise ProtocolError(f"unsupported protocol: {protocol}")
    msg_type = _require_str(obj, "type")
    if msg_type != "order_intent":
        raise ProtocolError(f"expected order_intent, got: {msg_type}")

    intent_id = _require_id(obj, "intent_id")
    event_id = _require_id(obj, "event_id")
    ts = _require_str(obj, "ts")

    # Phase O1: OptionOrderIntent support (single-leg only).
    asset_type_raw = obj.get("asset_type")
    if isinstance(asset_type_raw, str) and asset_type_raw.strip().upper() == "OPTION":
        # Reject multi-leg payloads explicitly (fail-closed).
        if "legs" in obj:
            raise ProtocolError("multi-leg option payloads not supported")

        contract_symbol = _require_str(obj, "contract_symbol")
        underlying = _require_str(obj, "underlying")
        expiration = _require_iso_date(obj, "expiration")

        strike_raw = _require(obj, "strike")
        if isinstance(strike_raw, bool) or not isinstance(strike_raw, (int, float)):
            raise ProtocolError("field strike must be number")
        strike = float(strike_raw)
        if strike <= 0:
            raise ProtocolError("field strike must be > 0")

        right_raw = _require_str(obj, "right").strip().upper()
        if right_raw not in ("CALL", "PUT"):
            raise ProtocolError("field right must be CALL or PUT")

        qty_raw = _require(obj, "qty")
        if isinstance(qty_raw, bool) or not isinstance(qty_raw, (int, float)):
            raise ProtocolError("field qty must be number")
        qty = float(qty_raw)
        if qty <= 0:
            raise ProtocolError("field qty must be > 0")

        multiplier_raw = obj.get("multiplier", 100)
        if isinstance(multiplier_raw, bool) or not isinstance(multiplier_raw, (int, float)):
            raise ProtocolError("field multiplier must be number")
        multiplier = int(multiplier_raw)
        if multiplier <= 0:
            raise ProtocolError("field multiplier must be > 0")

        order_type_raw = _require_str(obj, "order_type").strip().upper()
        if order_type_raw != "MARKET":
            raise ProtocolError("field order_type invalid (MARKET only for options)")

        tif_raw = _require_str(obj, "time_in_force").strip().upper()
        if tif_raw != "DAY":
            raise ProtocolError("field time_in_force invalid (DAY only for options)")

        client_tag = _optional_str(obj, "client_tag")
        metadata = obj.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ProtocolError("field metadata must be object")

        return OptionOrderIntent(
            protocol=protocol,
            type="order_intent",
            intent_id=intent_id,
            event_id=event_id,
            ts=ts,
            asset_type="OPTION",
            contract_symbol=contract_symbol,
            underlying=underlying,
            expiration=expiration,
            strike=strike,
            right=right_raw,  # type: ignore[arg-type]
            qty=qty,
            multiplier=multiplier,
            order_type="MARKET",
            time_in_force="DAY",
            client_tag=client_tag,
            metadata=metadata,
        )

    # Backward-compatible parsing for existing (equity) OrderIntent remains unchanged.
    symbol = _require_str(obj, "symbol")
    side = _require_str(obj, "side")
    if side not in ("buy", "sell"):
        raise ProtocolError("field side must be 'buy' or 'sell'")
    qty_raw = _require(obj, "qty")
    if isinstance(qty_raw, bool) or not isinstance(qty_raw, (int, float)):
        raise ProtocolError("field qty must be number")
    qty = float(qty_raw)
    if qty <= 0:
        raise ProtocolError("field qty must be > 0")
    order_type = _require_str(obj, "order_type")
    if order_type not in ("market", "limit", "stop", "stop_limit"):
        raise ProtocolError("field order_type invalid")

    limit_price = _optional_float(obj, "limit_price")
    tif = _optional_str(obj, "time_in_force")
    if tif is not None and tif not in ("day", "gtc", "ioc", "fok"):
        raise ProtocolError("field time_in_force invalid")
    client_tag = _optional_str(obj, "client_tag")
    metadata = obj.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise ProtocolError("field metadata must be object")

    return OrderIntent(
        protocol=protocol,
        type="order_intent",
        intent_id=intent_id,
        event_id=event_id,
        ts=ts,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        qty=qty,
        order_type=order_type,  # type: ignore[arg-type]
        limit_price=limit_price,
        time_in_force=tif,  # type: ignore[arg-type]
        client_tag=client_tag,
        metadata=metadata,
    )


def dumps_ndjson(objs: Iterable[Dict[str, Any]]) -> bytes:
    out = []
    for o in objs:
        out.append(json.dumps(o, separators=(",", ":"), ensure_ascii=False))
    return ("\n".join(out) + "\n").encode("utf-8")


def loads_ndjson(blob: Union[str, bytes]) -> List[Dict[str, Any]]:
    if isinstance(blob, bytes):
        text = blob.decode("utf-8", errors="strict")
    else:
        text = blob
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]

