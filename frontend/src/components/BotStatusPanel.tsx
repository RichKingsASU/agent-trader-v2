import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown } from "lucide-react";

interface BotStatus {
  status: "in_trade" | "flat";
  current_symbol?: string;
  current_side?: "long" | "short";
  entry_price?: number;
  current_price?: number;
  position_size?: number;
  pnl_open?: number;
}

interface BotStatusPanelProps {
  data: BotStatus | null;
  loading: boolean;
}

export const BotStatusPanel = ({ data, loading }: BotStatusPanelProps) => {
  if (loading || !data) {
    return (
      <Card className="p-4">
        <div className="animate-pulse space-y-3">
          <div className="h-8 bg-muted rounded"></div>
          <div className="h-4 bg-muted rounded w-3/4"></div>
        </div>
      </Card>
    );
  }

  if (data.status === "flat") {
    return (
      <Card className="p-4">
        <Badge variant="outline" className="w-full justify-center py-2 text-base font-semibold bg-muted/50">
          BOT: FLAT
        </Badge>
        <p className="text-xs text-muted-foreground text-center mt-2">
          No active positions. Bot is scanning.
        </p>
      </Card>
    );
  }

  const isLong = data.current_side === "long";
  const pnl = data.pnl_open || 0;

  return (
    <Card className={`p-4 border-2 ${isLong ? "border-bull/30 bg-bull/5" : "border-bear/30 bg-bear/5"}`}>
      <div className="flex items-center justify-between mb-3">
        <Badge
          variant="outline"
          className={`py-2 px-4 text-base font-semibold ${
            isLong ? "bg-bull/20 text-bull border-bull" : "bg-bear/20 text-bear border-bear"
          }`}
        >
          <div className="flex items-center gap-2">
            {isLong ? <TrendingUp className="h-5 w-5" /> : <TrendingDown className="h-5 w-5" />}
            BOT: IN TRADE
          </div>
        </Badge>
      </div>

      <div className="space-y-2">
        <div className="flex justify-between items-center">
          <span className="text-sm text-muted-foreground">Symbol</span>
          <span className="font-semibold text-lg">{data.current_symbol}</span>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-sm text-muted-foreground">Side</span>
          <Badge className={isLong ? "bg-bull text-bull-foreground" : "bg-bear text-bear-foreground"}>
            {data.current_side?.toUpperCase()}
          </Badge>
        </div>
        <div className="flex justify-between items-center text-sm">
          <span className="text-muted-foreground">Position Size</span>
          <span className="number-mono">{data.position_size} contracts</span>
        </div>
        <div className="flex justify-between items-center text-sm">
          <span className="text-muted-foreground">Entry Price</span>
          <span className="number-mono">${data.entry_price?.toFixed(2)}</span>
        </div>
        <div className="flex justify-between items-center text-sm">
          <span className="text-muted-foreground">Current Price</span>
          <span className="number-mono">${data.current_price?.toFixed(2)}</span>
        </div>
        <div className="border-t border-border pt-2 mt-2">
          <div className="flex justify-between items-center">
            <span className="text-sm font-medium">Open P/L</span>
            <span className={`number-mono font-bold text-lg ${pnl >= 0 ? "bull-text" : "bear-text"}`}>
              {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
            </span>
          </div>
        </div>
      </div>
    </Card>
  );
};
