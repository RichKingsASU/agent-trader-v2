#!/usr/bin/env python3
"""
Replay timeline generator from AgentTrader logs.

Inputs:
- One or more log files (plain text, or .gz)
- Or stdin (e.g., `kubectl logs ... | scripts/replay_from_logs.py`)

It scans lines for JSON objects and extracts:
- Native replay events: {"replay_schema":"agenttrader.replay.v1", ...}
- (Optional) Strategy microVM protocol order intents: {"protocol":"v1","type":"order_intent", ...}

Output:
- A grouped markdown timeline (grouped by trace_id + agent_name).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple


REPLAY_SCHEMA = "agenttrader.replay.v1"


def _parse_iso(ts: str) -> Optional[datetime]:
    try:
        s = str(ts).strip()
        if not s:
            return None
        # Handle common Z suffix
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _format_ts(dt: Optional[datetime], fallback: str = "") -> str:
    if dt is None:
        return fallback
    return dt.astimezone(timezone.utc).isoformat()


def _open_text_stream(path: Path) -> io.TextIOBase:
    if str(path).endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def _iter_input_lines(paths: Sequence[str]) -> Iterator[Tuple[str, str]]:
    """
    Yields (source_label, line).
    """
    if not paths:
        for ln in sys.stdin:
            yield ("stdin", ln)
        return

    for p in paths:
        path = Path(p)
        with _open_text_stream(path) as f:
            for ln in f:
                yield (str(path), ln)


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
        return None
    except Exception:
        return None


def _extract_json_from_line(line: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort extraction of a JSON object embedded in a log line.
    """
    line = line.strip()
    if not line:
        return None

    # Fast path: whole line is a JSON object
    obj = _try_parse_json(line)
    if obj is not None:
        return obj

    # Common path: logging prefix + JSON payload as message
    if "{" not in line or "}" not in line:
        return None

    starts = [i for i, ch in enumerate(line) if ch == "{"]
    end = line.rfind("}")
    if end <= 0:
        return None

    for s in starts:
        if s >= end:
            continue
        cand = line[s : end + 1]
        obj = _try_parse_json(cand)
        if obj is not None:
            return obj
    return None


def _summarize_event(ev: Dict[str, Any]) -> str:
    et = str(ev.get("event") or "")
    data = ev.get("data") or {}
    if not isinstance(data, dict):
        data = {}

    if et == "startup":
        service = data.get("service") or data.get("runner") or ""
        component = ev.get("component") or ""
        bits = [b for b in [service, component] if b]
        return " / ".join(map(str, bits)) if bits else "startup"

    if et == "state_transition":
        fs = data.get("from_state")
        ts = data.get("to_state")
        reason = data.get("reason")
        s = ""
        if fs or ts:
            s = f"{fs or '?'} → {ts or '?'}"
        if reason:
            if s:
                s += f" ({reason})"
            else:
                s = str(reason)
        return s or "state_transition"

    if et == "decision_checkpoint":
        cp = data.get("checkpoint") or ""
        allowed = data.get("allowed")
        should_execute = data.get("should_execute")
        reason = data.get("reason")
        parts: List[str] = []
        if cp:
            parts.append(str(cp))
        if allowed is not None:
            parts.append(f"allowed={allowed}")
        if should_execute is not None:
            parts.append(f"should_execute={should_execute}")
        if reason:
            parts.append(str(reason))
        return " - ".join(parts) or "decision_checkpoint"

    if et == "order_intent":
        stage = data.get("stage") or ""
        intent = data.get("intent")
        if isinstance(intent, dict):
            sym = intent.get("symbol")
            side = intent.get("side")
            qty = intent.get("qty")
            ot = intent.get("order_type")
            bits = [b for b in [stage, sym, side, qty, ot] if b is not None and b != ""]
            return " ".join(map(str, bits)) if bits else "order_intent"
        sym = data.get("symbol")
        side = data.get("side")
        qty = data.get("qty")
        bits = [b for b in [stage, sym, side, qty] if b is not None and b != ""]
        return " ".join(map(str, bits)) if bits else "order_intent"

    return et or "event"


@dataclass(frozen=True)
class TimelineEvent:
    idx: int
    source: str
    raw: Dict[str, Any]
    ts: Optional[datetime]
    trace_id: str
    agent_name: str
    event_type: str
    summary: str


def _as_replay_event(
    *, obj: Dict[str, Any], source: str, idx: int, include_protocol_intents: bool
) -> Optional[TimelineEvent]:
    # Native replay schema
    if obj.get("replay_schema") == REPLAY_SCHEMA:
        trace_id = str(obj.get("trace_id") or "").strip()
        agent_name = str(obj.get("agent_name") or "").strip()
        if not trace_id or not agent_name:
            return None
        event_type = str(obj.get("event") or "").strip() or "event"
        ts = _parse_iso(str(obj.get("ts") or "").strip())
        summary = _summarize_event(obj)
        return TimelineEvent(
            idx=idx,
            source=source,
            raw=obj,
            ts=ts,
            trace_id=trace_id,
            agent_name=agent_name,
            event_type=event_type,
            summary=summary,
        )

    # Optional: protocol order intents (microVM NDJSON)
    if include_protocol_intents and obj.get("protocol") == "v1" and obj.get("type") == "order_intent":
        trace_id = str(obj.get("event_id") or obj.get("intent_id") or "").strip()
        if not trace_id:
            return None
        agent_name = "strategy"
        ts = _parse_iso(str(obj.get("ts") or "").strip())
        wrapped = {
            "replay_schema": REPLAY_SCHEMA,
            "ts": str(obj.get("ts") or "") or None,
            "event": "order_intent",
            "trace_id": trace_id,
            "agent_name": agent_name,
            "component": "strategy_runner.protocol",
            "data": {"stage": "protocol", "intent": obj},
        }
        summary = _summarize_event(wrapped)
        return TimelineEvent(
            idx=idx,
            source=source,
            raw=wrapped,
            ts=ts,
            trace_id=trace_id,
            agent_name=agent_name,
            event_type="order_intent",
            summary=summary,
        )

    return None


def _group_key(ev: TimelineEvent) -> Tuple[str, str]:
    return (ev.trace_id, ev.agent_name)


def _render_markdown(
    *,
    events: Sequence[TimelineEvent],
    sources: Sequence[str],
    verbose: bool,
) -> str:
    now = datetime.now(tz=timezone.utc).isoformat()
    out: List[str] = []
    out.append("# Replay timeline")
    out.append("")
    out.append(f"- Generated: `{now}`")
    if sources:
        out.append(f"- Sources: `{', '.join(sources)}`")
    out.append(f"- Events: `{len(events)}`")
    out.append("")

    groups: Dict[Tuple[str, str], List[TimelineEvent]] = {}
    for ev in events:
        groups.setdefault(_group_key(ev), []).append(ev)

    out.append(f"## Groups ({len(groups)})")
    out.append("")

    def _md_escape_cell(s: str) -> str:
        # Minimal escaping for markdown tables
        return str(s).replace("|", "\\|").replace("\n", " ").strip()

    def _sort_key(e: TimelineEvent) -> Tuple[int, int]:
        # Prefer timestamp; fall back to read order.
        if e.ts is None:
            return (1, e.idx)
        return (0, int(e.ts.timestamp() * 1000))

    for (trace_id, agent_name), group_events in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        group_sorted = sorted(group_events, key=_sort_key)
        first_ts = next((e.ts for e in group_sorted if e.ts is not None), None)
        last_ts = next((e.ts for e in reversed(group_sorted) if e.ts is not None), None)
        out.append(f"### trace_id=`{trace_id}` agent=`{agent_name}`")
        out.append("")
        if first_ts or last_ts:
            out.append(f"- First: `{_format_ts(first_ts)}`")
            out.append(f"- Last: `{_format_ts(last_ts)}`")
            out.append("")

        out.append("| time (UTC) | event | summary | source |")
        out.append("|---|---|---|---|")
        for e in group_sorted:
            t = _format_ts(e.ts, fallback=str(e.raw.get("ts") or ""))
            out.append(
                f"| `{_md_escape_cell(t)}` | `{_md_escape_cell(e.event_type)}` | {_md_escape_cell(e.summary)} | `{_md_escape_cell(e.source)}` |"
            )
        out.append("")

        if verbose:
            out.append("<details><summary>Raw events</summary>")
            out.append("")
            for e in group_sorted:
                out.append(f"- `{_format_ts(e.ts, fallback=str(e.raw.get('ts') or ''))}` `{e.event_type}`")
                out.append("")
                out.append("```json")
                out.append(json.dumps(e.raw, indent=2, ensure_ascii=False))
                out.append("```")
                out.append("")
            out.append("</details>")
            out.append("")

    return "\n".join(out) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Generate a markdown replay timeline from logs.")
    p.add_argument(
        "inputs",
        nargs="*",
        help="Log files to read (plain text or .gz). If omitted, reads stdin.",
    )
    p.add_argument(
        "-o",
        "--output",
        default="-",
        help="Output path for markdown (default: stdout).",
    )
    p.add_argument(
        "--include-protocol-intents",
        action="store_true",
        help="Also parse microVM protocol order_intent messages (protocol=v1).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Include raw event JSON (sanitized if emitted that way) under each group.",
    )
    args = p.parse_args(list(argv) if argv is not None else None)

    events: List[TimelineEvent] = []
    idx = 0
    sources_seen: List[str] = []
    for source, line in _iter_input_lines(args.inputs):
        idx += 1
        if source not in sources_seen:
            sources_seen.append(source)
        obj = _extract_json_from_line(line)
        if obj is None:
            continue
        ev = _as_replay_event(
            obj=obj,
            source=source,
            idx=idx,
            include_protocol_intents=bool(args.include_protocol_intents),
        )
        if ev is not None:
            events.append(ev)

    md = _render_markdown(events=events, sources=sources_seen, verbose=bool(args.verbose))

    if args.output == "-" or args.output.strip() == "":
        sys.stdout.write(md)
        return 0

    out_path = Path(args.output)
    out_path.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

