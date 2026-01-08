"""
Minimal, dependency-free metrics + Prometheus text exposition.

Design goals:
- stdlib-only (no prometheus_client dependency)
- tiny API: counters, gauges, labeled counters
- safe for multi-threaded access (used by background tasks + HTTP handlers)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Tuple

logger = logging.getLogger(__name__)


def _now_s() -> float:
    return time.time()


def _escape_label_value(v: str) -> str:
    # Prometheus text format label value escaping: \, ", and newlines.
    return (
        str(v)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )


def _format_labels(label_items: Iterable[Tuple[str, str]]) -> str:
    items = list(label_items)
    if not items:
        return ""
    inner = ",".join(f'{k}="{_escape_label_value(v)}"' for k, v in items)
    return "{" + inner + "}"


@dataclass(frozen=True)
class _MetricDef:
    name: str
    help: str
    mtype: str  # "counter" | "gauge"
    label_names: Tuple[str, ...] = ()


class MetricRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._defs: Dict[str, _MetricDef] = {}
        # Values keyed by metric name -> labels tuple -> value
        self._values: Dict[str, Dict[Tuple[Tuple[str, str], ...], float]] = {}

    def counter(self, name: str, *, help: str = "", label_names: Iterable[str] = ()) -> "Counter":
        return Counter(self, name=name, help=help, label_names=tuple(label_names))

    def gauge(self, name: str, *, help: str = "", label_names: Iterable[str] = ()) -> "Gauge":
        return Gauge(self, name=name, help=help, label_names=tuple(label_names))

    def _ensure_def(self, mdef: _MetricDef) -> None:
        with self._lock:
            existing = self._defs.get(mdef.name)
            if existing is None:
                self._defs[mdef.name] = mdef
                self._values.setdefault(mdef.name, {})
                return
            # Best-effort: enforce consistent type/labels
            if existing.mtype != mdef.mtype or existing.label_names != mdef.label_names:
                raise ValueError(
                    f"Metric redefined: {mdef.name} existing(type={existing.mtype},labels={existing.label_names}) "
                    f"new(type={mdef.mtype},labels={mdef.label_names})"
                )

    def _labels_key(self, label_names: Tuple[str, ...], labels: Mapping[str, Any] | None) -> Tuple[Tuple[str, str], ...]:
        if not label_names:
            return ()
        if not labels:
            raise ValueError("labels required for labeled metric")
        items: list[Tuple[str, str]] = []
        for k in label_names:
            if k not in labels:
                raise ValueError(f"missing label: {k}")
            items.append((k, str(labels[k])))
        return tuple(items)

    def inc(self, name: str, *, by: float = 1.0, labels: Mapping[str, Any] | None = None) -> None:
        with self._lock:
            mdef = self._defs[name]
            key = self._labels_key(mdef.label_names, labels)
            cur = self._values[name].get(key, 0.0)
            self._values[name][key] = float(cur) + float(by)

    def set(self, name: str, *, value: float, labels: Mapping[str, Any] | None = None) -> None:
        with self._lock:
            mdef = self._defs[name]
            key = self._labels_key(mdef.label_names, labels)
            self._values[name][key] = float(value)

    def snapshot(self) -> Dict[str, Dict[Tuple[Tuple[str, str], ...], float]]:
        with self._lock:
            return {k: dict(v) for k, v in self._values.items()}

    def render_prometheus_text(self) -> str:
        """
        Render Prometheus exposition format v0.0.4.
        """
        with self._lock:
            lines: list[str] = []
            for name in sorted(self._defs.keys()):
                mdef = self._defs[name]
                if mdef.help:
                    lines.append(f"# HELP {mdef.name} {mdef.help}")
                lines.append(f"# TYPE {mdef.name} {mdef.mtype}")
                samples = self._values.get(name, {})
                # Deterministic label ordering for stable diffs.
                for label_tup in sorted(samples.keys()):
                    v = samples[label_tup]
                    lines.append(f"{mdef.name}{_format_labels(label_tup)} {v}")
            return "\n".join(lines) + "\n"


class Counter:
    def __init__(self, reg: MetricRegistry, *, name: str, help: str, label_names: Tuple[str, ...]) -> None:
        self._reg = reg
        self._name = name
        self._reg._ensure_def(_MetricDef(name=name, help=help, mtype="counter", label_names=label_names))

    def inc(self, by: float = 1.0, *, labels: Mapping[str, Any] | None = None) -> None:
        self._reg.inc(self._name, by=by, labels=labels)


class Gauge:
    def __init__(self, reg: MetricRegistry, *, name: str, help: str, label_names: Tuple[str, ...]) -> None:
        self._reg = reg
        self._name = name
        self._reg._ensure_def(_MetricDef(name=name, help=help, mtype="gauge", label_names=label_names))

    def set(self, value: float, *, labels: Mapping[str, Any] | None = None) -> None:
        self._reg.set(self._name, value=value, labels=labels)


# ---- Shared registry + required metric names ----

REGISTRY = MetricRegistry()

# ---- Generic in-process counters (no external deps) ----
#
# These are intentionally "institutional-grade minimal":
# - names match operational intent
# - labeled so multiple components/streams can share them
# - safe to use from async tasks and threads
messages_received_total = REGISTRY.counter(
    "messages_received_total",
    help="Total messages received from upstream connections, labeled by component and stream.",
    label_names=("component", "stream"),
)
messages_published_total = REGISTRY.counter(
    "messages_published_total",
    help="Total messages/events published to downstream destinations, labeled by component and stream.",
    label_names=("component", "stream"),
)
reconnect_attempts_total = REGISTRY.counter(
    "reconnect_attempts_total",
    help="Total reconnect attempts, labeled by component and stream.",
    label_names=("component", "stream"),
)

# Required metrics (keep names exactly as requested)
agent_start_total = REGISTRY.counter(
    "agent_start_total",
    help="Agent starts (process starts), labeled by component.",
    label_names=("component",),
)
heartbeat_age_seconds = REGISTRY.gauge(
    "heartbeat_age_seconds",
    help="Seconds since last marketdata tick/heartbeat was observed.",
)
marketdata_ticks_total = REGISTRY.counter(
    "marketdata_ticks_total",
    help="Total marketdata ticks/messages processed.",
)
marketdata_stale_total = REGISTRY.counter(
    "marketdata_stale_total",
    help="Count of transitions into marketdata-stale state.",
)
strategy_cycles_total = REGISTRY.counter(
    "strategy_cycles_total",
    help="Total strategy evaluation cycles performed.",
)
strategy_cycles_skipped_total = REGISTRY.counter(
    "strategy_cycles_skipped_total",
    help="Total strategy cycles skipped due to internal errors/conditions.",
)
order_proposals_total = REGISTRY.counter(
    "order_proposals_total",
    help="Total orders proposed by strategies (not necessarily executed).",
)
safety_halted_total = REGISTRY.counter(
    "safety_halted_total",
    help="Total safety halt events observed (e.g., kill switch engaged).",
)
errors_total = REGISTRY.counter(
    "errors_total",
    help="Total errors observed, labeled by component.",
    label_names=("component",),
)

# Ensure required metrics appear even before first increment.
# (Prometheus best practice: export zero-valued time series explicitly.)
try:
    # Unlabeled counters
    marketdata_ticks_total.inc(0.0)
    marketdata_stale_total.inc(0.0)
    # Gauges
    heartbeat_age_seconds.set(0.0)
    strategy_cycles_total.inc(0.0)
    strategy_cycles_skipped_total.inc(0.0)
    order_proposals_total.inc(0.0)
    safety_halted_total.inc(0.0)

    # Labeled counters: pre-seed common components
    for c in ("marketdata-mcp-server", "strategy-engine"):
        agent_start_total.inc(0.0, labels={"component": c})
        errors_total.inc(0.0, labels={"component": c})
except Exception:
    # Metrics should never block service import/startup, but don't fail silently.
    logger.exception("ops_metrics.metric_preseed_failed")
    pass


# ---- Runtime state for heartbeat/age + status ----

_state_lock = threading.RLock()
_last_activity_epoch_s: Dict[str, float] = {}
_last_marketdata_stale: bool = False


def mark_activity(component: str, *, at_epoch_s: float | None = None) -> None:
    """
    Mark the component as having done useful work "now" (or at a provided timestamp).
    Used to compute heartbeat_age_seconds for marketdata and freshness for /ops/status.
    """
    ts = float(at_epoch_s if at_epoch_s is not None else _now_s())
    with _state_lock:
        _last_activity_epoch_s[str(component)] = ts


def activity_age_seconds(component: str, *, now_epoch_s: float | None = None) -> float | None:
    now = float(now_epoch_s if now_epoch_s is not None else _now_s())
    with _state_lock:
        last = _last_activity_epoch_s.get(str(component))
    if last is None:
        return None
    return max(0.0, now - float(last))


def update_marketdata_heartbeat_metrics(*, stale_threshold_s: float) -> Dict[str, Any]:
    """
    Update heartbeat_age_seconds and stale transition counter based on the
    current marketdata activity age. Returns a small dict for status endpoints.
    """
    global _last_marketdata_stale
    age = activity_age_seconds("marketdata")
    age_s = float(age) if age is not None else float("inf")

    heartbeat_age_seconds.set(age_s if age is not None else float("inf"))

    is_stale = bool(age is None or age_s > float(stale_threshold_s))
    with _state_lock:
        prev = _last_marketdata_stale
        _last_marketdata_stale = is_stale
    if is_stale and not prev:
        marketdata_stale_total.inc(1.0)
        # Emit a structured log once per transition for optional log-based metrics.
        try:
            from backend.common.ops_log import log_json

            log_json(
                intent_type="marketdata_stale_transition",
                severity="WARNING",
                reason_codes=["marketdata_stale"],
                heartbeat_age_seconds=None if age is None else age_s,
                stale_threshold_seconds=float(stale_threshold_s),
            )
        except Exception:
            # Never let logging break metrics.
            pass

    return {
        "age_seconds": None if age is None else age_s,
        "stale_threshold_seconds": float(stale_threshold_s),
        "is_stale": is_stale,
        "last_observed_epoch_s": None if age is None else (_now_s() - age_s),
    }

