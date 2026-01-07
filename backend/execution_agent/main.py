from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.common.agent_boot import configure_startup_logging
from backend.common.kill_switch import get_kill_switch_state
from backend.execution_agent.gating import enforce_startup_gate_or_exit
from backend.trading.execution.decider import decide_execution
from backend.trading.execution.models import SafetySnapshot

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _bool_env_exact(name: str) -> bool | None:
    """
    Strict boolean parser:
    - "true" => True
    - "false" => False
    - anything else/missing => None
    """
    v = os.getenv(name)
    if v is None:
        return None
    s = str(v).strip()
    if s == "true":
        return True
    if s == "false":
        return False
    return None


def _int_env(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return int(default)
    return int(v)


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except Exception:
        return None


def build_safety_snapshot(*, now: datetime | None = None) -> SafetySnapshot:
    now_dt = (now or _utc_now()).astimezone(timezone.utc)
    kill, _source = get_kill_switch_state()

    last_ts = _parse_iso_dt(os.getenv("MARKETDATA_LAST_TS_UTC"))
    stale_threshold_s = _int_env("MARKETDATA_STALE_THRESHOLD_S", 120)
    marketdata_fresh = bool(last_ts) and ((now_dt - last_ts).total_seconds() <= float(stale_threshold_s))

    return SafetySnapshot(
        kill_switch=bool(kill),
        marketdata_fresh=bool(marketdata_fresh),
        marketdata_last_ts=last_ts.isoformat() if last_ts else None,
        agent_mode=str(os.getenv("AGENT_MODE") or "").strip() or "UNKNOWN",
    )


def _json_log(event: dict[str, Any]) -> None:
    print(json.dumps(event, separators=(",", ":"), ensure_ascii=False), flush=True)


def _decision_output_path(*, base_dir: Path, now: datetime) -> Path:
    date_dir = now.astimezone(timezone.utc).date().isoformat()
    return base_dir / date_dir / "decisions.ndjson"


def load_prior_decision_ids_today(*, decisions_path: Path) -> set[str]:
    """
    Best-effort only: seed a set of proposal_ids already written today.

    This allows a restart to reprocess proposals while logging duplicate_seen=true.
    """
    prior: set[str] = set()
    try:
        if not decisions_path.exists():
            return prior
        # Read line-by-line to bound memory.
        with decisions_path.open("r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = json.loads(s)
                    pid = str(obj.get("proposal_id") or "").strip()
                    if pid:
                        prior.add(pid)
                except Exception:
                    continue
    except Exception:
        return prior
    return prior


def append_decision_ndjson(*, decisions_path: Path, decision_obj: dict[str, Any]) -> bool:
    """
    Append one decision as NDJSON. Returns True if written to filesystem.
    """
    try:
        decisions_path.parent.mkdir(parents=True, exist_ok=True)
        with decisions_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(decision_obj, separators=(",", ":"), ensure_ascii=False))
            f.write("\n")
        return True
    except Exception:
        return False


def iter_ndjson_follow(*, path: Path, start_at_end: bool, poll_interval_s: float) -> Iterable[dict[str, Any]]:
    """
    Follow an NDJSON file and yield parsed objects.
    """
    with path.open("r", encoding="utf-8") as f:
        if start_at_end:
            f.seek(0, os.SEEK_END)

        while True:
            line = f.readline()
            if not line:
                time.sleep(poll_interval_s)
                continue
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception:
                _json_log(
                    {
                        "ts": _utc_now().isoformat(),
                        "intent_type": "proposal_parse_error",
                        "error": "invalid_json",
                    }
                )
                continue
            if isinstance(obj, dict):
                yield obj
            else:
                _json_log(
                    {
                        "ts": _utc_now().isoformat(),
                        "intent_type": "proposal_parse_error",
                        "error": "not_object",
                    }
                )


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    # Absolute safety boundary: refuse to start unless the hard gate passes.
    enforce_startup_gate_or_exit()

    configure_startup_logging(
        agent_name="execution-agent",
        intent="consume_proposals_emit_execution_decisions_no_orders",
    )

    proposals_path_raw = str(os.getenv("PROPOSALS_PATH") or "").strip()
    if not proposals_path_raw:
        _json_log(
            {
                "ts": _utc_now().isoformat(),
                "intent_type": "startup_refused",
                "reason_codes": ["PROPOSALS_PATH_missing"],
            }
        )
        raise SystemExit(2)

    proposals_path = Path(proposals_path_raw)
    if not proposals_path.exists():
        _json_log(
            {
                "ts": _utc_now().isoformat(),
                "intent_type": "startup_refused",
                "reason_codes": ["PROPOSALS_PATH_not_found"],
                "proposals_path": proposals_path_raw,
            }
        )
        raise SystemExit(2)

    base_dir = Path(str(os.getenv("DECISIONS_BASE_DIR") or "audit_artifacts/execution_decisions").strip())
    now0 = _utc_now()
    decisions_path = _decision_output_path(base_dir=base_dir, now=now0)
    prior_ids_today = load_prior_decision_ids_today(decisions_path=decisions_path)
    processed_ids: set[str] = set()

    start_at_end = (str(os.getenv("PROPOSALS_START_AT") or "end").strip().lower() == "end")
    poll_interval_s = float(os.getenv("PROPOSALS_POLL_INTERVAL_S") or "0.25")

    _json_log(
        {
            "ts": now0.isoformat(),
            "intent_type": "execution_agent_started",
            "proposals_path": str(proposals_path),
            "follow_start_at": "end" if start_at_end else "beginning",
            "decisions_path": str(decisions_path),
            "dedupe_seeded_from_today_artifacts": True,
            "prior_decision_ids_today": len(prior_ids_today),
        }
    )

    agent_name = str(os.getenv("AGENT_NAME") or "execution-agent").strip() or "execution-agent"
    agent_role = str(os.getenv("AGENT_ROLE") or "execution").strip() or "execution"

    for proposal in iter_ndjson_follow(path=proposals_path, start_at_end=start_at_end, poll_interval_s=poll_interval_s):
        proposal_id = str(proposal.get("proposal_id") or proposal.get("id") or "").strip() or "missing_proposal_id"

        if proposal_id in processed_ids:
            _json_log(
                {
                    "ts": _utc_now().isoformat(),
                    "intent_type": "proposal_duplicate_seen",
                    "proposal_id": proposal_id,
                    "duplicate_seen": True,
                    "dedupe_scope": "in_memory",
                }
            )
            continue
        processed_ids.add(proposal_id)

        duplicate_seen = proposal_id in prior_ids_today
        safety = build_safety_snapshot()
        decision = decide_execution(
            proposal=proposal,
            safety=safety,
            agent_name=agent_name,
            agent_role=agent_role,
        )
        decision_obj = decision.to_dict()

        # Emit intent log (always).
        _json_log(
            {
                "ts": _utc_now().isoformat(),
                "intent_type": "execution_decision",
                "decision_id": decision_obj.get("decision_id"),
                "proposal_id": decision_obj.get("proposal_id"),
                "decision": decision_obj.get("decision"),
                "reason_codes": decision_obj.get("reject_reason_codes") or [],
                "duplicate_seen": bool(duplicate_seen),
            }
        )

        written = append_decision_ndjson(decisions_path=decisions_path, decision_obj=decision_obj)
        if not written:
            # FS not writable: emit full decision to stdout as fallback.
            _json_log(
                {
                    "ts": _utc_now().isoformat(),
                    "intent_type": "decision_output_fallback_stdout",
                    "decision": decision_obj,
                }
            )


if __name__ == "__main__":
    main()

