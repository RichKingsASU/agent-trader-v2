import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

interface OptionContract {
  strike: number;
  bid: number;
  ask: number;
  volume: number;
  open_interest: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
}

interface OptionsChainData {
  symbol: string;
  expiry: string;
  calls: OptionContract[];
  puts: OptionContract[];
}

interface OptionsChainProps {
  symbol: string;
  data?: OptionsChainData;
}

export function OptionsChain({ symbol, data }: OptionsChainProps) {
  const [selectedExpiry, setSelectedExpiry] = useState("2024-12-20");
  const [strikeRange, setStrikeRange] = useState("10");
  const [showGreeks, setShowGreeks] = useState(false);

  // Mock data for demonstration
  const mockExpiries = ["2024-12-20", "2024-12-27", "2025-01-17", "2025-02-21"];
  
  // Generate mock strikes around current price (assume $432)
  const currentPrice = 432;
  const strikes = Array.from({ length: parseInt(strikeRange) * 2 + 1 }, (_, i) => {
    return currentPrice - parseInt(strikeRange) + i;
  });

  const generateMockContract = (strike: number, isCall: boolean): OptionContract => {
    const itm = isCall ? strike < currentPrice : strike > currentPrice;
    const distance = Math.abs(strike - currentPrice);
    
    return {
      strike,
      bid: itm ? distance + 2 + Math.random() * 2 : Math.max(0.5, distance / 2 + Math.random()),
      ask: itm ? distance + 3 + Math.random() * 2 : Math.max(0.6, distance / 2 + Math.random() * 1.5),
      volume: Math.floor(Math.random() * 1000) + 100,
      open_interest: Math.floor(Math.random() * 5000) + 500,
      delta: isCall ? Math.max(0.01, 1 - distance / 50) : Math.min(-0.01, -distance / 50),
      gamma: 0.01 + Math.random() * 0.05,
      theta: -(0.05 + Math.random() * 0.15),
      vega: 0.1 + Math.random() * 0.3,
    };
  };

  const mockCalls = strikes.map(strike => generateMockContract(strike, true));
  const mockPuts = strikes.map(strike => generateMockContract(strike, false));

  const handleOptionClick = (strike: number, type: "call" | "put", side: "bid" | "ask") => {
    console.log(`Clicked ${side} on ${strike} ${type}`);
    // TODO: Populate order ticket
  };

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
          <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Strikes</Label>
          <Select value={strikeRange} onValueChange={setStrikeRange}>
            <SelectTrigger className="w-32 bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-[100]">
              <SelectItem value="5" className="cursor-pointer">± 5 strikes</SelectItem>
              <SelectItem value="10" className="cursor-pointer">± 10 strikes</SelectItem>
              <SelectItem value="20" className="cursor-pointer">± 20 strikes</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="flex items-center gap-2">
          <Checkbox
            id="show-greeks"
            checked={showGreeks}
            onCheckedChange={(checked) => setShowGreeks(checked as boolean)}
          />
          <Label htmlFor="show-greeks" className="text-xs font-medium cursor-pointer">
            Show Greeks
          </Label>
        </div>

        <div className="ml-auto">
          <Badge variant="outline" className="text-xs font-semibold">
            {symbol} @ ${currentPrice.toFixed(2)}
          </Badge>
        </div>
      </div>

      {/* Options Chain Table */}
      <div className="overflow-auto max-h-[600px]">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-background border-b border-border z-10">
            <tr>
              {/* CALLS Header */}
              <th colSpan={showGreeks ? 6 : 4} className="text-center py-3 px-2 font-semibold text-bull bg-bull/5 border-r-2 border-border">
                CALLS
              </th>
              {/* STRIKE Header */}
              <th className="text-center py-3 px-3 font-semibold bg-muted">
                STRIKE
              </th>
              {/* PUTS Header */}
              <th colSpan={showGreeks ? 6 : 4} className="text-center py-3 px-2 font-semibold text-bear bg-bear/5 border-l-2 border-border">
                PUTS
              </th>
            </tr>
            <tr className="text-[10px] text-muted-foreground">
              {/* CALLS Columns */}
              <th className="text-right py-2 px-2 font-medium">Bid</th>
              <th className="text-right py-2 px-2 font-medium">Ask</th>
              <th className="text-right py-2 px-2 font-medium">Vol</th>
              <th className="text-right py-2 px-2 font-medium border-r-2 border-border">OI</th>
              {showGreeks && (
                <>
                  <th className="text-right py-2 px-2 font-medium">Δ</th>
                  <th className="text-right py-2 px-2 font-medium border-r-2 border-border">Θ</th>
                </>
              )}
              
              {/* STRIKE Column */}
              <th className="text-center py-2 px-3 font-medium bg-muted">$</th>
              
              {/* PUTS Columns */}
              {showGreeks && (
                <>
                  <th className="text-right py-2 px-2 font-medium border-l-2 border-border">Δ</th>
                  <th className="text-right py-2 px-2 font-medium">Θ</th>
                </>
              )}
              <th className="text-right py-2 px-2 font-medium">Bid</th>
              <th className="text-right py-2 px-2 font-medium">Ask</th>
              <th className="text-right py-2 px-2 font-medium">Vol</th>
              <th className="text-right py-2 px-2 font-medium">OI</th>
            </tr>
          </thead>
          <tbody>
            {strikes.map((strike, idx) => {
              const call = mockCalls[idx];
              const put = mockPuts[idx];
              const isATM = Math.abs(strike - currentPrice) < 1;
              const rowClass = isATM ? "bg-accent/10" : idx % 2 === 0 ? "bg-card" : "bg-muted/20";

              return (
                <tr key={strike} className={`${rowClass} hover:bg-accent/20 transition-colors`}>
                  {/* CALLS Data */}
                  <td 
                    className="text-right py-2 px-2 number-mono cursor-pointer hover:bg-bull/10 hover:font-semibold"
                    onClick={() => handleOptionClick(strike, "call", "bid")}
                  >
                    {call.bid.toFixed(2)}
                  </td>
                  <td 
                    className="text-right py-2 px-2 number-mono cursor-pointer hover:bg-bull/10 hover:font-semibold"
                    onClick={() => handleOptionClick(strike, "call", "ask")}
                  >
                    {call.ask.toFixed(2)}
                  </td>
                  <td className="text-right py-2 px-2 number-mono text-muted-foreground">
                    {call.volume.toLocaleString()}
                  </td>
                  <td className="text-right py-2 px-2 number-mono text-muted-foreground border-r-2 border-border">
                    {call.open_interest.toLocaleString()}
                  </td>
                  {showGreeks && (
                    <>
                      <td className="text-right py-2 px-2 number-mono text-xs text-bull">
                        {call.delta.toFixed(2)}
                      </td>
                      <td className="text-right py-2 px-2 number-mono text-xs text-muted-foreground border-r-2 border-border">
                        {call.theta.toFixed(2)}
                      </td>
                    </>
                  )}
                  
                  {/* STRIKE */}
                  <td className={`text-center py-2 px-3 font-bold number-mono ${isATM ? "text-primary bg-primary/10" : "bg-muted"}`}>
                    {strike}
                  </td>
                  
                  {/* PUTS Data */}
                  {showGreeks && (
                    <>
                      <td className="text-right py-2 px-2 number-mono text-xs text-bear border-l-2 border-border">
                        {put.delta.toFixed(2)}
                      </td>
                      <td className="text-right py-2 px-2 number-mono text-xs text-muted-foreground">
                        {put.theta.toFixed(2)}
                      </td>
                    </>
                  )}
                  <td 
                    className="text-right py-2 px-2 number-mono cursor-pointer hover:bg-bear/10 hover:font-semibold"
                    onClick={() => handleOptionClick(strike, "put", "bid")}
                  >
                    {put.bid.toFixed(2)}
                  </td>
                  <td 
                    className="text-right py-2 px-2 number-mono cursor-pointer hover:bg-bear/10 hover:font-semibold"
                    onClick={() => handleOptionClick(strike, "put", "ask")}
                  >
                    {put.ask.toFixed(2)}
                  </td>
                  <td className="text-right py-2 px-2 number-mono text-muted-foreground">
                    {put.volume.toLocaleString()}
                  </td>
                  <td className="text-right py-2 px-2 number-mono text-muted-foreground">
                    {put.open_interest.toLocaleString()}
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
