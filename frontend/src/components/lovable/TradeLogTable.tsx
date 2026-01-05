import React, { useEffect, useMemo, useRef, useState } from "react";

type TradeRow = Record<string, unknown>;

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function normalizeTrades(payload: unknown): TradeRow[] {
  if (Array.isArray(payload)) return payload.filter((x) => isPlainObject(x)) as TradeRow[];
  if (!isPlainObject(payload)) return [];

  const candidates = [payload.trades, payload.history, payload.data, payload.items, (payload as any).results];
  for (const c of candidates) {
    if (Array.isArray(c)) return c.filter((x) => isPlainObject(x)) as TradeRow[];
  }
  return [];
}

function pickString(row: TradeRow, keys: string[]): string | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

function pickNumber(row: TradeRow, keys: string[]): number | null {
  for (const k of keys) {
    const v = row[k];
    if (typeof v === "number" && Number.isFinite(v)) return v;
    if (typeof v === "string") {
      const n = Number(v);
      if (Number.isFinite(n)) return n;
    }
  }
  return null;
}

function parseTimestamp(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    // Heuristic: seconds vs ms
    return value < 10_000_000_000 ? value * 1000 : value;
  }
  if (typeof value === "string" && value.trim()) {
    const asNum = Number(value);
    if (Number.isFinite(asNum)) return asNum < 10_000_000_000 ? asNum * 1000 : asNum;
    const t = Date.parse(value);
    return Number.isFinite(t) ? t : null;
  }
  return null;
}

function formatTime(ms: number | null): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function formatNumber(n: number | null, opts?: Intl.NumberFormatOptions): string {
  if (n == null) return "—";
  return new Intl.NumberFormat(undefined, opts).format(n);
}

type TradeLogTableProps = {
  className?: string;
  pollMs?: number;
  endpoint?: string;
  limit?: number;
};

export function TradeLogTable({
  className,
  pollMs = 5000,
  endpoint = "/trades/history",
  limit = 250,
}: TradeLogTableProps) {
  const [rows, setRows] = useState<TradeRow[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);

  const inflight = useRef<AbortController | null>(null);
  const lastRequestId = useRef(0);

  useEffect(() => {
    let mounted = true;

    const fetchOnce = async () => {
      const reqId = ++lastRequestId.current;
      inflight.current?.abort();
      const controller = new AbortController();
      inflight.current = controller;

      setLoading(true);
      setError(null);

      try {
        const res = await fetch(endpoint, {
          method: "GET",
          signal: controller.signal,
          cache: "no-store",
          headers: { Accept: "application/json" },
        });

        if (!res.ok) {
          const text = await res.text().catch(() => "");
          throw new Error(`HTTP ${res.status}${text ? `: ${text}` : ""}`);
        }

        const json = (await res.json()) as unknown;
        if (!mounted) return;
        if (reqId !== lastRequestId.current) return;

        const normalized = normalizeTrades(json);
        setRows(limit > 0 ? normalized.slice(0, limit) : normalized);
        setLastUpdatedAt(Date.now());
      } catch (e: any) {
        if (!mounted) return;
        if (e?.name === "AbortError") return;
        setError(e?.message ?? "Failed to fetch trade history");
      } finally {
        if (!mounted) return;
        if (reqId === lastRequestId.current) setLoading(false);
      }
    };

    fetchOnce();
    const interval = window.setInterval(fetchOnce, pollMs);
    return () => {
      mounted = false;
      window.clearInterval(interval);
      inflight.current?.abort();
    };
  }, [endpoint, pollMs, limit]);

  const view = useMemo(() => {
    return rows.map((r) => {
      const ts =
        parseTimestamp(r.ts ?? r.t ?? r.time ?? r.timestamp ?? r.created_at ?? r.filled_at ?? r.submitted_at) ?? null;
      const symbol = pickString(r, ["symbol", "ticker", "asset", "S"]) ?? "—";
      const sideRaw = pickString(r, ["side", "action", "order_side"]) ?? "—";
      const side = sideRaw.toUpperCase();
      const qty = pickNumber(r, ["qty", "quantity", "q", "shares"]);
      const price = pickNumber(r, ["price", "avg_fill_price", "fill_price", "p", "limit_price"]);
      const status = pickString(r, ["status", "state", "order_status", "fill_status"]) ?? "—";
      const strategy = pickString(r, ["strategy", "strategy_id", "bot", "agent", "source"]) ?? "—";
      const id = pickString(r, ["id", "order_id", "client_order_id", "trade_id"]) ?? null;
      return { ts, symbol, side, qty, price, status, strategy, id };
    });
  }, [rows]);

  return (
    <div
      className={[
        "relative w-full rounded-xl border border-slate-800 bg-slate-950",
        "shadow-[0_0_0_1px_rgba(15,23,42,0.6),0_10px_30px_rgba(0,0,0,0.35)]",
        className ?? "",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
        <div className="flex items-baseline gap-3">
          <div className="text-sm font-semibold text-slate-100">Trade Log</div>
          <div className="text-xs text-slate-400">
            {lastUpdatedAt ? `Updated ${formatTime(lastUpdatedAt)}` : "Not yet updated"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {loading ? (
            <div className="flex items-center gap-2 text-xs text-emerald-300">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
              Fetching
            </div>
          ) : (
            <div className="text-xs text-slate-500">Polling {Math.round(pollMs / 1000)}s</div>
          )}
        </div>
      </div>

      {error && (
        <div className="border-b border-slate-800 px-4 py-3 text-sm text-rose-300">
          <span className="font-mono">ERROR</span>: {error}
        </div>
      )}

      <div className="max-h-[52vh] overflow-auto">
        <table className="w-full table-fixed border-separate border-spacing-0">
          <thead className="sticky top-0 z-10 bg-slate-950">
            <tr className="border-b border-slate-800">
              {["Time", "Symbol", "Side", "Qty", "Price", "Status", "Strategy"].map((h) => (
                <th
                  key={h}
                  className="border-b border-slate-800 px-4 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-slate-400"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="text-sm">
            {view.length === 0 && !loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-sm text-slate-500">
                  No trades yet.
                </td>
              </tr>
            ) : (
              view.map((r, idx) => {
                const sideClass =
                  r.side === "BUY" ? "text-emerald-300" : r.side === "SELL" ? "text-rose-300" : "text-slate-200";
                return (
                  <tr
                    key={r.id ?? `${r.ts ?? "na"}-${r.symbol}-${idx}`}
                    className="border-b border-slate-900/60 hover:bg-slate-900/30"
                  >
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-300">{formatTime(r.ts)}</td>
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-slate-100">{r.symbol}</td>
                    <td className={["whitespace-nowrap px-4 py-2 font-mono text-xs", sideClass].join(" ")}>{r.side}</td>
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-200">
                      {formatNumber(r.qty, { maximumFractionDigits: 6 })}
                    </td>
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-slate-200">
                      {r.price == null ? "—" : `$${formatNumber(r.price, { maximumFractionDigits: 6 })}`}
                    </td>
                    <td className="truncate px-4 py-2 text-xs text-slate-300">{r.status}</td>
                    <td className="truncate px-4 py-2 font-mono text-xs text-slate-400">{r.strategy}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

