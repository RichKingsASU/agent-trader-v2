from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Literal, Optional, Tuple

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

AGENT_KIND = Literal["marketdata", "strategy", "execution", "ingest"]
CRITICALITY = Literal["critical", "important", "optional"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


TRUTHY = {"1", "true", "yes", "on"}


def _is_truthy(value: object | None) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in TRUTHY


def _read_first_line(path: str) -> str:
    # Keep it small and safe: read only the first line.
    p = Path(path)
    data = p.read_text(encoding="utf-8", errors="ignore")
    return (data.splitlines()[0] if data else "").strip()


def get_kill_switch_state() -> Tuple[bool, Optional[str]]:
    """
    Read-only view of global kill switch state.

    Mirrors backend/common/kill_switch.py behavior:
    - EXECUTION_HALTED=1 (env) halts
    - EXECUTION_HALTED_FILE points to a file containing 1/0 (preferred in k8s)
    """
    if _is_truthy(os.getenv("EXECUTION_HALTED")):
        return True, "env:EXECUTION_HALTED"
    if _is_truthy(os.getenv("EXEC_KILL_SWITCH")):
        return True, "env:EXEC_KILL_SWITCH"

    file_path = (
        os.getenv("EXECUTION_HALTED_FILE")
        or os.getenv("EXEC_KILL_SWITCH_FILE")
        or "/etc/agenttrader/kill-switch/EXECUTION_HALTED"
    ).strip()
    if file_path:
        try:
            if Path(file_path).exists() and _is_truthy(_read_first_line(file_path)):
                return True, f"file:{file_path}"
        except Exception:
            # Fail-open for this read-only observer.
            return False, None

    return False, None


SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "secret",
    "token",
    "authorization",
    "password",
    "private_key",
    "firebase_key",
)


def _looks_sensitive_key(key: str) -> bool:
    k = str(key).strip().lower()
    return any(frag in k for frag in SENSITIVE_KEY_FRAGMENTS)


def redact(obj: Any, *, max_string_len: int = 2000) -> Any:
    """
    Best-effort redaction for arbitrary JSON-like structures.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _looks_sensitive_key(str(k)):
                out[str(k)] = "***REDACTED***"
            else:
                out[str(k)] = redact(v, max_string_len=max_string_len)
        return out
    if isinstance(obj, list):
        return [redact(v, max_string_len=max_string_len) for v in obj]
    if isinstance(obj, (int, float, bool)):
        return obj
    s = str(obj)
    if len(s) > max_string_len:
        return s[:max_string_len] + "...(truncated)"
    return s


class AgentConfig(BaseModel):
    agent_name: str = Field(..., min_length=1)
    service_dns: str = Field(..., min_length=1, description="Base URL, e.g. http://svc.ns.svc.cluster.local")
    kind: AGENT_KIND
    expected_endpoints: List[str] = Field(default_factory=list)
    criticality: CRITICALITY = "important"


class AgentsFile(BaseModel):
    agents: List[AgentConfig] = Field(default_factory=list)


@dataclass(frozen=True)
class EndpointResult:
    ok: bool
    status_code: Optional[int]
    latency_ms: Optional[int]
    error: Optional[str]


@dataclass
class AgentRuntimeStatus:
    agent_name: str
    service_dns: str
    kind: str
    criticality: str
    last_poll_at: Optional[datetime] = None
    online: Optional[bool] = None
    healthz: Optional[EndpointResult] = None
    ops_status: Optional[EndpointResult] = None
    heartbeat: Optional[EndpointResult] = None
    raw_ops_status_redacted: Optional[dict[str, Any]] = None
    marketdata_freshness: Optional[dict[str, Any]] = None


class EventBuffer:
    def __init__(self, *, maxlen: int = 500):
        self._buf: Deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = asyncio.Lock()

    async def append(self, event: dict[str, Any]) -> None:
        async with self._lock:
            self._buf.append(event)

    async def recent(self, *, limit: int = 50) -> list[dict[str, Any]]:
        async with self._lock:
            items = list(self._buf)
        items.reverse()  # newest first
        return items[:limit]


def load_agents_config(path: str) -> list[AgentConfig]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"agents config not found: {path}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    parsed = AgentsFile.model_validate(raw)
    # Deterministic ordering for API output
    return sorted(parsed.agents, key=lambda a: a.agent_name)


def _join(base: str, path: str) -> str:
    b = (base or "").rstrip("/")
    p = (path or "").strip()
    if not p.startswith("/"):
        p = "/" + p
    return b + p


async def _get_json_best_effort(res: httpx.Response) -> Optional[dict[str, Any]]:
    try:
        data = res.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else {"_value": data}


async def _check_endpoint(
    *,
    client: Any,
    url: str,
    timeout_s: float,
    headers: Optional[dict[str, str]] = None,
) -> tuple[EndpointResult, Optional[dict[str, Any]]]:
    t0 = time.monotonic()
    try:
        res = await client.get(url, timeout=timeout_s, headers=headers or {})
        latency_ms = int((time.monotonic() - t0) * 1000)
        ok = 200 <= int(res.status_code) < 300
        js = await _get_json_best_effort(res)
        return EndpointResult(ok=ok, status_code=int(res.status_code), latency_ms=latency_ms, error=None), js
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return EndpointResult(ok=False, status_code=None, latency_ms=latency_ms, error=str(e)), None


class MissionControlState:
    def __init__(self, *, agents: list[AgentConfig]):
        self.agents = agents
        self.status_by_agent: dict[str, AgentRuntimeStatus] = {
            a.agent_name: AgentRuntimeStatus(
                agent_name=a.agent_name,
                service_dns=a.service_dns,
                kind=a.kind,
                criticality=a.criticality,
            )
            for a in agents
        }
        self.events = EventBuffer(maxlen=int(os.getenv("EVENT_BUFFER_MAXLEN", "500")))
        self._status_lock = asyncio.Lock()
        self._poll_lock = asyncio.Lock()
        self.last_poll_cycle_at: Optional[datetime] = None

    async def get_status_snapshot(self) -> dict[str, AgentRuntimeStatus]:
        async with self._status_lock:
            return {k: v for k, v in self.status_by_agent.items()}

    async def upsert_status(self, agent_name: str, st: AgentRuntimeStatus) -> None:
        async with self._status_lock:
            self.status_by_agent[agent_name] = st

    async def poll_once(self, *, client: Any, per_agent_timeout_s: float) -> dict[str, Any]:
        async with self._poll_lock:
            cycle_started_at = _utcnow()
            outcomes: list[dict[str, Any]] = []

            # Gentle concurrency (best-effort) to keep total cycle time bounded.
            sem = asyncio.Semaphore(int(os.getenv("POLL_MAX_CONCURRENCY", "10")))

            async def _poll_one(agent: AgentConfig) -> None:
                async with sem:
                    await poll_agent_once(
                        state=self,
                        agent=agent,
                        client=client,
                        per_agent_timeout_s=per_agent_timeout_s,
                        outcomes=outcomes,
                    )

            await asyncio.gather(*[_poll_one(a) for a in self.agents])
            self.last_poll_cycle_at = cycle_started_at

            event = {
                "type": "mission_control.poll",
                "ts": cycle_started_at.isoformat(),
                "outcomes": outcomes,
            }
            await self.events.append(event)
            return event


async def poll_agent_once(
    *,
    state: MissionControlState,
    agent: AgentConfig,
    client: Any,
    per_agent_timeout_s: float,
    outcomes: list[dict[str, Any]],
) -> None:
    base = agent.service_dns
    now = _utcnow()

    health_url = _join(base, "/healthz")
    ops_url = _join(base, "/ops/status")

    health_res, health_json = await _check_endpoint(client=client, url=health_url, timeout_s=per_agent_timeout_s)
    ops_res, ops_json = await _check_endpoint(client=client, url=ops_url, timeout_s=per_agent_timeout_s)

    heartbeat_res: Optional[EndpointResult] = None
    heartbeat_payload: Optional[dict[str, Any]] = None
    md_freshness: Optional[dict[str, Any]] = None

    if agent.kind == "marketdata":
        hb_url = _join(base, "/heartbeat")
        heartbeat_res, heartbeat_payload = await _check_endpoint(
            client=client, url=hb_url, timeout_s=per_agent_timeout_s
        )

        # Fallback to /healthz contract if /heartbeat doesn't exist.
        if heartbeat_res and heartbeat_res.status_code in {404, 405}:
            heartbeat_payload = None
        src_payload = heartbeat_payload or health_json or {}
        # Marketdata service already reports age_seconds/ok on /healthz
        md_freshness = {
            "source": "/heartbeat" if heartbeat_payload is not None else "/healthz",
            "ok": bool(src_payload.get("ok")) if isinstance(src_payload, dict) else None,
            "age_seconds": src_payload.get("age_seconds") if isinstance(src_payload, dict) else None,
            "max_age_seconds": src_payload.get("max_age_seconds") if isinstance(src_payload, dict) else None,
            "last_tick_epoch_seconds": src_payload.get("last_tick_epoch_seconds") if isinstance(src_payload, dict) else None,
        }

    online = bool(health_res.ok)
    raw_ops_redacted = redact(ops_json) if ops_json else None

    st = AgentRuntimeStatus(
        agent_name=agent.agent_name,
        service_dns=agent.service_dns,
        kind=agent.kind,
        criticality=agent.criticality,
        last_poll_at=now,
        online=online,
        healthz=health_res,
        ops_status=ops_res,
        heartbeat=heartbeat_res,
        raw_ops_status_redacted=raw_ops_redacted,
        marketdata_freshness=md_freshness,
    )
    await state.upsert_status(agent.agent_name, st)

    outcomes.append(
        {
            "agent_name": agent.agent_name,
            "online": online,
            "healthz": asdict(health_res),
            "ops_status": asdict(ops_res),
            "heartbeat": asdict(heartbeat_res) if heartbeat_res else None,
        }
    )


def _agent_summary(cfg: AgentConfig, st: Optional[AgentRuntimeStatus]) -> dict[str, Any]:
    status = "UNKNOWN"
    if st and st.online is True:
        status = "ONLINE"
    elif st and st.online is False:
        status = "OFFLINE"

    return {
        "agent_name": cfg.agent_name,
        "kind": cfg.kind,
        "criticality": cfg.criticality,
        "service_dns": cfg.service_dns,
        "expected_endpoints": list(cfg.expected_endpoints),
        "status": status,
        "last_poll_at": _iso(st.last_poll_at) if st else None,
        "healthz": asdict(st.healthz) if (st and st.healthz) else None,
        "ops_status": asdict(st.ops_status) if (st and st.ops_status) else None,
        "heartbeat": asdict(st.heartbeat) if (st and st.heartbeat) else None,
        "marketdata_freshness": st.marketdata_freshness if st else None,
    }


def _agent_detail(cfg: AgentConfig, st: Optional[AgentRuntimeStatus]) -> dict[str, Any]:
    d = _agent_summary(cfg, st)
    d["raw_ops_status"] = st.raw_ops_status_redacted if st else None
    return d


@asynccontextmanager
async def lifespan(app: FastAPI):
    agents_path = os.getenv("AGENTS_CONFIG_PATH", "/app/configs/agents/agents.yaml")
    poll_interval_s = float(os.getenv("POLL_INTERVAL_SECONDS", "10"))
    per_agent_timeout_s = float(os.getenv("PER_AGENT_TIMEOUT_SECONDS", "1.5"))

    agents = load_agents_config(agents_path)
    state = MissionControlState(agents=agents)
    app.state.mc_state = state

    client = httpx.AsyncClient(
        headers={"user-agent": "agenttrader-mission-control/1.0"},
        follow_redirects=False,
    )
    app.state.http_client = client

    stop = asyncio.Event()

    async def _poll_loop() -> None:
        # Gentle polling loop; never crash on agent errors.
        while not stop.is_set():
            try:
                await state.poll_once(client=client, per_agent_timeout_s=per_agent_timeout_s)
            except Exception:
                # Observer must stay up regardless.
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=poll_interval_s)
            except asyncio.TimeoutError:
                continue

    task = asyncio.create_task(_poll_loop())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        try:
            await task
        except Exception:
            pass
        await client.aclose()


app = FastAPI(title="Agent Mission Control", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "mission-control", "ts": _utcnow().isoformat()}


async def _ensure_recent_poll(state: MissionControlState, *, client: Any) -> None:
    poll_interval_s = float(os.getenv("POLL_INTERVAL_SECONDS", "10"))
    per_agent_timeout_s = float(os.getenv("PER_AGENT_TIMEOUT_SECONDS", "1.5"))
    last = state.last_poll_cycle_at
    if last is None:
        await state.poll_once(client=client, per_agent_timeout_s=per_agent_timeout_s)
        return
    age = (_utcnow() - last).total_seconds()
    if age > max(1.0, poll_interval_s):
        await state.poll_once(client=client, per_agent_timeout_s=per_agent_timeout_s)


@app.get("/api/v1/agents")
async def list_agents(
    refresh: bool = Query(default=True, description="If true, poll agents before returning")
) -> dict[str, Any]:
    state: MissionControlState = app.state.mc_state
    client = app.state.http_client
    if refresh:
        await _ensure_recent_poll(state, client=client)
    snapshot = await state.get_status_snapshot()

    agents = state.agents
    items = [_agent_summary(cfg, snapshot.get(cfg.agent_name)) for cfg in agents]
    return {"ts": _utcnow().isoformat(), "agents": items}


@app.get("/api/v1/agents/{agent_name}")
async def get_agent(agent_name: str, refresh: bool = Query(default=True)) -> dict[str, Any]:
    state: MissionControlState = app.state.mc_state
    client = app.state.http_client
    if refresh:
        await _ensure_recent_poll(state, client=client)

    cfg = next((a for a in state.agents if a.agent_name == agent_name), None)
    if not cfg:
        raise HTTPException(status_code=404, detail="agent_not_found")

    snapshot = await state.get_status_snapshot()
    return {"ts": _utcnow().isoformat(), "agent": _agent_detail(cfg, snapshot.get(agent_name))}


@app.get("/api/v1/safety")
async def safety(refresh: bool = Query(default=True)) -> dict[str, Any]:
    state: MissionControlState = app.state.mc_state
    client = app.state.http_client
    if refresh:
        await _ensure_recent_poll(state, client=client)

    enabled, source = get_kill_switch_state()
    snapshot = await state.get_status_snapshot()

    marketdata_agents = [a for a in state.agents if a.kind == "marketdata"]
    md = []
    for a in marketdata_agents:
        st = snapshot.get(a.agent_name)
        md.append(
            {
                "agent_name": a.agent_name,
                "criticality": a.criticality,
                "status": "ONLINE" if (st and st.online) else "OFFLINE",
                "freshness": st.marketdata_freshness if st else None,
            }
        )

    all_md_ok = True
    for item in md:
        crit = item.get("criticality")
        freshness = item.get("freshness") or {}
        ok = freshness.get("ok")
        online = item.get("status") == "ONLINE"
        if crit == "critical" and (not online or ok is False or ok is None):
            all_md_ok = False

    return {
        "ts": _utcnow().isoformat(),
        "kill_switch": {"execution_halted": bool(enabled), "source": source},
        "marketdata": {"all_critical_fresh": all_md_ok, "agents": md},
    }


@app.get("/api/v1/reports/deploy/latest")
async def latest_deploy_report() -> Response:
    path = os.getenv("DEPLOY_REPORT_PATH", "/var/agenttrader/reports/deploy_report.md")
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="deploy_report_not_found")
    data = p.read_text(encoding="utf-8", errors="ignore")
    return PlainTextResponse(content=data, media_type="text/markdown")


@app.get("/api/v1/events/recent")
async def recent_events(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    state: MissionControlState = app.state.mc_state
    events = await state.events.recent(limit=int(limit))
    return {"ts": _utcnow().isoformat(), "events": events}

