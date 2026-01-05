from __future__ import annotations

from pathlib import Path


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def test_frontend_no_global_collection_or_doc_calls() -> None:
    """
    Tenant data must be queried via tenant-scoped helpers, not top-level collections.

    This is a lightweight guardrail (not a substitute for Firestore rules).
    """
    root = Path(__file__).resolve().parents[1]
    src = root / "frontend" / "src"
    assert src.exists(), f"missing frontend src at {src}"

    allow = {str(src / "lib" / "tenancy" / "firestore.ts")}
    bad: list[str] = []

    for p in list(src.rglob("*.ts")) + list(src.rglob("*.tsx")):
        if str(p) in allow:
            continue
        t = _read_text(p)
        if "collection(db," in t or "doc(db," in t:
            bad.append(str(p.relative_to(root)))

    assert not bad, "Found non-tenant-scoped Firestore calls:\n" + "\n".join(sorted(bad))


def test_backend_services_do_not_use_global_tenant_collections() -> None:
    """
    Strategy + risk services must not access tenant-owned collections at top-level.
    """
    root = Path(__file__).resolve().parents[1]

    # Only scan these services (other directories contain ingestion/system writers).
    service_dirs = [
        root / "backend" / "strategy_service",
        root / "backend" / "risk_service",
    ]
    for d in service_dirs:
        assert d.exists(), f"missing service dir: {d}"

    tenant_owned_collections = {
        "strategies",
        "broker_accounts",
        "paper_orders",
        "risk_limits",
        "profiles",
        "trades",
        "paper_trades",
        "system",
        "system_logs",
        "system_commands",
        "accounts",
        "live_quotes",
        "news_events",
        "market_data_1m",
        "alpaca_option_snapshots",
        "portfolio_performance",
        "ops",
        "ops_heartbeats",
    }

    bad: list[str] = []
    for service_dir in service_dirs:
        for p in service_dir.rglob("*.py"):
            t = _read_text(p)
            for col in tenant_owned_collections:
                if f'.collection("{col}")' in t or f".collection('{col}')" in t:
                    bad.append(f"{p.relative_to(root)} -> {col}")

    assert not bad, "Found top-level tenant-owned collection usage:\n" + "\n".join(sorted(bad))

