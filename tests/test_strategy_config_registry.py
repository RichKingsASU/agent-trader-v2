import os

import pytest

from backend.strategies.registry.loader import load_all_configs
from backend.strategies.registry.models import StrategyConfig, StrategyMode
from backend.strategies.registry.validator import compute_effective_mode


def _write(p, text: str) -> None:
    p.write_text(text, encoding="utf-8")


def test_valid_config_loads_defaults(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "strategies"
    cfg_dir.mkdir(parents=True)
    _write(
        cfg_dir / "example.yaml",
        """
strategy_id: example
strategy_name: Example
strategy_type: rsi
enabled: true
mode: EVAL_ONLY
parameters:
  foo: 1
""".lstrip(),
    )
    monkeypatch.setenv("STRATEGY_CONFIG_DIR", str(cfg_dir))
    monkeypatch.delenv("STRATEGY_SYMBOL_ALLOWLIST", raising=False)

    rows = load_all_configs()
    assert len(rows) == 1
    assert rows[0].strategy_id == "example"
    # defaults
    assert rows[0].symbols == ["SPY", "IWM"]
    assert rows[0].enabled is True
    assert rows[0].mode == StrategyMode.EVAL_ONLY


def test_invalid_config_fails_safe_non_jsonable_parameters(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "strategies"
    cfg_dir.mkdir(parents=True)
    _write(
        cfg_dir / "bad.yaml",
        """
strategy_id: bad
strategy_name: Bad
strategy_type: rsi
enabled: true
mode: EVAL_ONLY
parameters:
  bad_timestamp: !!timestamp 2020-01-01
""".lstrip(),
    )
    monkeypatch.setenv("STRATEGY_CONFIG_DIR", str(cfg_dir))

    with pytest.raises(ValueError, match="parameters must be JSON-serializable"):
        load_all_configs()


def test_duplicate_strategy_id_fails(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "strategies"
    cfg_dir.mkdir(parents=True)
    _write(
        cfg_dir / "a.yaml",
        """
strategy_id: dup
strategy_name: A
strategy_type: gamma
""".lstrip(),
    )
    _write(
        cfg_dir / "b.yaml",
        """
strategy_id: dup
strategy_name: B
strategy_type: whale
""".lstrip(),
    )
    monkeypatch.setenv("STRATEGY_CONFIG_DIR", str(cfg_dir))

    with pytest.raises(ValueError, match="duplicate strategy_id"):
        load_all_configs()


def test_effective_mode_respects_agent_mode(monkeypatch):
    cfg = StrategyConfig(
        strategy_id="x",
        strategy_name="X",
        strategy_type="gamma",
        enabled=True,
        mode=StrategyMode.PROPOSE_ONLY,
    )

    monkeypatch.setenv("AGENT_MODE", "DISABLED")
    assert compute_effective_mode(cfg) == StrategyMode.EVAL_ONLY

    monkeypatch.setenv("AGENT_MODE", "LIVE")
    assert compute_effective_mode(cfg) == StrategyMode.PROPOSE_ONLY


def test_effective_mode_execute_gated_by_allow_flag(monkeypatch):
    cfg = StrategyConfig(
        strategy_id="x",
        strategy_name="X",
        strategy_type="gamma",
        enabled=True,
        mode=StrategyMode.EXECUTE,
    )

    monkeypatch.setenv("AGENT_MODE", "LIVE")
    monkeypatch.delenv("ALLOW_STRATEGY_EXECUTION", raising=False)
    assert compute_effective_mode(cfg) == StrategyMode.PROPOSE_ONLY

    monkeypatch.setenv("ALLOW_STRATEGY_EXECUTION", "true")
    assert compute_effective_mode(cfg) == StrategyMode.EXECUTE

