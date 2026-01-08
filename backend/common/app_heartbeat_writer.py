from __future__ import annotations

import json
import os
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

try:
    # Only used for type hints; avoid hard dependency at runtime.
    from fastapi import FastAPI  # type: ignore
except Exception:  # pragma: no cover
    FastAPI = object  # type: ignore


HEARTBEAT_PREFIX = "HEARTBEAT:"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return default
    s = str(v).strip()
    return s if s != "" else default


def _float_env(name: str, default: float) -> float:
    raw = _env(name)
    if raw is None:
        return float(default)
    try:
        return float(raw)
    except Exception:
        return float(default)


def _read_first_line(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            line = f.readline()
        s = (line or "").strip()
        return s if s else None
    except Exception:
        return None


def _incluster_namespace() -> Optional[str]:
    # Standard k8s serviceaccount namespace file.
    return _read_first_line("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


def _incluster_token() -> Optional[str]:
    return _read_first_line("/var/run/secrets/kubernetes.io/serviceaccount/token")


def _incluster_ca_cert_path() -> Optional[str]:
    p = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    return p if os.path.isfile(p) else None


@dataclass(frozen=True, slots=True)
class K8sConfigMapTarget:
    namespace: str
    name: str
    key: str = "last_seen"


def _k8s_api_base() -> str:
    host = _env("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = _env("KUBERNETES_SERVICE_PORT", "443")
    return f"https://{host}:{port}"


def _patch_configmap_key(*, target: K8sConfigMapTarget, value: str, timeout_s: float = 5.0) -> None:
    token = _incluster_token()
    if not token:
        raise RuntimeError("k8s-configmap heartbeat requires in-cluster serviceaccount token")

    url = f"{_k8s_api_base()}/api/v1/namespaces/{target.namespace}/configmaps/{target.name}"
    body = json.dumps({"data": {target.key: value}}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(url, data=body, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/merge-patch+json")
    req.add_header("Accept", "application/json")

    ca_path = _incluster_ca_cert_path()
    ctx = ssl.create_default_context(cafile=ca_path) if ca_path else ssl.create_default_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as res:
            code = int(getattr(res, "status", 0) or 0)
            if code < 200 or code >= 300:
                raise RuntimeError(f"unexpected status {code} patching ConfigMap {target.namespace}/{target.name}")
    except urllib.error.HTTPError as e:
        # Preserve body for debugging if present (bounded).
        try:
            body_text = (e.read() or b"").decode("utf-8", errors="ignore")[:2000]
        except Exception:
            body_text = ""
        raise RuntimeError(
            f"failed to patch ConfigMap {target.namespace}/{target.name} ({e.code}): {body_text or e.reason}"
        ) from e


def _default_service_name() -> str:
    return (
        str(_env("SERVICE_NAME") or _env("AGENT_NAME") or _env("K_SERVICE") or _env("HOSTNAME") or "service")
        .strip()
        .lower()
    )


def _resolve_configmap_target() -> K8sConfigMapTarget:
    name = _env("HEARTBEAT_CONFIGMAP_NAME")
    if not name:
        raise RuntimeError("HEARTBEAT_CONFIGMAP_NAME is required when HEARTBEAT_MODE=k8s-configmap")

    ns = _env("HEARTBEAT_CONFIGMAP_NAMESPACE") or _env("POD_NAMESPACE") or _incluster_namespace() or "default"
    key = _env("HEARTBEAT_CONFIGMAP_KEY", "last_seen") or "last_seen"
    return K8sConfigMapTarget(namespace=ns, name=name, key=key)


def _heartbeat_thread(
    *,
    stop: threading.Event,
    mode: str,
    interval_s: float,
    service_name: str,
) -> None:
    interval_s = max(1.0, float(interval_s))
    last_err_log = 0.0
    err_log_min_interval_s = float(_float_env("HEARTBEAT_ERROR_LOG_MIN_INTERVAL_S", 300.0))

    target: Optional[K8sConfigMapTarget] = None
    if mode == "k8s-configmap":
        target = _resolve_configmap_target()

    while not stop.is_set():
        ts = _utcnow_iso()
        try:
            if mode == "stdout":
                env = _env("ENVIRONMENT") or _env("ENV") or _env("APP_ENV") or _env("DEPLOY_ENV") or "unknown"
                # Required format: HEARTBEAT: ts=<iso>
                sys.stdout.write(f"{HEARTBEAT_PREFIX} ts={ts} service={service_name} env={env}\n")
                try:
                    sys.stdout.flush()
                except Exception:
                    pass
            elif mode == "k8s-configmap":
                assert target is not None
                _patch_configmap_key(target=target, value=ts)
            else:
                return
        except Exception as e:  # pragma: no cover
            now = time.monotonic()
            if (now - last_err_log) >= err_log_min_interval_s:
                last_err_log = now
                env = _env("ENVIRONMENT") or _env("ENV") or _env("APP_ENV") or _env("DEPLOY_ENV") or "unknown"
                sys.stdout.write(
                    f"HEARTBEAT_ERROR: mode={mode} service={service_name} env={env} err={type(e).__name__}: {e}\n"
                )
                try:
                    sys.stdout.flush()
                except Exception:
                    pass

        # Sleep in small increments so shutdown is responsive.
        deadline = time.monotonic() + interval_s
        while not stop.is_set() and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.05, deadline - time.monotonic())))


@dataclass(frozen=True, slots=True)
class HeartbeatHandle:
    stop: threading.Event
    thread: threading.Thread


def start_heartbeat_background(
    *,
    mode: Optional[str] = None,
    interval_s: Optional[float] = None,
    service_name: Optional[str] = None,
) -> Optional[HeartbeatHandle]:
    """
    Start the heartbeat writer in a daemon thread.

    Returns a handle to stop/join, or None if disabled/invalid config.
    """
    m = str(mode or (_env("HEARTBEAT_MODE") or "")).strip()
    if not m:
        return None
    if m not in {"stdout", "k8s-configmap"}:
        env = _env("ENVIRONMENT") or _env("ENV") or _env("APP_ENV") or _env("DEPLOY_ENV") or "unknown"
        try:
            sys.stdout.write(f"HEARTBEAT_DISABLED: unknown mode={m} env={env}\n")
            try:
                sys.stdout.flush()
            except Exception:
                pass
        except Exception:
            pass
        return None

    itv = float(interval_s if interval_s is not None else _float_env("HEARTBEAT_INTERVAL_SECONDS", 30.0))
    svc = (service_name or _default_service_name()).strip() or _default_service_name()

    stop = threading.Event()
    t = threading.Thread(
        target=_heartbeat_thread,
        name=f"heartbeat-writer-{svc}",
        daemon=True,
        kwargs={"stop": stop, "mode": m, "interval_s": float(itv), "service_name": svc},
    )
    t.start()
    return HeartbeatHandle(stop=stop, thread=t)


def stop_heartbeat_background(handle: Optional[HeartbeatHandle]) -> None:
    if handle is None:
        return
    try:
        handle.stop.set()
    except Exception:
        pass
    try:
        handle.thread.join(timeout=2.0)
    except Exception:
        pass


def install_app_heartbeat(app: FastAPI, *, service_name: Optional[str] = None) -> None:
    """
    Optional app-level heartbeat writer.

    Enable with:
    - HEARTBEAT_MODE=stdout          -> logs "HEARTBEAT: ts=<iso> ..." every 30s
    - HEARTBEAT_MODE=k8s-configmap   -> patches ConfigMap .data.last_seen every 30s

    k8s-configmap mode env vars:
    - HEARTBEAT_CONFIGMAP_NAME (required)
    - HEARTBEAT_CONFIGMAP_NAMESPACE (optional; defaults to in-cluster namespace)
    - HEARTBEAT_CONFIGMAP_KEY (optional; default "last_seen")
    """

    def _startup() -> None:
        handle = start_heartbeat_background(service_name=service_name)
        if handle is None:
            return
        try:
            app.state._heartbeat_handle = handle  # type: ignore[attr-defined]
        except Exception:
            pass

    def _shutdown() -> None:
        try:
            handle = getattr(app.state, "_heartbeat_handle", None)
        except Exception:
            handle = None
        stop_heartbeat_background(handle)

    # Attach as additional lifecycle hooks without interfering with existing ones.
    try:
        app.add_event_handler("startup", _startup)
        app.add_event_handler("shutdown", _shutdown)
    except Exception:
        # If we're not running under FastAPI/Starlette, do nothing.
        return

