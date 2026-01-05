import React, { useEffect, useMemo, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { useOpsStatus } from "@/lib/lovable/useOpsStatus";

type TickerPoint = {
  t: number; // ms since epoch
  price: number;
};

type LiveTickerProps = {
  symbol?: string;
  serviceId?: string;
  className?: string;
};

function parseIncomingPoint(raw: string): { symbol?: string; price?: number; t?: number } | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;

  // Common case: JSON payload.
  try {
    const obj = JSON.parse(trimmed) as Record<string, unknown>;

    const symbol =
      (typeof obj.symbol === "string" && obj.symbol) || (typeof obj.S === "string" && obj.S) || undefined;

    const priceCandidate = obj.price ?? obj.p ?? obj.last ?? obj.close ?? obj.c ?? obj.value ?? obj.v ?? obj.P;
    const price =
      typeof priceCandidate === "number"
        ? priceCandidate
        : typeof priceCandidate === "string"
          ? Number(priceCandidate)
          : NaN;

    const tCandidate = obj.t ?? obj.ts ?? obj.timestamp ?? obj.time;
    const t =
      typeof tCandidate === "number" ? tCandidate : typeof tCandidate === "string" ? Date.parse(tCandidate) : NaN;

    if (!Number.isFinite(price)) return null;
    return { symbol, price, t: Number.isFinite(t) ? t : undefined };
  } catch {
    // Fallback case: plain number.
    const asNum = Number(trimmed);
    if (!Number.isFinite(asNum)) return null;
    return { price: asNum };
  }
}

export function LiveTicker({
  symbol = "SPY",
  serviceId = "agenttrader-prod-streamer",
  className,
}: LiveTickerProps) {
  const { status } = useOpsStatus(serviceId);
  const isOffline = status === "Red" || status === "Gray";
  const isLive = status === "Green";

  const [points, setPoints] = useState<TickerPoint[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const lastPrice = points.length ? points[points.length - 1]!.price : null;

  const streamerUrl = import.meta.env.VITE_STREAMER_URL as string | undefined;

  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!streamerUrl) {
      setStreamError("Missing VITE_STREAMER_URL");
      return;
    }

    setStreamError(null);
    const es = new EventSource(streamerUrl);
    esRef.current = es;

    es.onmessage = (evt) => {
      const parsed = parseIncomingPoint(evt.data);
      if (!parsed?.price) return;
      if (parsed.symbol && parsed.symbol.toUpperCase() !== symbol.toUpperCase()) return;

      const next: TickerPoint = {
        t: typeof parsed.t === "number" ? parsed.t : Date.now(),
        price: parsed.price,
      };

      setPoints((prev) => (prev.length >= 50 ? [...prev.slice(-49), next] : [...prev, next]));
    };

    es.onerror = () => {
      // EventSource auto-retries; keep a soft error for UI.
      setStreamError("Stream connection error (retrying…)");
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [streamerUrl, symbol]);

  const xTickFormatter = useMemo(() => {
    return (t: number) =>
      new Date(t).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
  }, []);

  return (
    <div className={["relative w-full rounded-xl border border-slate-800 bg-slate-950 p-4", className ?? ""].join(" ")}>
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <div className="text-sm font-semibold text-slate-100">{symbol} Live Ticker</div>
          {lastPrice != null ? (
            <div className="text-xs text-slate-300">${lastPrice.toFixed(2)}</div>
          ) : (
            <div className="text-xs text-slate-500">Waiting for data…</div>
          )}
        </div>

        <div className="flex items-center gap-2">
          {isLive ? (
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
              </span>
              <span className="text-xs font-medium text-emerald-300">Live</span>
            </div>
          ) : (
            <span className="text-xs text-slate-400">{status}</span>
          )}
        </div>
      </div>

      <div className={isOffline ? "opacity-40" : ""}>
        <div className="h-48 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={points} margin={{ top: 8, right: 10, bottom: 0, left: 0 }}>
              <CartesianGrid stroke="rgba(148,163,184,0.12)" strokeDasharray="3 3" />
              <XAxis
                dataKey="t"
                type="number"
                domain={["dataMin", "dataMax"]}
                tickFormatter={xTickFormatter}
                tick={{ fill: "rgba(148,163,184,0.85)", fontSize: 11 }}
                axisLine={{ stroke: "rgba(148,163,184,0.25)" }}
                tickLine={{ stroke: "rgba(148,163,184,0.25)" }}
              />
              <YAxis
                dataKey="price"
                domain={["auto", "auto"]}
                tick={{ fill: "rgba(148,163,184,0.85)", fontSize: 11 }}
                axisLine={{ stroke: "rgba(148,163,184,0.25)" }}
                tickLine={{ stroke: "rgba(148,163,184,0.25)" }}
                width={46}
              />
              <Tooltip
                labelFormatter={(label) => xTickFormatter(Number(label))}
                formatter={(value) => [`$${Number(value).toFixed(2)}`, "Price"]}
                contentStyle={{
                  background: "rgba(2,6,23,0.95)",
                  border: "1px solid rgba(148,163,184,0.25)",
                  borderRadius: 10,
                  color: "rgba(226,232,240,0.95)",
                }}
              />
              <Line
                type="monotone"
                dataKey="price"
                stroke="#60a5fa"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {(isOffline || streamError) && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center rounded-xl bg-slate-950/40">
          <div className="rounded-lg border border-slate-700 bg-slate-950/90 px-4 py-2 text-sm text-slate-200">
            {isOffline ? "Stream Offline" : streamError}
          </div>
        </div>
      )}
    </div>
  );
}

