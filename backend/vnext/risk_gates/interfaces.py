"""
vNEXT Risk Gates — Interfaces (Governance-first)

Risk gates are *policy controls* that can modify or block automated decisions.

Governance invariants (see `backend/vnext/GOVERNANCE.md`):
- Gates never place trades (OBSERVE-only): they emit data-only recommendations.
- Gates never override humans: a human decision is always authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable


class GateAction(str, Enum):
    """
    What a gate recommends for an *automated* decision.

    Notes:
    - `BLOCK` means "block automation" (humans may still proceed).
    - `REDUCE` means "scale down risk" (e.g., size, leverage, exposure).
    """

    ALLOW = "allow"
    REDUCE = "reduce"
    BLOCK = "block"


@dataclass(frozen=True, slots=True)
class GateTrigger:
    """
    One concrete gate activation (auditable, data-only).

    Fields are intentionally generic so triggers can be logged / persisted
    without requiring runtime dependencies.
    """

    gate_id: str
    action: GateAction
    reason_code: str
    message: str

    # Optional severity label to support governance/auditing.
    severity: str = "info"

    # Optional structured evidence for explainability.
    metadata: Mapping[str, Any] = field(default_factory=dict)

    # If action == REDUCE, this can specify a multiplicative reduction factor
    # in (0, 1]. The final factor is composed conservatively across triggers.
    reduction_factor: float | None = None


@dataclass(frozen=True, slots=True)
class RiskGateEvaluation:
    """
    Aggregate evaluation across a set of risk gates.

    Governance-first semantics:
    - `recommended_action` is what automation should do.
    - If `human_authority` is True, gates are *advisory only*:
      - `enforced_action` is always `ALLOW` (humans are never overridden).
      - `recommended_action` still reflects what gates would have enforced
        for automation, for transparency and auditability.
    """

    enforced_action: GateAction
    recommended_action: GateAction
    triggers: tuple[GateTrigger, ...]

    # Multiplicative factor in (0, 1] when recommended_action is REDUCE.
    recommended_reduction_factor: float | None = None

    # True when the caller indicates a human is the decision authority.
    human_authority: bool = False


@runtime_checkable
class RiskGate(Protocol):
    """
    Risk gate interface.

    Implementations MUST be pure evaluation:
    - no order placement
    - no external side effects
    - deterministic given `context`
    """

    gate_id: str

    def evaluate(self, context: Mapping[str, Any]) -> Sequence[GateTrigger]:
        """
        Return zero or more triggers.

        Implementations should:
        - return an empty sequence when not triggered
        - be defensive: never raise; return a BLOCK trigger if safety requires
        """


def evaluate_risk_gates(
    context: Mapping[str, Any],
    gates: Sequence[RiskGate] | None = None,
) -> RiskGateEvaluation:
    """
    Evaluate all provided gates and conservatively combine their outputs.

    Combination rules (governance-first):
    - Any `BLOCK` trigger => recommended_action = BLOCK
    - Else any `REDUCE` trigger => recommended_action = REDUCE
      - reduction factor is the minimum valid factor across triggers
    - Else => recommended_action = ALLOW

    Human authority rule:
    - If `context.get("decision_authority") == "human"`, then enforced_action is
      always `ALLOW` regardless of triggers (gates are advisory only).
    """

    gates = gates or ()

    decision_authority = str(context.get("decision_authority", "automation")).strip().lower()
    human_authority = decision_authority == "human"

    triggers: list[GateTrigger] = []
    for gate in gates:
        try:
            for t in gate.evaluate(context):
                triggers.append(t)
        except Exception as e:  # governance-first: fail safe, never fail open
            triggers.append(
                GateTrigger(
                    gate_id=getattr(gate, "gate_id", gate.__class__.__name__),
                    action=GateAction.BLOCK,
                    reason_code="gate_evaluation_error",
                    message="Risk gate evaluation raised; blocking automation fail-safe.",
                    severity="critical",
                    metadata={"error_type": type(e).__name__},
                )
            )

    recommended_action = GateAction.ALLOW
    if any(t.action == GateAction.BLOCK for t in triggers):
        recommended_action = GateAction.BLOCK
    elif any(t.action == GateAction.REDUCE for t in triggers):
        recommended_action = GateAction.REDUCE

    reduction_factors: list[float] = []
    for t in triggers:
        if t.action != GateAction.REDUCE:
            continue
        if t.reduction_factor is None:
            continue
        try:
            f = float(t.reduction_factor)
        except Exception:
            continue
        if 0.0 < f <= 1.0:
            reduction_factors.append(f)

    recommended_reduction_factor: float | None = None
    if recommended_action == GateAction.REDUCE and reduction_factors:
        recommended_reduction_factor = min(reduction_factors)

    enforced_action = GateAction.ALLOW if human_authority else recommended_action

    return RiskGateEvaluation(
        enforced_action=enforced_action,
        recommended_action=recommended_action,
        triggers=tuple(triggers),
        recommended_reduction_factor=recommended_reduction_factor,
        human_authority=human_authority,
    )

