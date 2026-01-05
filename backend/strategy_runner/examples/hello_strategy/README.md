## Hello Strategy (sandbox example)

This folder represents what a tenant uploads (strategy code + optional files).

### Contract

- **Entrypoint**: `strategy.py` (packaged as `user_strategy.py` in the bundle)
- **Handler**: `on_market_event(event: dict) -> list[dict] | dict | None`
- **Input**: one market event JSON object (see `backend/strategy_runner/protocol.py`)
- **Output**: zero or more order intent JSON objects (same protocol)

### Local sandbox run (requires Firecracker assets)

See `backend/strategy_runner/harness.py`.

