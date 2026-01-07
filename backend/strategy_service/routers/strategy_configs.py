from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from backend.strategies.registry.loader import load_all_configs
from backend.strategies.registry.models import StrategyConfig, StrategyMode
from backend.strategies.registry.validator import compute_effective_mode


class StrategyConfigWithEffectiveMode(StrategyConfig):
    effective_mode: StrategyMode


router = APIRouter(prefix="/strategies/configs", tags=["strategy-configs"])


def _get_cached_configs(request: Request) -> list[StrategyConfig]:
    # Best-effort caching; fallback to direct load.
    rows = getattr(request.app.state, "strategy_config_registry", None)
    if rows is None:
        rows = load_all_configs()
        request.app.state.strategy_config_registry = rows
    return rows


@router.get("", response_model=list[StrategyConfigWithEffectiveMode])
def list_strategy_configs(request: Request) -> list[StrategyConfigWithEffectiveMode]:
    rows = _get_cached_configs(request)
    return [
        StrategyConfigWithEffectiveMode(
            **cfg.model_dump(), effective_mode=compute_effective_mode(cfg)
        )
        for cfg in rows
    ]


@router.get("/{strategy_id}", response_model=StrategyConfigWithEffectiveMode)
def get_strategy_config(strategy_id: str, request: Request) -> StrategyConfigWithEffectiveMode:
    rows = _get_cached_configs(request)
    for cfg in rows:
        if cfg.strategy_id == strategy_id:
            return StrategyConfigWithEffectiveMode(
                **cfg.model_dump(), effective_mode=compute_effective_mode(cfg)
            )
    raise HTTPException(status_code=404, detail="strategy_id_not_found")

