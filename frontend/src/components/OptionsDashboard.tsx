import { RefreshCw } from "lucide-react";
import { RecentTradesTable } from "@/components/RecentTradesTable";
import { useQuery } from "@tanstack/react-query";
import { getFirestore, getDocs } from "firebase/firestore";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

interface PortfolioPerformance {
  root_symbol: string | null;
  total_contracts: number | null;
  total_premium_spent: number | null;
  avg_portfolio_delta: number | null;
  avg_portfolio_theta: number | null;
  last_trade_time: string | null;
}

function formatCurrency(value: number | null): string {
  if (value === null) return "$0.00";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(value);
}

function getDeltaColor(delta: number | null): string {
  if (delta === null) return "text-muted-foreground";
  return delta > 0.5 ? "text-emerald-400" : "text-slate-400";
}

function TickerCard({ data }: { data: PortfolioPerformance }) {
  const deltaColor = getDeltaColor(data.avg_portfolio_delta);

  return (
    <Card className="bg-slate-800 border-slate-700">
      <CardHeader className="pb-2">
        <CardTitle className="text-2xl font-bold text-foreground">
          {data.root_symbol || "Unknown"}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Exposure</p>
            <p className="text-lg font-semibold text-foreground">
              {formatCurrency(data.total_premium_spent)}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">Volume</p>
            <p className="text-lg font-semibold text-foreground">
              {data.total_contracts ?? 0} contracts
            </p>
          </div>
        </div>

        <div className="border-t border-slate-700 pt-4">
          <p className="text-xs text-muted-foreground uppercase tracking-wide mb-2">Risk</p>
          <div className="grid grid-cols-2 gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Δ Delta</span>
              <span className={`text-sm font-semibold ${deltaColor}`}>
                {data.avg_portfolio_delta?.toFixed(3) ?? "—"}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Θ Theta</span>
              <span className="text-sm font-semibold text-amber-400">
                {data.avg_portfolio_theta?.toFixed(3) ?? "—"}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function TickerCardSkeleton() {
  return (
    <Card className="bg-slate-800 border-slate-700">
      <CardHeader className="pb-2">
        <Skeleton className="h-8 w-16" />
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-6 w-24" />
          </div>
          <div>
            <Skeleton className="h-3 w-16 mb-2" />
            <Skeleton className="h-6 w-20" />
          </div>
        </div>
        <div className="border-t border-slate-700 pt-4">
          <Skeleton className="h-3 w-12 mb-2" />
          <div className="grid grid-cols-2 gap-4">
            <Skeleton className="h-5 w-20" />
            <Skeleton className="h-5 w-20" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function OptionsDashboard() {
  const { tenantId } = useAuth();
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["portfolio-performance", tenantId],
    queryFn: async () => {
      if (!tenantId) return [];
      const db = getFirestore();
      const snapshot = await getDocs(tenantCollection(db, tenantId, "portfolio_performance"));
      return snapshot.docs.map(doc => doc.data()) as PortfolioPerformance[];
    },
  });

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-7xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-foreground">Portfolio Performance</h1>
            <p className="text-muted-foreground text-sm">Options exposure by ticker</p>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => refetch()}
            disabled={isFetching}
            className="gap-2 border-slate-700 hover:bg-slate-800"
          >
            <RefreshCw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {isLoading ? (
            <>
              <TickerCardSkeleton />
              <TickerCardSkeleton />
              <TickerCardSkeleton />
            </>
          ) : data && data.length > 0 ? (
            data.map((item) => (
              <TickerCard key={item.root_symbol} data={item} />
            ))
          ) : (
            <div className="col-span-full text-center py-12">
              <p className="text-muted-foreground">No portfolio data available</p>
            </div>
          )}
        </div>

        <div className="mt-8">
          <RecentTradesTable />
        </div>
      </div>
    </div>
  );
}
