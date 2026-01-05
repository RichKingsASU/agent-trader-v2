import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { DollarSign, TrendingUp, Wallet } from "lucide-react";
import { formatUsd0, formatUsd2 } from "@/lib/utils";

interface AccountData {
  account_id: string;
  environment: "production" | "sandbox";
  market: string;
  equity: number;
  day_pnl: number;
  day_pnl_pct: number;
  unrealized_pnl: number;
  realized_pnl: number;
  settled_cash: number;
  buying_power: number;
  margin_available: number;
  portfolio_delta: number;
  portfolio_theta: number;
  portfolio_vega: number;
}

interface AccountPanelProps {
  data: AccountData | null;
  loading: boolean;
}

export const AccountPanel = ({ data, loading }: AccountPanelProps) => {
  if (loading || !data) {
    return (
      <div className="space-y-3">
        {[...Array(3)].map((_, i) => (
          <Card key={i} className="p-4">
            <div className="animate-pulse space-y-3">
              <div className="h-3 bg-muted rounded w-1/3"></div>
              <div className="h-6 bg-muted rounded"></div>
            </div>
          </Card>
        ))}
      </div>
    );
  }

  const getGreekColor = (value: number, type: 'delta' | 'theta' | 'vega') => {
    if (type === 'delta') {
      if (Math.abs(value) > 50) return value > 0 ? "bull-text" : "bear-text";
      return "text-muted-foreground";
    }
    if (type === 'theta') {
      if (Math.abs(value) > 25) return "text-warning";
      return "text-muted-foreground";
    }
    if (type === 'vega') {
      if (Math.abs(value) > 40) return "text-info";
      return "text-muted-foreground";
    }
    return "text-muted-foreground";
  };

  return (
    <div className="space-y-3">
      {/* Account Info Header */}
      <div className="flex items-center justify-between px-1">
        <div>
          <div className="number-mono text-sm font-medium">{data.account_id}</div>
          <div className="text-xs text-muted-foreground ui-label">{data.market}</div>
        </div>
        <Badge
          variant="outline"
          className={`text-[10px] ${
            data.environment === "production" 
              ? "bg-production/10 text-production border-production" 
              : "bg-sandbox/10 text-sandbox border-sandbox"
          }`}
        >
          {data.environment.toUpperCase()}
        </Badge>
      </div>

      {/* 1. Equity Card - High Contrast */}
      <Card className="p-4 border-2 border-primary/20 bg-gradient-to-br from-primary/5 to-primary/10">
        <div className="flex items-center gap-2 mb-3">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h3 className="text-xs font-bold text-primary uppercase tracking-wider ui-label">Equity & P/L</h3>
        </div>
        <div className="space-y-3">
          <div className="flex justify-between items-baseline">
            <span className="text-xs text-muted-foreground font-medium ui-label">Total Equity</span>
            <span className="number-mono text-xl font-bold text-foreground">
              {formatUsd2(data.equity)}
            </span>
          </div>
          <div className="flex justify-between items-baseline pt-2 border-t border-primary/20">
            <span className="text-xs text-muted-foreground font-medium ui-label">Day P/L</span>
            <div className="text-right">
              <div className={`number-mono text-lg font-bold ${data.day_pnl >= 0 ? "bull-text" : "bear-text"}`}>
                {data.day_pnl >= 0 ? "+" : "-"}
                {formatUsd2(Math.abs(data.day_pnl))}
              </div>
              <div className={`text-xs font-semibold ${data.day_pnl >= 0 ? "bull-text" : "bear-text"}`}>
                ({data.day_pnl_pct >= 0 ? "+" : ""}{data.day_pnl_pct.toFixed(2)}%)
              </div>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 pt-2 border-t border-primary/20">
            <div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Unrealized</div>
              <div className={`number-mono text-sm font-bold ${data.unrealized_pnl >= 0 ? "bull-text" : "bear-text"}`}>
                {data.unrealized_pnl >= 0 ? "+" : "-"}
                {formatUsd0(Math.abs(data.unrealized_pnl))}
              </div>
            </div>
            <div>
              <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Realized</div>
              <div className={`number-mono text-sm font-bold ${data.realized_pnl >= 0 ? "bull-text" : "bear-text"}`}>
                {data.realized_pnl >= 0 ? "+" : "-"}
                {formatUsd0(Math.abs(data.realized_pnl))}
              </div>
            </div>
          </div>
        </div>
      </Card>

      {/* 2. Liquidity Card - High Contrast */}
      <Card className="p-4 border-2 border-accent/20 bg-gradient-to-br from-accent/5 to-accent/10">
        <div className="flex items-center gap-2 mb-3">
          <Wallet className="h-4 w-4 text-accent" />
          <h3 className="text-xs font-bold text-accent uppercase tracking-wider ui-label">Liquidity</h3>
        </div>
        <div className="space-y-3">
          <div className="bg-background/60 border border-accent/30 rounded-md p-3">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Settled Cash</div>
            <div className="number-mono text-lg font-bold text-foreground">
              {formatUsd2(data.settled_cash)}
            </div>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-muted-foreground font-medium ui-label">Buying Power</span>
            <span className="number-mono font-bold text-sm">
              {formatUsd0(data.buying_power)}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-muted-foreground font-medium ui-label">Margin Available</span>
            <span className="number-mono font-bold text-sm">
              {formatUsd0(data.margin_available)}
            </span>
          </div>
        </div>
      </Card>

      {/* 3. Greeks Card - High Contrast */}
      <Card className="p-4 border-2 border-muted-foreground/20 bg-gradient-to-br from-muted/30 to-muted/50">
        <div className="flex items-center gap-2 mb-3">
          <DollarSign className="h-4 w-4 text-muted-foreground" />
          <h3 className="text-xs font-bold text-muted-foreground uppercase tracking-wider ui-label">Portfolio Greeks</h3>
        </div>
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-background/60 border border-white/10 rounded-md p-3 text-center">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Delta</div>
            <div className={`number-mono text-base font-bold ${getGreekColor(data.portfolio_delta, 'delta')}`}>
              {data.portfolio_delta >= 0 ? "+" : ""}{data.portfolio_delta.toFixed(1)}
            </div>
          </div>
          <div className="bg-background/60 border border-white/10 rounded-md p-3 text-center">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Theta</div>
            <div className={`number-mono text-base font-bold ${getGreekColor(data.portfolio_theta, 'theta')}`}>
              {data.portfolio_theta.toFixed(1)}
            </div>
          </div>
          <div className="bg-background/60 border border-white/10 rounded-md p-3 text-center">
            <div className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1 font-medium ui-label">Vega</div>
            <div className={`number-mono text-base font-bold ${getGreekColor(data.portfolio_vega, 'vega')}`}>
              {data.portfolio_vega >= 0 ? "+" : ""}{data.portfolio_vega.toFixed(1)}
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
};
