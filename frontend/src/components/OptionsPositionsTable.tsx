import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { X, ArrowUpDown } from "lucide-react";

interface OptionPosition {
  underlying: string;
  position_summary: string;
  cost_basis: number;
  market_value: number;
  pnl_usd: number;
  pnl_pct: number;
  delta: number;
  theta: number;
  vega: number;
}

interface OptionsPositionsTableProps {
  positions?: OptionPosition[];
  loading?: boolean;
}

export function OptionsPositionsTable({ positions, loading }: OptionsPositionsTableProps) {
  // Mock data for demonstration
  const mockPositions: OptionPosition[] = positions || [
    {
      underlying: "SPY",
      position_summary: "+5 19Dec25 430C",
      cost_basis: 2500.00,
      market_value: 2750.00,
      pnl_usd: 250.00,
      pnl_pct: 10.0,
      delta: 18.5,
      theta: -12.5,
      vega: 8.3,
    },
    {
      underlying: "SPY",
      position_summary: "-5 19Dec25 435C",
      cost_basis: -1500.00,
      market_value: -1200.00,
      pnl_usd: 300.00,
      pnl_pct: 20.0,
      delta: -8.2,
      theta: 8.5,
      vega: -4.1,
    },
    {
      underlying: "QQQ",
      position_summary: "+3 20Dec25 380P",
      cost_basis: 1800.00,
      market_value: 1650.00,
      pnl_usd: -150.00,
      pnl_pct: -8.33,
      delta: -12.6,
      theta: -9.2,
      vega: 5.5,
    },
  ];

  if (loading) {
    return (
      <Card className="p-4">
        <div className="animate-pulse space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-16 bg-muted rounded" />
          ))}
        </div>
      </Card>
    );
  }

  if (!mockPositions || mockPositions.length === 0) {
    return (
      <Card className="p-6 text-center">
        <p className="text-sm text-muted-foreground">No options positions</p>
      </Card>
    );
  }

  // Group by underlying
  const groupedPositions = mockPositions.reduce((acc, pos) => {
    if (!acc[pos.underlying]) {
      acc[pos.underlying] = [];
    }
    acc[pos.underlying].push(pos);
    return acc;
  }, {} as Record<string, OptionPosition[]>);

  const handleClose = (position: string) => {
    console.log("Close position:", position);
    // TODO: Implement close logic
  };

  const handleRoll = (position: string) => {
    console.log("Roll position:", position);
    // TODO: Implement roll logic
  };

  return (
    <Card className="p-4">
      <div className="space-y-4">
        {Object.entries(groupedPositions).map(([underlying, positions]) => {
          // Calculate totals for this underlying
          const totalPnl = positions.reduce((sum, pos) => sum + pos.pnl_usd, 0);
          const totalDelta = positions.reduce((sum, pos) => sum + pos.delta, 0);
          const totalTheta = positions.reduce((sum, pos) => sum + pos.theta, 0);
          const totalVega = positions.reduce((sum, pos) => sum + pos.vega, 0);

          return (
            <div key={underlying} className="space-y-2">
              {/* Group Header */}
              <div className="flex items-center justify-between bg-muted/50 px-3 py-2 rounded-md">
                <div className="flex items-center gap-3">
                  <Badge variant="outline" className="font-bold">
                    {underlying}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {positions.length} position{positions.length > 1 ? 's' : ''}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-xs">
                  <div className="text-right">
                    <div className="text-[10px] text-muted-foreground uppercase">Net P/L</div>
                    <div className={`number-mono font-bold ${totalPnl >= 0 ? "bull-text" : "bear-text"}`}>
                      {totalPnl >= 0 ? "+" : ""}${Math.abs(totalPnl).toFixed(0)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-muted-foreground uppercase">Δ</div>
                    <div className="number-mono font-semibold">{totalDelta >= 0 ? "+" : ""}{totalDelta.toFixed(1)}</div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10px] text-muted-foreground uppercase">Θ</div>
                    <div className="number-mono font-semibold">{totalTheta.toFixed(1)}</div>
                  </div>
                </div>
              </div>

              {/* Positions in this group */}
              <div className="space-y-1.5 pl-2">
                {positions.map((pos, idx) => (
                  <div
                    key={idx}
                    className="bg-card border border-border rounded-md p-3 hover:bg-accent/5 transition-colors"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="font-medium text-sm">{pos.position_summary}</div>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          onClick={() => handleRoll(pos.position_summary)}
                        >
                          <ArrowUpDown className="h-3 w-3 mr-1" />
                          Roll
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs hover:bg-destructive/10 hover:text-destructive"
                          onClick={() => handleClose(pos.position_summary)}
                        >
                          <X className="h-3 w-3 mr-1" />
                          Close
                        </Button>
                      </div>
                    </div>

                    <div className="grid grid-cols-4 gap-3 text-xs">
                      <div>
                        <div className="text-[10px] text-muted-foreground uppercase mb-0.5">Cost Basis</div>
                        <div className="number-mono font-semibold">
                          ${Math.abs(pos.cost_basis).toLocaleString("en-US", { minimumFractionDigits: 0 })}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted-foreground uppercase mb-0.5">Market Value</div>
                        <div className="number-mono font-semibold">
                          ${Math.abs(pos.market_value).toLocaleString("en-US", { minimumFractionDigits: 0 })}
                        </div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted-foreground uppercase mb-0.5">P/L</div>
                        <div className={`number-mono font-bold ${pos.pnl_usd >= 0 ? "bull-text" : "bear-text"}`}>
                          {pos.pnl_usd >= 0 ? "+" : ""}${Math.abs(pos.pnl_usd).toFixed(0)}
                          <span className="ml-1">({pos.pnl_pct >= 0 ? "+" : ""}{pos.pnl_pct.toFixed(1)}%)</span>
                        </div>
                      </div>
                      <div className="flex items-end gap-2 text-[10px] number-mono">
                        <span className="text-muted-foreground">Δ</span>
                        <span className={pos.delta >= 0 ? "bull-text" : "bear-text"}>
                          {pos.delta >= 0 ? "+" : ""}{pos.delta.toFixed(1)}
                        </span>
                        <span className="text-muted-foreground">Θ</span>
                        <span>{pos.theta.toFixed(1)}</span>
                        <span className="text-muted-foreground">V</span>
                        <span>{pos.vega >= 0 ? "+" : ""}{pos.vega.toFixed(1)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
