import { Skeleton } from "@/components/ui/skeleton";
import { SystemStatusBadge } from "@/components/SystemStatusBadge";
import { useMarketLiveQuotes } from "@/hooks/useMarketLiveQuotes";

function formatPrice(p: number | null | undefined) {
  return typeof p === "number" ? p.toFixed(2) : "—";
}

export function MarketTicker({
  symbols = ["TSLA", "NVDA", "MSFT", "AAPL", "META", "AMD", "GOOGL", "AMZN"],
}: {
  symbols?: string[];
}) {
  const { quotesBySymbol, loading, status, heartbeatAt } = useMarketLiveQuotes();

  const hasAnyQuote = symbols.some((s) => {
    const q = quotesBySymbol[s.toUpperCase()];
    return !!q && (q.last_trade_price != null || q.price != null || q.bid_price != null || q.ask_price != null);
  });

  return (
    <div className="bg-card border-b border-border py-2 px-4 overflow-x-auto">
      <div className="flex items-center gap-4 min-w-max">
        <SystemStatusBadge status={status} heartbeatAt={heartbeatAt} className="text-[10px] px-2 py-0.5" />
        <div className="h-5 w-px bg-border" />

        {loading ? (
          <div className="flex items-center gap-6">
            {Array.from({ length: Math.min(symbols.length, 6) }).map((_, i) => (
              <div key={i} className="flex items-center gap-2">
                <Skeleton className="h-4 w-10" />
                <Skeleton className="h-4 w-14" />
              </div>
            ))}
          </div>
        ) : !hasAnyQuote ? (
          <div className="text-sm text-muted-foreground">
            {status === "OFFLINE"
              ? "Market data offline."
              : status === "STALE"
                ? "Market data stale."
                : "Waiting for quotes…"}
          </div>
        ) : (
          symbols.map((symbol) => {
            const q = quotesBySymbol[symbol.toUpperCase()];
            const last = q?.last_trade_price ?? q?.price ?? null;
            const bid = q?.bid_price ?? null;
            const ask = q?.ask_price ?? null;

            return (
              <div key={symbol} className="flex items-center gap-2">
                <span className="font-semibold text-sm text-foreground">{symbol}</span>
                <span className="text-sm text-foreground number-mono">${formatPrice(last)}</span>
                <span className="text-xs text-muted-foreground number-mono">
                  {bid != null || ask != null ? `B ${formatPrice(bid)} · A ${formatPrice(ask)}` : "—"}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
