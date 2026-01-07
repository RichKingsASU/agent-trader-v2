# vNEXT Module Boundaries (Isolation & Imports)

This document defines **module boundary rules** for vNEXT to keep modules **isolated**, **mockable**, and safe to evolve independently.

These rules complement (do not replace) `backend/vnext/GOVERNANCE.md`.

---

## Definitions

- **vNEXT module**: A top-level package under `backend/vnext/<module_name>/`.
- **Public surface**: The *only* cross-module API of a vNEXT module, defined in `backend/vnext/<module_name>/interfaces.py` (and optionally re-exported from that module’s `__init__.py`).
- **Internal implementation**: Any file other than `interfaces.py` inside a module. Internal code is private to that module.

---

## Boundary invariant (the rule everything else supports)

**A vNEXT module may depend on other vNEXT modules via `interfaces.py` only.**

No module is allowed to import another module’s internal implementation, even “temporarily”.

---

## Allowed imports

### Within the same module

- **Allowed**: Any import within your own module.
  - Example: `from backend.vnext.risk_gates.foo import Bar`

### Cross-module (vNEXT → vNEXT)

- **Allowed**: Importing another module’s **public surface** only:
  - `from backend.vnext.<other_module>.interfaces import ...`
  - Optionally: `from backend.vnext.<other_module> import ...` **only if** `<other_module>/__init__.py` re-exports symbols from `interfaces.py` and does not introduce additional dependencies.

### Outside vNEXT (vNEXT → non-vNEXT)

- **Allowed**: Pure utility / foundation code that does not create domain coupling and does not introduce live dependencies, for example:
  - Python stdlib
  - Typing utilities (`typing`, `dataclasses`, `enum`, `datetime`, etc.)
  - **Small, stable “platform” helpers** that are not strategy/execution/business-logic specific

TODO(enforcement): Define an explicit allowlist of non-vNEXT packages vNEXT may import (and enforce it in CI).

---

## Forbidden dependencies

### Cross-module (vNEXT → vNEXT) internal imports

- **Forbidden**: Importing anything other than another module’s `interfaces.py`.
  - Bad: `from backend.vnext.macro_events.provider_impl import TradingEconomicsProvider`
  - Bad: `from backend.vnext.risk_gates.internal import combine_gate_outputs`

### Execution coupling (vNEXT → execution/brokers/order routing)

vNEXT must remain **analysis/observation-first** and must not structurally couple to execution systems.

- **Forbidden** (examples, non-exhaustive):
  - `backend.execution.*`
  - `backend.execution_agent.*`
  - `backend.brokers.*` (including Alpaca SDK wrappers)
  - `backend.trading.*`
  - Any “place order / cancel order / route order” client libraries

### Strategy/runtime coupling (vNEXT → strategy engines / live trading loops)

- **Forbidden** (examples, non-exhaustive):
  - `backend.strategy_engine.*`
  - `backend.strategy_runner.*`
  - `backend.strategies.*`
  - `backend.strategy_service.*`

### Live dependency coupling (networked clients as default imports)

- **Forbidden by default**:
  - Direct production DB clients, queue clients, or live market data clients in core module codepaths
  - Module-level side effects that initialize network connections on import

TODO(enforcement): Add a static check that flags imports of known execution/strategy packages from any `backend/vnext/**` file.

---

## How modules communicate (interfaces only)

### 1) Define contracts in `interfaces.py`

Each module exposes:

- **Data contracts** (immutable dataclasses / pydantic models where appropriate)
- **Protocols** (e.g., provider/client/sink interfaces)
- **Pure functions** that operate only on contract types (optional; keep them dependency-free)

Rule: `interfaces.py` must stay **dependency-light** and **safe to import** (no I/O, no heavy imports, no side effects).

### 2) Consumers depend on contracts, not implementations

The consuming module:

- Imports only `backend.vnext.<provider>.interfaces`
- Uses dependency injection (constructor args / function args) to accept implementations of Protocols
- Produces **data-only outputs** (proposals, alerts, triggers), never imperative execution actions

### 3) Implementations live outside vNEXT (adapter layer)

Concrete implementations that perform I/O (HTTP, DB, queues, live market data) must live **outside** `backend/vnext/` and implement vNEXT Protocols.

This keeps vNEXT modules:

- Easy to test (swap in fakes)
- Deterministic (no implicit network calls)
- Not coupled to deployment/runtime topology

TODO(enforcement): Establish a canonical adapter location (e.g., `backend/adapters/vnext_<module>/...`) and add a template for new module wiring.

---

## Practical import rules (copy/paste for PR review)

- **vNEXT module public surface** is `backend/vnext/<module>/interfaces.py` (and optional re-exports).
- **Cross-module imports** must target `interfaces.py` only.
- **No imports** from execution, broker, or strategy runtime packages inside `backend/vnext/**`.
- **No I/O on import**; no network clients created at module import time.

TODO(enforcement): Add an “import boundary” CI job (e.g., import-linter/ruff custom rule) that fails builds when these rules are violated.

---

## Examples

### ✅ Good: interfaces-only dependency

```python
from backend.vnext.macro_events.interfaces import MacroEventProvider
```

### ❌ Bad: implementation dependency

```python
from backend.vnext.macro_events.provider_impl import TradingEconomicsProvider
```

### ✅ Good: adapter outside vNEXT implements vNEXT Protocol

```python
from backend.vnext.macro_events.interfaces import MacroEventProvider

class MyProvider(MacroEventProvider):
    ...
```

---

## TODOs (future tooling)

- TODO(enforcement): CI rule to restrict cross-module imports to `interfaces.py`.
- TODO(enforcement): CI rule to ban imports of known execution/strategy/broker packages from `backend/vnext/**`.
- TODO(enforcement): Optional “module graph” report artifact (DOT/JSON) for PRs touching vNEXT.
- TODO(enforcement): Pre-commit hook to run boundary checks locally.

