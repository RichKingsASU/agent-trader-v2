"""
Options Observer — READ-ONLY explanation module

Goal:
- Explain, for the most recent recorded option plan/intent, *why* it was created,
  *which contract* was selected, and *whether execution succeeded* based on
  already-recorded artifacts and/or captured stdout logs.

Safety guarantees (absolute):
- READ-ONLY: only reads local files (audit artifacts and optional log files).
- NO broker calls: does not import broker SDKs or call external trading APIs.
- NO execution logic: does not place orders, size orders, or trigger execution flows.
- NO writes: never writes to the filesystem.

Primary entrypoint:
  explain_last_option_trade(...) -> ExplanationRecord
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from backend.trading.proposals.models import OrderProposal, ProposalAssetType


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _try_parse_json(text: str) -> Optional[dict[str, Any]]:
    s = (text or "").strip()
    if not s:
        return None
    try:
        obj = json.loads(s)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _extract_json_from_line(line: str) -> Optional[dict[str, Any]]:
    """
    Best-effort extraction of a JSON object embedded in a log line.
    Mirrors the behavior used in `scripts/replay_from_logs.py` (simplified).
    """
    line = (line or "").strip()
    if not line or "{" not in line or "}" not in line:
        return _try_parse_json(line)
    obj = _try_parse_json(line)
    if obj is not None:
        return obj
    end = line.rfind("}")
    starts = [m.start() for m in re.finditer(r"\{", line)]
    for s in starts:
        if s >= end:
            continue
        cand = line[s : end + 1]
        obj = _try_parse_json(cand)
        if obj is not None:
            return obj
    return None


def _iter_ndjson(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for ln in f:
                obj = _try_parse_json(ln)
                if obj is not None:
                    yield obj
    except Exception:
        return


def _candidate_paths(audit_dir: Path, *, rel_globs: Sequence[str]) -> list[Path]:
    out: list[Path] = []
    for g in rel_globs:
        try:
            out.extend(sorted(audit_dir.glob(g)))
        except Exception:
            continue
    # De-dupe while preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        uniq.append(p)
    return uniq


def _latest_by_mtime(paths: Sequence[Path]) -> Optional[Path]:
    best: Optional[Path] = None
    best_mtime = -1.0
    for p in paths:
        try:
            if not p.exists() or not p.is_file():
                continue
            mt = p.stat().st_mtime
            if mt > best_mtime:
                best_mtime = mt
                best = p
        except Exception:
            continue
    return best


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


@dataclass(frozen=True)
class ContractSelection:
    underlying_symbol: str
    expiration: str | None = None  # YYYY-MM-DD
    right: str | None = None  # CALL|PUT
    strike: float | None = None
    contract_symbol: str | None = None


@dataclass(frozen=True)
class ExecutionEvidence:
    decision: str  # APPROVE|REJECT|UNKNOWN
    decided_at_utc: str | None = None
    decision_id: str | None = None
    reject_reason_codes: tuple[str, ...] = field(default_factory=tuple)
    notes: str | None = None
    source: str | None = None  # filepath or "stdout"


@dataclass(frozen=True)
class ExplanationRecord:
    # Plan identity
    plan_id: str | None
    correlation_id: str | None
    created_at_utc: str | None
    strategy_name: str | None
    agent_name: str | None

    # Contract & intent
    underlying_symbol: str | None
    selected_contract: ContractSelection | None
    side: str | None
    quantity: int | None
    limit_price: float | None
    time_in_force: str | None

    # Why this plan exists
    why: str | None
    key_factors: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    # Execution outcome (from artifacts/logs)
    execution_succeeded: bool | None = None
    execution: ExecutionEvidence = field(default_factory=lambda: ExecutionEvidence(decision="UNKNOWN"))

    # Provenance
    sources: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "correlation_id": self.correlation_id,
            "created_at_utc": self.created_at_utc,
            "strategy_name": self.strategy_name,
            "agent_name": self.agent_name,
            "underlying_symbol": self.underlying_symbol,
            "selected_contract": None
            if self.selected_contract is None
            else {
                "underlying_symbol": self.selected_contract.underlying_symbol,
                "expiration": self.selected_contract.expiration,
                "right": self.selected_contract.right,
                "strike": self.selected_contract.strike,
                "contract_symbol": self.selected_contract.contract_symbol,
            },
            "side": self.side,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force,
            "why": self.why,
            "key_factors": list(self.key_factors),
            "execution_succeeded": self.execution_succeeded,
            "execution": {
                "decision": self.execution.decision,
                "decided_at_utc": self.execution.decided_at_utc,
                "decision_id": self.execution.decision_id,
                "reject_reason_codes": list(self.execution.reject_reason_codes),
                "notes": self.execution.notes,
                "source": self.execution.source,
            },
            "sources": list(self.sources),
        }

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append("Options Observer Explanation")
        lines.append("")
        if self.plan_id:
            lines.append(f"- plan_id: {self.plan_id}")
        if self.correlation_id:
            lines.append(f"- correlation_id: {self.correlation_id}")
        if self.created_at_utc:
            lines.append(f"- created_at_utc: {self.created_at_utc}")
        if self.strategy_name:
            lines.append(f"- strategy_name: {self.strategy_name}")
        if self.agent_name:
            lines.append(f"- agent_name: {self.agent_name}")
        if self.underlying_symbol:
            lines.append(f"- underlying: {self.underlying_symbol}")
        lines.append("")

        lines.append("Why the plan was created")
        lines.append(f"- why: {self.why or 'unknown (missing rationale in artifacts)'}")
        if self.key_factors:
            lines.append("- key_factors:")
            for kf in self.key_factors[:10]:
                name = _as_str(kf.get("name")) or _as_str(kf.get("key")) or "factor"
                val = kf.get("value")
                weight = kf.get("weight")
                extra = []
                if val is not None:
                    extra.append(f"value={val}")
                if weight is not None:
                    extra.append(f"weight={weight}")
                lines.append(f"  - {name}" + (f" ({', '.join(map(str, extra))})" if extra else ""))
            if len(self.key_factors) > 10:
                lines.append(f"  - ... ({len(self.key_factors) - 10} more)")
        lines.append("")

        lines.append("What contract was selected")
        if self.selected_contract is None:
            lines.append("- selected_contract: unknown (no option fields found in plan)")
        else:
            c = self.selected_contract
            parts = [c.underlying_symbol]
            if c.expiration:
                parts.append(c.expiration)
            if c.right:
                parts.append(c.right)
            if c.strike is not None:
                parts.append(str(c.strike))
            if c.contract_symbol:
                parts.append(f"({c.contract_symbol})")
            lines.append(f"- selected_contract: {' '.join(parts)}")
        lines.append("")

        lines.append("Whether execution succeeded (from artifacts/logs)")
        if self.execution_succeeded is True:
            lines.append("- execution_succeeded: true")
        elif self.execution_succeeded is False:
            lines.append("- execution_succeeded: false")
        else:
            lines.append("- execution_succeeded: unknown (no decision/result evidence found)")

        lines.append(f"- execution_decision: {self.execution.decision}")
        if self.execution.reject_reason_codes:
            lines.append(f"- reject_reason_codes: {', '.join(self.execution.reject_reason_codes)}")
        if self.execution.notes:
            lines.append(f"- notes: {self.execution.notes}")
        if self.execution.source:
            lines.append(f"- evidence_source: {self.execution.source}")
        if self.sources:
            lines.append(f"- sources: {', '.join(self.sources)}")
        return "\n".join(lines).rstrip() + "\n"


def _coerce_key_factors_from_indicators(indicators: Any) -> tuple[dict[str, Any], ...]:
    """
    Convert an indicators dict (or list) into a stable key_factors list.
    We keep values short and safe; the emitter already redacts known secret keys.
    """
    if indicators is None:
        return tuple()
    if isinstance(indicators, list):
        out = []
        for x in indicators:
            if isinstance(x, dict) and x:
                out.append(dict(x))
        return tuple(out)
    if isinstance(indicators, dict):
        out = []
        # Prefer a human-friendly subset if present.
        for k in ("signal", "thesis", "regime", "trend", "flow", "gex", "iv", "delta", "gamma"):
            if k in indicators:
                out.append({"name": k, "value": indicators.get(k)})
        # Otherwise include top keys (bounded).
        if not out:
            for k in list(indicators.keys())[:12]:
                out.append({"name": str(k), "value": indicators.get(k)})
        return tuple(out)
    return tuple()


def _parse_plan_as_order_proposal(plan: Mapping[str, Any]) -> Optional[OrderProposal]:
    try:
        return OrderProposal.model_validate(dict(plan))
    except Exception:
        return None


def _extract_contract_from_plan(*, underlying: str | None, plan: Mapping[str, Any], parsed: OrderProposal | None) -> ContractSelection | None:
    if parsed is not None and parsed.option is not None:
        opt = parsed.option
        return ContractSelection(
            underlying_symbol=str(parsed.symbol),
            expiration=opt.expiration.isoformat(),
            right=str(opt.right.value),
            strike=float(opt.strike),
            contract_symbol=opt.contract_symbol,
        )

    # Generic extraction for "OptionTradePlan" variants.
    opt = plan.get("option") if isinstance(plan.get("option"), dict) else None
    if opt is None:
        opt = plan.get("contract") if isinstance(plan.get("contract"), dict) else None
    if not isinstance(opt, dict):
        return ContractSelection(underlying_symbol=str(underlying)) if underlying else None

    expiration = _as_str(opt.get("expiration") or opt.get("expiry") or opt.get("exp"))
    right = _as_str(opt.get("right") or opt.get("type") or opt.get("cp"))
    strike = opt.get("strike")
    try:
        strike_f = float(strike) if strike is not None else None
    except Exception:
        strike_f = None
    contract_symbol = _as_str(opt.get("contract_symbol") or opt.get("symbol") or opt.get("occ_symbol"))
    if not underlying:
        underlying = _as_str(plan.get("symbol") or plan.get("underlying") or opt.get("underlying_symbol") or opt.get("underlying"))
    return ContractSelection(
        underlying_symbol=str(underlying) if underlying else "UNKNOWN",
        expiration=expiration,
        right=right.upper() if right else None,
        strike=strike_f,
        contract_symbol=contract_symbol,
    )


def _pick_last_option_proposal_from_artifacts(audit_dir: Path) -> tuple[Optional[OrderProposal], Optional[Path]]:
    candidates = _candidate_paths(
        audit_dir,
        rel_globs=(
            "proposals/*/proposals.ndjson",
            "proposals.ndjson",
        ),
    )
    # Try the newest file first.
    ordered = sorted(candidates, key=lambda p: (p.stat().st_mtime if p.exists() else 0.0), reverse=True)
    for path in ordered:
        last: Optional[OrderProposal] = None
        try:
            for obj in _iter_ndjson(path):
                p = _parse_plan_as_order_proposal(obj)
                if p is None:
                    continue
                if p.asset_type != ProposalAssetType.OPTION:
                    continue
                # Best-effort: treat it as an "option plan" even if option fields are absent.
                last = p
        except Exception:
            last = None
        if last is not None:
            return last, path
    return None, None


def _pick_last_execution_decision_for_proposal(audit_dir: Path, *, proposal_id: str, correlation_id: str | None) -> tuple[Optional[dict[str, Any]], Optional[Path]]:
    candidates = _candidate_paths(
        audit_dir,
        rel_globs=(
            "execution_decisions/*/decisions.ndjson",
            "execution_decisions/decisions.ndjson",
        ),
    )
    ordered = sorted(candidates, key=lambda p: (p.stat().st_mtime if p.exists() else 0.0), reverse=True)
    best_obj: Optional[dict[str, Any]] = None
    best_path: Optional[Path] = None
    best_ts = -1.0

    for path in ordered:
        for obj in _iter_ndjson(path):
            pid = _as_str(obj.get("proposal_id"))
            cid = _as_str(obj.get("correlation_id"))
            if pid != proposal_id and not (correlation_id and cid == correlation_id):
                continue
            dt = _parse_iso_dt(obj.get("decided_at_utc") or obj.get("decided_at") or obj.get("ts"))
            ts = dt.timestamp() if dt is not None else path.stat().st_mtime
            if ts >= best_ts:
                best_ts = ts
                best_obj = obj
                best_path = path
        if best_obj is not None:
            # Since files are ordered newest-first, this is typically sufficient.
            break
    return best_obj, best_path


def _search_stdout_logs_for_evidence(
    *,
    log_paths: Sequence[Path],
    proposal_id: str | None,
    correlation_id: str | None,
) -> Optional[dict[str, Any]]:
    """
    Look for execution-agent emitted JSON logs that can be used as evidence when
    artifact files are missing.
    """
    if not log_paths:
        return None
    for p in log_paths:
        try:
            if not p.exists() or not p.is_file():
                continue
        except Exception:
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for ln in f:
                    obj = _extract_json_from_line(ln)
                    if obj is None:
                        continue
                    it = _as_str(obj.get("intent_type") or obj.get("event_type"))
                    if it not in {"execution_decision", "decision_output_fallback_stdout"}:
                        continue
                    # execution_decision log lines include proposal_id; fallback wraps decision object.
                    if it == "execution_decision":
                        pid = _as_str(obj.get("proposal_id"))
                        cid = _as_str(obj.get("correlation_id"))
                        if proposal_id and pid == proposal_id:
                            return obj
                        if correlation_id and cid == correlation_id:
                            return obj
                    if it == "decision_output_fallback_stdout":
                        dec = obj.get("decision")
                        if isinstance(dec, dict):
                            pid = _as_str(dec.get("proposal_id"))
                            cid = _as_str(dec.get("correlation_id"))
                            if proposal_id and pid == proposal_id:
                                return dec
                            if correlation_id and cid == correlation_id:
                                return dec
        except Exception:
            continue
    return None


def explain_option_trade_plan(
    *,
    plan: Mapping[str, Any],
    audit_dir: Path = Path("audit_artifacts"),
    stdout_log_paths: Sequence[Path] = (),
) -> ExplanationRecord:
    """
    Explain a provided OptionTradePlan-like JSON object.
    """
    parsed = _parse_plan_as_order_proposal(plan)

    plan_id = _as_str(plan.get("proposal_id") or plan.get("plan_id") or plan.get("id") or (getattr(parsed, "proposal_id", None)))
    correlation_id = _as_str(plan.get("correlation_id") or plan.get("correlationId") or (getattr(parsed, "correlation_id", None)))
    created_at = _parse_iso_dt(plan.get("created_at_utc") or plan.get("created_at") or plan.get("ts") or (getattr(parsed, "created_at_utc", None)))

    strategy_name = _as_str(plan.get("strategy_name") or plan.get("strategy") or (getattr(parsed, "strategy_name", None)))
    agent_name = _as_str(plan.get("agent_name") or plan.get("agent") or (getattr(parsed, "agent_name", None)))
    symbol = _as_str(plan.get("symbol") or plan.get("underlying") or (getattr(parsed, "symbol", None)))

    why = None
    indicators = None
    if parsed is not None:
        why = parsed.rationale.short_reason
        indicators = parsed.rationale.indicators
    else:
        rat = plan.get("rationale")
        if isinstance(rat, dict):
            why = _as_str(rat.get("short_reason") or rat.get("reason") or rat.get("why"))
            indicators = rat.get("indicators")
        why = why or _as_str(plan.get("why") or plan.get("reason"))

    key_factors = _coerce_key_factors_from_indicators(indicators)

    selected_contract = _extract_contract_from_plan(underlying=symbol, plan=plan, parsed=parsed)

    side = None
    quantity = None
    limit_price = None
    tif = None
    if parsed is not None:
        side = parsed.side.value
        quantity = int(parsed.quantity)
        limit_price = float(parsed.limit_price) if parsed.limit_price is not None else None
        tif = parsed.time_in_force.value
    else:
        side = _as_str(plan.get("side") or plan.get("action"))
        try:
            quantity = int(plan.get("quantity")) if plan.get("quantity") is not None else None
        except Exception:
            quantity = None
        try:
            limit_price = float(plan.get("limit_price")) if plan.get("limit_price") is not None else None
        except Exception:
            limit_price = None
        tif = _as_str(plan.get("time_in_force") or plan.get("tif"))

    # Execution evidence
    evidence_obj = None
    evidence_src = None
    decision_obj, decision_path = (None, None)
    if plan_id:
        decision_obj, decision_path = _pick_last_execution_decision_for_proposal(
            audit_dir, proposal_id=plan_id, correlation_id=correlation_id
        )
        if decision_obj is not None and decision_path is not None:
            evidence_obj = decision_obj
            evidence_src = str(decision_path)
    if evidence_obj is None:
        ev = _search_stdout_logs_for_evidence(
            log_paths=list(stdout_log_paths),
            proposal_id=plan_id,
            correlation_id=correlation_id,
        )
        if ev is not None:
            evidence_obj = ev
            evidence_src = "stdout_logs"

    decision = "UNKNOWN"
    decided_at_utc = None
    decision_id = None
    reject_reason_codes: tuple[str, ...] = tuple()
    notes = None
    succeeded: bool | None = None

    if isinstance(evidence_obj, dict) and evidence_obj:
        decision = str(evidence_obj.get("decision") or "UNKNOWN").upper()
        decided_at_utc = _as_str(evidence_obj.get("decided_at_utc") or evidence_obj.get("decided_at") or evidence_obj.get("ts"))
        decision_id = _as_str(evidence_obj.get("decision_id") or evidence_obj.get("id"))
        rrc = evidence_obj.get("reject_reason_codes") or evidence_obj.get("reason_codes") or evidence_obj.get("reasons") or []
        if isinstance(rrc, list):
            reject_reason_codes = tuple(str(x) for x in rrc if str(x).strip())
        notes = _as_str(evidence_obj.get("notes") or evidence_obj.get("message"))
        if decision in {"APPROVE", "REJECT"}:
            succeeded = decision == "APPROVE"

    sources: list[str] = []
    if decision_path is not None:
        sources.append(str(decision_path))

    return ExplanationRecord(
        plan_id=plan_id,
        correlation_id=correlation_id,
        created_at_utc=created_at.isoformat() if created_at else None,
        strategy_name=strategy_name,
        agent_name=agent_name,
        underlying_symbol=symbol,
        selected_contract=selected_contract,
        side=side,
        quantity=quantity,
        limit_price=limit_price,
        time_in_force=tif,
        why=why,
        key_factors=key_factors,
        execution_succeeded=succeeded,
        execution=ExecutionEvidence(
            decision=decision,
            decided_at_utc=decided_at_utc,
            decision_id=decision_id,
            reject_reason_codes=reject_reason_codes,
            notes=notes,
            source=evidence_src,
        ),
        sources=tuple(sources),
    )


def explain_last_option_trade(
    *,
    audit_dir: Path = Path("audit_artifacts"),
    stdout_log_paths: Sequence[Path] = (),
) -> ExplanationRecord:
    """
    Find the most recent option proposal in local audit artifacts and explain it.
    """
    proposal, proposal_path = _pick_last_option_proposal_from_artifacts(audit_dir)
    if proposal is None:
        # Stable empty shape
        return ExplanationRecord(
            plan_id=None,
            correlation_id=None,
            created_at_utc=None,
            strategy_name=None,
            agent_name=None,
            underlying_symbol=None,
            selected_contract=None,
            side=None,
            quantity=None,
            limit_price=None,
            time_in_force=None,
            why=None,
            key_factors=tuple(),
            execution_succeeded=None,
            execution=ExecutionEvidence(decision="UNKNOWN", source=None),
            sources=tuple([str(proposal_path)]) if proposal_path else tuple(),
        )

    raw = proposal.model_dump(mode="json")  # type: ignore[attr-defined]
    rec = explain_option_trade_plan(plan=raw, audit_dir=audit_dir, stdout_log_paths=stdout_log_paths)
    srcs = list(rec.sources)
    if proposal_path is not None:
        srcs.append(str(proposal_path))
    # De-dupe
    seen: set[str] = set()
    uniq = tuple([s for s in srcs if not (s in seen or seen.add(s))])
    return ExplanationRecord(
        plan_id=rec.plan_id,
        correlation_id=rec.correlation_id,
        created_at_utc=rec.created_at_utc,
        strategy_name=rec.strategy_name,
        agent_name=rec.agent_name,
        underlying_symbol=rec.underlying_symbol,
        selected_contract=rec.selected_contract,
        side=rec.side,
        quantity=rec.quantity,
        limit_price=rec.limit_price,
        time_in_force=rec.time_in_force,
        why=rec.why,
        key_factors=rec.key_factors,
        execution_succeeded=rec.execution_succeeded,
        execution=rec.execution,
        sources=uniq,
    )

