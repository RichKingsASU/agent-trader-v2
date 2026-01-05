import { TradeLogTable } from "@/components/lovable/TradeLogTable";
import LiveQuotesWidget from "@/components/LiveQuotesWidget";

export default function DashboardPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-6 py-6">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <div className="text-lg font-semibold text-slate-100">Dashboard</div>
        <div className="text-xs text-slate-500">
          <span className="font-mono">LOVABLE</span> · terminal view
        </div>
      </div>

      <div className="grid grid-rows-[auto,1fr] gap-4">
        <section className="min-h-[14rem]">
          <LiveQuotesWidget />
        </section>

        <section className="min-h-0">
          <TradeLogTable endpoint={import.meta.env.VITE_TRADES_ENDPOINT ?? "/trades/history"} />
        </section>
      </div>
    </main>
  );
}

