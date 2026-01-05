from __future__ import annotations

"""
Ops markers helpers.

Note: This module intentionally mirrors the existing "Ops Marker.py" content,
but is provided under a valid Python module filename for imports.
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

DATABASE_URL = os.getenv("DATABASE_URL")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json(obj: Any) -> str:
    return json.dumps(obj, default=str)


@dataclass
class OpsContext:
    component: str  # e.g. "options-window-job", "market-stream"
    component_type: str  # "job" | "service" | "agent"
    env: str = "prod"
    version: Optional[str] = None  # git sha / image tag
    region: Optional[str] = None


class OpsDB:
    """
    Minimal Postgres writer for ops markers.

    Requires DATABASE_URL (Postgres connection string).
    Uses psycopg (v3) if available, otherwise psycopg2.
    """

    def __init__(self, database_url: Optional[str] = None):
        self.database_url = database_url or DATABASE_URL
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is not set")

        self._mode = None
        self._psycopg = None
        self._psycopg2 = None
        try:
            import psycopg  # type: ignore

            self._psycopg = psycopg
            self._mode = "psycopg3"
        except Exception:
            import psycopg2  # type: ignore

            self._psycopg2 = psycopg2
            self._mode = "psycopg2"

    def _connect(self):
        if self._mode == "psycopg3":
            return self._psycopg.connect(self.database_url)
        return self._psycopg2.connect(self.database_url)

    def upsert_heartbeat(
        self, ctx: OpsContext, status: str = "ok", meta: Optional[Dict[str, Any]] = None
    ) -> None:
        meta = meta or {}
        sql = """
        insert into public.ops_heartbeats (component, component_type, env, status, last_heartbeat_at, version, region, meta)
        values (%s, %s, %s, %s, now(), %s, %s, %s::jsonb)
        on conflict (component) do update set
          component_type = excluded.component_type,
          env = excluded.env,
          status = excluded.status,
          last_heartbeat_at = excluded.last_heartbeat_at,
          version = excluded.version,
          region = excluded.region,
          meta = excluded.meta;
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        ctx.component,
                        ctx.component_type,
                        ctx.env,
                        status,
                        ctx.version,
                        ctx.region,
                        _json(meta),
                    ),
                )

    def upsert_watermark(
        self,
        pipeline: str,
        partition_key: str = "global",
        last_event_time: Optional[datetime] = None,
        last_received_at: Optional[datetime] = None,
        last_sequence: Optional[int] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        meta = meta or {}
        let = last_event_time
        lra = last_received_at or _utcnow()
        lag_ms = None
        if let is not None:
            lag_ms = int((lra - let).total_seconds() * 1000)

        sql = """
        insert into public.ops_watermarks (pipeline, partition_key, last_event_time, last_received_at, last_sequence, lag_ms, updated_at, meta)
        values (%s, %s, %s, %s, %s, %s, now(), %s::jsonb)
        on conflict (pipeline, partition_key) do update set
          last_event_time = excluded.last_event_time,
          last_received_at = excluded.last_received_at,
          last_sequence = excluded.last_sequence,
          lag_ms = excluded.lag_ms,
          updated_at = excluded.updated_at,
          meta = excluded.meta;
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (pipeline, partition_key, let, lra, last_sequence, lag_ms, _json(meta)))


def heartbeat_loop(
    ctx: OpsContext, interval_sec: int = 30, status: str = "ok", meta: Optional[Dict[str, Any]] = None
):
    """
    Use in always-on stream services:
      from backend.utils.ops_markers import OpsDB, OpsContext, heartbeat_loop
      heartbeat_loop(OpsContext("market-stream","service", ...))
    """

    db = OpsDB()
    while True:
        db.upsert_heartbeat(ctx, status=status, meta=meta)
        time.sleep(interval_sec)

