from __future__ import annotations

import json
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from backend.contracts.v2.execution import ExecutionAttempt, ExecutionResult
from backend.contracts.v2.explainability import StrategyExplanation
from backend.contracts.v2.risk import RiskDecision
from backend.contracts.v2.shadow import ShadowTrade
from backend.contracts.v2.trading import OrderIntent, TradingSignal
from backend.contracts.v2.types import CONTRACT_VERSION_V2


def _repo_root() -> Path:
    # backend/contracts/v2/generate_json_schemas.py -> backend/contracts/v2 -> backend/contracts -> backend -> repo root
    return Path(__file__).resolve().parents[3]


MODELS: dict[str, Type[BaseModel]] = {
    "trading_signal": TradingSignal,
    "order_intent": OrderIntent,
    "shadow_trade": ShadowTrade,
    "risk_decision": RiskDecision,
    "execution_attempt": ExecutionAttempt,
    "execution_result": ExecutionResult,
    "strategy_explanation": StrategyExplanation,
}


def main() -> None:
    out_dir = _repo_root() / "backend" / "contracts" / "schemas" / "v2"
    out_dir.mkdir(parents=True, exist_ok=True)

    for name, model in MODELS.items():
        schema = model.model_json_schema(mode="serialization")
        schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        schema["$id"] = f"agenttrader.v2/{name}.v{CONTRACT_VERSION_V2}.schema.json"
        schema["title"] = f"AgentTrader v2 - {model.__name__}"

        path = out_dir / f"{name}.v{CONTRACT_VERSION_V2}.schema.json"
        path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

