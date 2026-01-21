from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field

# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

# Canonical v2 contract version (SemVer string).
# - MAJOR: breaking changes
# - MINOR: additive optional fields / enum widening
# - PATCH: documentation / clarifications (no schema shape changes)
CONTRACT_VERSION_V2: str = "2.0.0"


# ---------------------------------------------------------------------------
# Common constrained primitives
# ---------------------------------------------------------------------------

# Canonical decimal representation for money/price/quantity:
# - JSON string, not JSON number (avoids float rounding & language differences)
# - base-10, optional leading "-", optional fractional part
DecimalString = Annotated[
    str,
    Field(
        pattern=r"^-?\d+(\.\d+)?$",
        examples=["0", "1", "10.5", "-0.01"],
        description="Base-10 decimal encoded as a JSON string.",
    ),
]

CurrencyCode = Annotated[
    str,
    Field(
        min_length=3,
        max_length=3,
        pattern=r"^[A-Z]{3}$",
        examples=["USD", "EUR"],
        description="ISO 4217 currency code (upper-case).",
    ),
]

CountryCode = Annotated[
    str,
    Field(
        min_length=2,
        max_length=2,
        pattern=r"^[A-Z]{2}$",
        examples=["US", "GB"],
        description="ISO 3166-1 alpha-2 country code (upper-case).",
    ),
]


# ---------------------------------------------------------------------------
# Enums (broker-agnostic)
# ---------------------------------------------------------------------------

class AssetClass(str, Enum):
    equity = "equity"
    option = "option"
    future = "future"
    fx = "fx"
    crypto = "crypto"
    index = "index"
    other = "other"


class Side(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    market = "market"
    limit = "limit"
    stop = "stop"
    stop_limit = "stop_limit"


class TimeInForce(str, Enum):
    day = "day"
    gtc = "gtc"
    ioc = "ioc"
    fok = "fok"


class SignalAction(str, Enum):
    enter_long = "enter_long"
    enter_short = "enter_short"
    exit = "exit"
    increase = "increase"
    reduce = "reduce"
    hold = "hold"


class RiskDecisionType(str, Enum):
    allow = "allow"
    deny = "deny"
    modify = "modify"


class ExecutionMode(str, Enum):
    live = "live"
    paper = "paper"
    simulated = "simulated"


class ExecutionStatus(str, Enum):
    accepted = "accepted"
    rejected = "rejected"
    partially_filled = "partially_filled"
    filled = "filled"
    cancelled = "cancelled"
    expired = "expired"
    failed = "failed"


class ExplanationSubjectType(str, Enum):
    trading_signal = "trading_signal"
    order_intent = "order_intent"
    shadow_trade = "shadow_trade"
    execution_result = "execution_result"
    risk_decision = "risk_decision"


# Stable, vendor-agnostic indicator for "where this object is meant to be used".
Environment = Literal["prod", "staging", "dev", "local"]

