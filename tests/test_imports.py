from __future__ import annotations

import importlib
import threading


def test_import_backend_ingestion_config() -> None:
    importlib.import_module("backend.ingestion.config")


def test_import_backend_ingestion_publisher() -> None:
    importlib.import_module("backend.ingestion.publisher")


def test_import_cloudrun_ingestor_main_exposes_app(monkeypatch) -> None:
    # cloudrun_ingestor/main.py validates env on import; provide dummy values.
    monkeypatch.setenv("GCP_PROJECT", "dummy")
    monkeypatch.setenv("SYSTEM_EVENTS_TOPIC", "dummy")
    monkeypatch.setenv("MARKET_TICKS_TOPIC", "dummy")
    monkeypatch.setenv("MARKET_BARS_1M_TOPIC", "dummy")
    monkeypatch.setenv("TRADE_SIGNALS_TOPIC", "dummy")
    monkeypatch.setenv("INGEST_FLAG_SECRET_ID", "dummy")

    # Ensure importing the module doesn't start background work during tests/CI.
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)

    try:
        m = importlib.import_module("cloudrun_ingestor.main")
    except ModuleNotFoundError as e:
        # cloudrun_ingestor hard-depends on google-cloud-pubsub at import time.
        if str(e).startswith("No module named 'google'"):
            import pytest

            pytest.xfail("cloudrun_ingestor requires google-cloud-pubsub dependency for importability")
        raise
    assert hasattr(m, "app")

