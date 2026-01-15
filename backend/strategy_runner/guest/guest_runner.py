#!/usr/bin/env python3
"""
Runs INSIDE the microVM.

Responsibilities:
- unpack the strategy bundle into an isolated directory
- import the user strategy entrypoint
- provide a strict NDJSON interface over vsock

The host must never import user code; only this guest process does.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import signal
import socket
import sys
import tarfile
import threading
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional


PROTOCOL_VERSION = "v1"
_SHUTDOWN_EVENT = threading.Event()


def _utc_now_iso() -> str:
    # Avoid importing datetime in guest hot path unnecessarily
    import datetime

    return datetime.datetime.now(tz=datetime.timezone.utc).isoformat()


def _log(level: str, message: str) -> Dict[str, Any]:
    return {
        "protocol": PROTOCOL_VERSION,
        "type": "log",
        "ts": _utc_now_iso(),
        "level": level,
        "message": message,
    }


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return float(default)
    try:
        return float(str(raw).strip())
    except Exception:
        return float(default)


def _parse_iso8601_utc(value: Any) -> Optional["datetime.datetime"]:
    """
    Best-effort parse for ISO8601 timestamps into tz-aware UTC datetime.

    Guest constraints:
    - stdlib only
    - tolerate both "...Z" and "+00:00" suffixes
    """
    import datetime

    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    # Normalize Zulu suffix for older Python versions.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        # Fail-closed-ish: assume UTC (callers will still enforce max-age).
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def _validate_event_timestamp(ts_raw: Any) -> tuple[bool, str]:
    """
    Enforce basic event timestamp safety:
    - must be parseable ISO8601
    - must not be too old (max age)
    - must not be too far in the future (clock skew)
    """
    import datetime

    max_age_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_AGE_SECONDS", 30.0))
    max_future_skew_s = max(0.0, _env_float("STRATEGY_EVENT_MAX_FUTURE_SKEW_SECONDS", 5.0))
    dt = _parse_iso8601_utc(ts_raw)
    if dt is None:
        return False, "invalid_ts"
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    age_s = (now - dt).total_seconds()
    # Too far in the future => reject (avoid trading on future-dated events).
    if age_s < -max_future_skew_s:
        return False, "future_ts"
    # Too old => reject.
    if age_s > max_age_s:
        return False, "stale_ts"
    return True, "ok"


class GuestFatal(RuntimeError):
    pass


def _safe_extract_tar(tar_path: Path, out_dir: Path) -> Dict[str, Any]:
    with tarfile.open(tar_path, "r:gz") as tf:
        # validate manifest first
        try:
            mf = tf.extractfile("manifest.json")
            if mf is None:
                raise GuestFatal("bundle missing manifest.json")
            manifest = json.loads(mf.read().decode("utf-8"))
        except KeyError:
            raise GuestFatal("bundle missing manifest.json")

        # prevent path traversal
        for m in tf.getmembers():
            name = m.name
            if name.startswith("/") or name.startswith("../") or "/../" in name:
                raise GuestFatal("bundle contains unsafe paths")

        tf.extractall(out_dir)
        return manifest


def _import_user_module(bundle_dir: Path, entrypoint: str) -> ModuleType:
    entry = bundle_dir / "strategy" / entrypoint
    if not entry.exists():
        raise GuestFatal(f"entrypoint not found in bundle: {entry}")

    spec = importlib.util.spec_from_file_location("user_strategy", str(entry))
    if spec is None or spec.loader is None:
        raise GuestFatal("failed to build module spec for user strategy")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


def _get_handler(mod: ModuleType) -> Callable[[Dict[str, Any]], Any]:
    fn = getattr(mod, "on_market_event", None)
    if fn is None or not callable(fn):
        raise GuestFatal("strategy must define callable: on_market_event(event: dict) -> list[dict] | dict | None")
    return fn  # type: ignore[return-value]


def _as_intents(obj: Any, event_id: str) -> List[Dict[str, Any]]:
    if obj is None:
        return []
    if isinstance(obj, dict):
        intents = [obj]
    elif isinstance(obj, list):
        intents = obj
    else:
        raise GuestFatal("strategy return must be dict | list[dict] | None")

    out: List[Dict[str, Any]] = []
    for i, it in enumerate(intents):
        if not isinstance(it, dict):
            raise GuestFatal("strategy intent must be object")
        # Minimal normalization: ensure protocol + type.
        it = dict(it)
        it.setdefault("protocol", PROTOCOL_VERSION)
        it.setdefault("type", "order_intent")
        it.setdefault("event_id", event_id)
        out.append(it)
    return out


def _read_ndjson_lines(f: io.BufferedReader) -> Iterable[Dict[str, Any]]:
    for raw in f:
        raw = raw.strip()
        if not raw:
            continue
        yield json.loads(raw.decode("utf-8"))


def _write_ndjson(f: io.BufferedWriter, objs: Iterable[Dict[str, Any]]) -> None:
    for o in objs:
        f.write(json.dumps(o, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        f.write(b"\n")
    f.flush()


def run_server(*, bundle_path: Path, port: int, work_dir: Path) -> int:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = _safe_extract_tar(bundle_path, work_dir)
    entrypoint = manifest.get("entrypoint")
    if not isinstance(entrypoint, str) or not entrypoint:
        raise GuestFatal("invalid manifest entrypoint")
    mod = _import_user_module(work_dir, entrypoint)
    handler = _get_handler(mod)

    # vsock server: CID is ignored for bind in guests; use VMADDR_CID_ANY (0xFFFFFFFF)
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)  # type: ignore[attr-defined]
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    # Make accept() interruptible so SIGTERM/SIGINT can stop the loop promptly.
    try:
        s.settimeout(1.0)
    except Exception:
        pass
    VMADDR_CID_ANY = 0xFFFFFFFF
    s.bind((VMADDR_CID_ANY, port))
    s.listen(1)

    def _handle_signal(_signum: int, _frame: Any | None = None) -> None:
        _SHUTDOWN_EVENT.set()

    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handle_signal)
            except Exception:
                pass

    accept_iter = 0
    while not _SHUTDOWN_EVENT.is_set():
        accept_iter += 1
        sys.stderr.write(f"guest_runner accept_loop_iteration={accept_iter}\n")
        try:
            conn, _addr = s.accept()
        except socket.timeout:
            continue
        except Exception as e:
            sys.stderr.write(f"guest_runner accept_error={type(e).__name__}: {e}\n")
            continue
        with conn:
            rf = conn.makefile("rb", buffering=0)
            wf = conn.makefile("wb", buffering=0)
            _write_ndjson(wf, [_log("info", f"guest ready (port={port})")])
            try:
                for msg in _read_ndjson_lines(rf):
                    if _SHUTDOWN_EVENT.is_set():
                        _write_ndjson(wf, [_log("info", "shutdown")])
                        return 0
                    if msg.get("protocol") != PROTOCOL_VERSION:
                        _write_ndjson(wf, [_log("error", "unsupported protocol")])
                        continue
                    t = msg.get("type")
                    if t == "shutdown":
                        _write_ndjson(wf, [_log("info", "shutdown")])
                        return 0
                    if t != "market_event":
                        _write_ndjson(wf, [_log("warn", f"ignoring unknown message type: {t}")])
                        continue

                    event_id = msg.get("event_id") or "unknown"
                    ok_ts, ts_reason = _validate_event_timestamp(msg.get("ts"))
                    if not ok_ts:
                        _write_ndjson(
                            wf,
                            [
                                _log(
                                    "warn",
                                    f"dropping market_event due to timestamp_validation_failed reason={ts_reason} event_id={event_id}",
                                )
                            ],
                        )
                        continue
                    try:
                        intents_obj = handler(msg)
                        intents = _as_intents(intents_obj, str(event_id))
                        _write_ndjson(wf, intents)
                    except Exception as e:  # user code error
                        tb = traceback.format_exc(limit=20)
                        _write_ndjson(
                            wf,
                            [
                                _log("error", f"strategy error: {e}"),
                                _log("debug", tb),
                            ],
                        )
            finally:
                try:
                    rf.close()
                except Exception:
                    pass
                try:
                    wf.close()
                except Exception:
                    pass

    return 0


def main() -> int:
    bundle_path = Path(os.getenv("AGENTTRADER_BUNDLE_PATH", "/mnt/strategy/bundle.tar.gz"))
    port = int(os.getenv("AGENTTRADER_VSOCK_PORT", "5005"))
    work_dir = Path(os.getenv("AGENTTRADER_WORK_DIR", "/tmp/agenttrader_strategy"))

    if not bundle_path.exists():
        sys.stderr.write(f"bundle not found: {bundle_path}\n")
        return 2

    try:
        return run_server(bundle_path=bundle_path, port=port, work_dir=work_dir)
    except GuestFatal as e:
        sys.stderr.write(f"guest fatal: {e}\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())

