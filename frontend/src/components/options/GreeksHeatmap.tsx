import { useMemo } from "react";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { useState } from "react";

interface GreeksHeatmapProps {
  symbol: string;
}

type GreekType = "delta" | "gamma" | "theta" | "vega";

export function GreeksHeatmap({ symbol }: GreeksHeatmapProps) {
  const [selectedExpiry, setSelectedExpiry] = useState("2024-12-20");
  const [selectedGreek, setSelectedGreek] = useState<GreekType>("delta");

  const mockExpiries = ["2024-12-20", "2024-12-27", "2025-01-17", "2025-02-21"];
  const currentPrice = 432;
  
  // Generate strikes and mock Greeks data
  const strikes = Array.from({ length: 21 }, (_, i) => currentPrice - 10 + i);
  
  const greeksData = useMemo(() => {
    return strikes.map(strike => {
      const distance = Math.abs(strike - currentPrice);
      const itm = strike < currentPrice;
      
      return {
        strike,
        call: {
          delta: itm ? 0.5 + (10 - distance) / 20 : 0.5 - distance / 20,
          gamma: Math.max(0, 0.1 - distance / 100),
          theta: -(0.05 + Math.random() * 0.1),
          vega: 0.15 + Math.random() * 0.1,
        },
        put: {
          delta: itm ? -(distance / 20) : -(0.5 + (10 - distance) / 20),
          gamma: Math.max(0, 0.1 - distance / 100),
          theta: -(0.05 + Math.random() * 0.1),
          vega: 0.15 + Math.random() * 0.1,
        },
      };
    });
  }, [strikes, currentPrice]);

  const getColorClass = (value: number, greek: GreekType) => {
    const absValue = Math.abs(value);
    
    if (greek === "delta") {
      if (value > 0.7) return "bg-bull text-bull-foreground";
      if (value > 0.4) return "bg-bull/70 text-bull-foreground";
      if (value > 0.2) return "bg-bull/40 text-foreground";
      if (value > -0.2) return "bg-muted text-muted-foreground";
      if (value > -0.4) return "bg-bear/40 text-foreground";
      if (value > -0.7) return "bg-bear/70 text-bear-foreground";
      return "bg-bear text-bear-foreground";
    }
    
    if (greek === "gamma") {
      if (absValue > 0.08) return "bg-primary text-primary-foreground";
      if (absValue > 0.05) return "bg-primary/70 text-primary-foreground";
      if (absValue > 0.03) return "bg-primary/40 text-foreground";
      return "bg-muted text-muted-foreground";
    }
    
    if (greek === "theta") {
      if (absValue > 0.12) return "bg-destructive text-destructive-foreground";
      if (absValue > 0.08) return "bg-destructive/70 text-destructive-foreground";
      if (absValue > 0.05) return "bg-destructive/40 text-foreground";
      return "bg-muted text-muted-foreground";
    }
    
    if (greek === "vega") {
      if (absValue > 0.22) return "bg-accent text-accent-foreground";
      if (absValue > 0.18) return "bg-accent/70 text-accent-foreground";
      if (absValue > 0.15) return "bg-accent/40 text-foreground";
      return "bg-muted text-muted-foreground";
    }
    
    return "bg-muted text-muted-foreground";
  };

  const formatValue = (value: number) => value.toFixed(3);

  return (
    <Card className="p-6">
      {/* Controls */}
      <div className="flex items-center gap-6 mb-6 pb-4 border-b border-border">
        <div className="flex items-center gap-3">
          <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Expiry</Label>
          <Select value={selectedExpiry} onValueChange={setSelectedExpiry}>
            <SelectTrigger className="w-40 bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-[100]">
              {mockExpiries.map((expiry) => (
                <SelectItem key={expiry} value={expiry} className="cursor-pointer">
                  {expiry}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-3">
          <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Greek</Label>
          <Select value={selectedGreek} onValueChange={(v) => setSelectedGreek(v as GreekType)}>
            <SelectTrigger className="w-32 bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-[100]">
              <SelectItem value="delta" className="cursor-pointer">Delta (Δ)</SelectItem>
              <SelectItem value="gamma" className="cursor-pointer">Gamma (Γ)</SelectItem>
              <SelectItem value="theta" className="cursor-pointer">Theta (Θ)</SelectItem>
              <SelectItem value="vega" className="cursor-pointer">Vega (ν)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="ml-auto text-sm text-muted-foreground">
          {symbol} @ <span className="font-bold text-foreground">${currentPrice.toFixed(2)}</span>
        </div>
      </div>

      {/* Legend */}
      <div className="mb-4 flex items-center gap-6 text-xs">
        <span className="font-semibold text-muted-foreground uppercase tracking-wide">Color Intensity:</span>
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <div className="w-4 h-4 bg-muted" />
            <span className="text-muted-foreground">Low</span>
          </div>
          <span className="text-muted-foreground">→</span>
          <div className="flex items-center gap-1">
            <div className={`w-4 h-4 ${selectedGreek === 'delta' ? 'bg-bull' : selectedGreek === 'gamma' ? 'bg-primary' : selectedGreek === 'theta' ? 'bg-destructive' : 'bg-accent'}`} />
            <span className="text-muted-foreground">High</span>
          </div>
        </div>
      </div>

      {/* Heatmap Table */}
      <div className="overflow-auto max-h-[600px]">
        <table className="w-full text-xs border-collapse">
          <thead className="sticky top-0 bg-background z-10">
            <tr>
              <th className="text-center py-3 px-3 font-semibold border-b-2 border-border bg-muted">Strike</th>
              <th className="text-center py-3 px-4 font-semibold border-b-2 border-border bg-bull/10 text-bull">CALL {selectedGreek.toUpperCase()}</th>
              <th className="text-center py-3 px-4 font-semibold border-b-2 border-border bg-bear/10 text-bear">PUT {selectedGreek.toUpperCase()}</th>
            </tr>
          </thead>
          <tbody>
            {greeksData.map(({ strike, call, put }) => {
              const isATM = Math.abs(strike - currentPrice) < 1;
              const callValue = call[selectedGreek];
              const putValue = put[selectedGreek];

              return (
                <tr key={strike} className={isATM ? "border-y-2 border-primary" : ""}>
                  <td className={`text-center py-3 px-3 font-bold number-mono ${isATM ? "bg-primary/20 text-primary" : "bg-muted"}`}>
                    {strike}
                  </td>
                  <td className="p-1">
                    <div className={`${getColorClass(callValue, selectedGreek)} py-2 px-4 text-center font-mono font-semibold rounded`}>
                      {formatValue(callValue)}
                    </div>
                  </td>
                  <td className="p-1">
                    <div className={`${getColorClass(putValue, selectedGreek)} py-2 px-4 text-center font-mono font-semibold rounded`}>
                      {formatValue(putValue)}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
