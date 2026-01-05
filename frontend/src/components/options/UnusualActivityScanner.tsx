import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TrendingUp, TrendingDown, AlertCircle, Eye } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";

interface UnusualActivityScannerProps {
  symbol: string;
}

interface UnusualFlow {
  id: string;
  time: string;
  strike: number;
  expiry: string;
  type: "call" | "put";
  side: "buy" | "sell";
  size: number;
  premium: number;
  ivRank: number;
  sentiment: "bullish" | "bearish" | "neutral";
  alertLevel: "high" | "medium" | "low";
}

export function UnusualActivityScanner({ symbol }: UnusualActivityScannerProps) {
  // Mock unusual flow data
  const mockFlows: UnusualFlow[] = [
    {
      id: "1",
      time: "13:45:23",
      strike: 435,
      expiry: "12/20",
      type: "call",
      side: "buy",
      size: 850,
      premium: 142500,
      ivRank: 78,
      sentiment: "bullish",
      alertLevel: "high",
    },
    {
      id: "2",
      time: "13:42:11",
      strike: 428,
      expiry: "12/27",
      type: "put",
      side: "buy",
      size: 1200,
      premium: 215000,
      ivRank: 85,
      sentiment: "bearish",
      alertLevel: "high",
    },
    {
      id: "3",
      time: "13:38:55",
      strike: 440,
      expiry: "01/17",
      type: "call",
      side: "buy",
      size: 450,
      premium: 89000,
      ivRank: 65,
      sentiment: "bullish",
      alertLevel: "medium",
    },
    {
      id: "4",
      time: "13:35:42",
      strike: 432,
      expiry: "12/20",
      type: "call",
      side: "sell",
      size: 680,
      premium: 98000,
      ivRank: 72,
      sentiment: "neutral",
      alertLevel: "medium",
    },
    {
      id: "5",
      time: "13:30:18",
      strike: 425,
      expiry: "12/27",
      type: "put",
      side: "buy",
      size: 320,
      premium: 52000,
      ivRank: 55,
      sentiment: "bearish",
      alertLevel: "low",
    },
    {
      id: "6",
      time: "13:27:09",
      strike: 438,
      expiry: "01/17",
      type: "call",
      side: "buy",
      size: 1500,
      premium: 312000,
      ivRank: 92,
      sentiment: "bullish",
      alertLevel: "high",
    },
  ];

  const getAlertIcon = (level: string) => {
    if (level === "high") return <AlertCircle className="h-4 w-4 text-destructive" />;
    if (level === "medium") return <Eye className="h-4 w-4 text-yellow-500" />;
    return <TrendingUp className="h-4 w-4 text-muted-foreground" />;
  };

  const getSentimentIcon = (sentiment: string) => {
    if (sentiment === "bullish") return <TrendingUp className="h-4 w-4 text-bull" />;
    if (sentiment === "bearish") return <TrendingDown className="h-4 w-4 text-bear" />;
    return <span className="text-muted-foreground">—</span>;
  };

  return (
    <Card className="p-6">
      {/* Header */}
      <div className="mb-6 pb-4 border-b border-border">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h3 className="text-lg font-bold">Unusual Options Activity</h3>
            <p className="text-sm text-muted-foreground">Real-time flow detection for {symbol}</p>
          </div>
          <Badge variant="outline" className="text-xs font-semibold">
            <span className="inline-block w-2 h-2 rounded-full bg-bull animate-pulse mr-2" />
            LIVE
          </Badge>
        </div>
        
        {/* Legend */}
        <div className="flex items-center gap-6 text-xs text-muted-foreground mt-3">
          <div className="flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5 text-destructive" />
            <span>High Alert (Premium &gt; $150k)</span>
          </div>
          <div className="flex items-center gap-2">
            <Eye className="h-3.5 w-3.5 text-yellow-500" />
            <span>Medium (Premium &gt; $50k)</span>
          </div>
          <div className="flex items-center gap-2">
            <TrendingUp className="h-3.5 w-3.5 text-muted-foreground" />
            <span>Low (Premium &lt; $50k)</span>
          </div>
        </div>
      </div>

      {/* Flow Table */}
      <ScrollArea className="h-[600px] pr-4">
        <div className="space-y-2">
          {mockFlows.map((flow) => (
            <Card 
              key={flow.id} 
              className={`p-4 border-l-4 transition-all hover:shadow-lg hover:scale-[1.01] cursor-pointer ${
                flow.alertLevel === "high" 
                  ? "border-l-destructive bg-destructive/5" 
                  : flow.alertLevel === "medium"
                  ? "border-l-yellow-500 bg-yellow-500/5"
                  : "border-l-border bg-card"
              }`}
            >
              <div className="grid grid-cols-12 gap-4 items-center">
                {/* Alert Icon */}
                <div className="col-span-1 flex justify-center">
                  {getAlertIcon(flow.alertLevel)}
                </div>

                {/* Time */}
                <div className="col-span-1">
                  <div className="text-xs text-muted-foreground">Time</div>
                  <div className="text-sm font-mono font-semibold">{flow.time}</div>
                </div>

                {/* Contract Details */}
                <div className="col-span-3">
                  <div className="text-xs text-muted-foreground">Contract</div>
                  <div className="text-sm font-semibold">
                    {symbol} ${flow.strike} {flow.type.toUpperCase()} {flow.expiry}
                  </div>
                </div>

                {/* Side */}
                <div className="col-span-1">
                  <div className="text-xs text-muted-foreground">Side</div>
                  <Badge 
                    variant={flow.side === "buy" ? "default" : "secondary"}
                    className={flow.side === "buy" ? "bg-bull text-bull-foreground" : "bg-bear text-bear-foreground"}
                  >
                    {flow.side.toUpperCase()}
                  </Badge>
                </div>

                {/* Size */}
                <div className="col-span-1">
                  <div className="text-xs text-muted-foreground">Size</div>
                  <div className="text-sm font-mono font-semibold">{flow.size}</div>
                </div>

                {/* Premium */}
                <div className="col-span-2">
                  <div className="text-xs text-muted-foreground">Premium</div>
                  <div className="text-sm font-mono font-bold text-primary">
                    ${(flow.premium / 1000).toFixed(1)}k
                  </div>
                </div>

                {/* IV Rank */}
                <div className="col-span-1">
                  <div className="text-xs text-muted-foreground">IV Rank</div>
                  <div className={`text-sm font-bold ${flow.ivRank > 75 ? "text-destructive" : flow.ivRank > 50 ? "text-yellow-500" : "text-muted-foreground"}`}>
                    {flow.ivRank}%
                  </div>
                </div>

                {/* Sentiment */}
                <div className="col-span-2 flex items-center justify-center gap-2">
                  {getSentimentIcon(flow.sentiment)}
                  <span className={`text-sm font-semibold uppercase ${
                    flow.sentiment === "bullish" ? "text-bull" : 
                    flow.sentiment === "bearish" ? "text-bear" : 
                    "text-muted-foreground"
                  }`}>
                    {flow.sentiment}
                  </span>
                </div>
              </div>
            </Card>
          ))}
        </div>
      </ScrollArea>
    </Card>
  );
}
