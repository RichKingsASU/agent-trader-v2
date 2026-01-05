import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";

interface MultiExpiryComparisonProps {
  symbol: string;
}

interface ExpiryData {
  expiry: string;
  dte: number;
  atmIV: number;
  callVolume: number;
  putVolume: number;
  pcRatio: number;
  openInterest: number;
}

export function MultiExpiryComparison({ symbol }: MultiExpiryComparisonProps) {
  const currentPrice = 432;
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>([
    "2024-12-20",
    "2024-12-27",
    "2025-01-17",
  ]);

  // Mock data for multiple expiries
  const allExpiries: ExpiryData[] = [
    {
      expiry: "2024-12-20",
      dte: 5,
      atmIV: 24.5,
      callVolume: 45230,
      putVolume: 38100,
      pcRatio: 0.84,
      openInterest: 125000,
    },
    {
      expiry: "2024-12-27",
      dte: 12,
      atmIV: 26.8,
      callVolume: 32150,
      putVolume: 41200,
      pcRatio: 1.28,
      openInterest: 98000,
    },
    {
      expiry: "2025-01-17",
      dte: 33,
      atmIV: 28.2,
      callVolume: 78900,
      putVolume: 65400,
      pcRatio: 0.83,
      openInterest: 215000,
    },
    {
      expiry: "2025-02-21",
      dte: 68,
      atmIV: 30.1,
      callVolume: 52300,
      putVolume: 48700,
      pcRatio: 0.93,
      openInterest: 142000,
    },
  ];

  const handleExpiryToggle = (expiry: string) => {
    setSelectedExpiries((prev) =>
      prev.includes(expiry)
        ? prev.filter((e) => e !== expiry)
        : [...prev, expiry]
    );
  };

  const selectedData = allExpiries.filter((e) => selectedExpiries.includes(e.expiry));

  return (
    <Card className="p-6">
      {/* Header */}
      <div className="mb-6 pb-4 border-b border-border">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-bold mb-1">Multi-Expiry Comparison</h3>
            <p className="text-sm text-muted-foreground">
              Compare options metrics across multiple expiration dates for {symbol}
            </p>
          </div>
          <Badge variant="outline" className="text-xs font-semibold">
            {symbol} @ ${currentPrice.toFixed(2)}
          </Badge>
        </div>
      </div>

      {/* Expiry Selection */}
      <div className="mb-6">
        <Label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 block">
          Select Expiries to Compare
        </Label>
        <div className="flex gap-4">
          {allExpiries.map((exp) => (
            <div key={exp.expiry} className="flex items-center gap-2">
              <Checkbox
                id={exp.expiry}
                checked={selectedExpiries.includes(exp.expiry)}
                onCheckedChange={() => handleExpiryToggle(exp.expiry)}
              />
              <Label htmlFor={exp.expiry} className="text-sm cursor-pointer">
                {exp.expiry} ({exp.dte}d)
              </Label>
            </div>
          ))}
        </div>
      </div>

      {/* Comparison Table */}
      <div className="overflow-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b-2 border-border">
              <th className="text-left py-3 px-4 font-semibold bg-muted">Expiry</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">DTE</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">ATM IV</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">Call Volume</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">Put Volume</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">P/C Ratio</th>
              <th className="text-center py-3 px-4 font-semibold bg-muted">Open Interest</th>
            </tr>
          </thead>
          <tbody>
            {selectedData.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-8 text-muted-foreground">
                  Select at least one expiry to compare
                </td>
              </tr>
            ) : (
              selectedData.map((data, idx) => (
                <tr
                  key={data.expiry}
                  className={`border-b border-border hover:bg-accent/10 transition-colors ${
                    idx % 2 === 0 ? "bg-card" : "bg-muted/20"
                  }`}
                >
                  <td className="py-4 px-4 font-semibold">{data.expiry}</td>
                  <td className="py-4 px-4 text-center number-mono">{data.dte}</td>
                  <td className="py-4 px-4 text-center">
                    <span className={`font-bold number-mono ${data.atmIV > 28 ? "text-destructive" : "text-foreground"}`}>
                      {data.atmIV.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-4 px-4 text-center">
                    <span className="font-semibold number-mono text-bull">
                      {data.callVolume.toLocaleString()}
                    </span>
                  </td>
                  <td className="py-4 px-4 text-center">
                    <span className="font-semibold number-mono text-bear">
                      {data.putVolume.toLocaleString()}
                    </span>
                  </td>
                  <td className="py-4 px-4 text-center">
                    <Badge
                      variant={data.pcRatio > 1 ? "default" : "secondary"}
                      className={
                        data.pcRatio > 1
                          ? "bg-bear/20 text-bear border-bear/30"
                          : "bg-bull/20 text-bull border-bull/30"
                      }
                    >
                      {data.pcRatio.toFixed(2)}
                    </Badge>
                  </td>
                  <td className="py-4 px-4 text-center font-semibold number-mono">
                    {data.openInterest.toLocaleString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Summary Stats */}
      {selectedData.length > 0 && (
        <div className="mt-6 pt-6 border-t border-border">
          <div className="grid grid-cols-4 gap-4">
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Avg ATM IV</div>
              <div className="text-2xl font-bold number-mono">
                {(selectedData.reduce((sum, d) => sum + d.atmIV, 0) / selectedData.length).toFixed(1)}%
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Total Call Volume</div>
              <div className="text-2xl font-bold number-mono text-bull">
                {selectedData.reduce((sum, d) => sum + d.callVolume, 0).toLocaleString()}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Total Put Volume</div>
              <div className="text-2xl font-bold number-mono text-bear">
                {selectedData.reduce((sum, d) => sum + d.putVolume, 0).toLocaleString()}
              </div>
            </Card>
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Avg P/C Ratio</div>
              <div className="text-2xl font-bold number-mono">
                {(selectedData.reduce((sum, d) => sum + d.pcRatio, 0) / selectedData.length).toFixed(2)}
              </div>
            </Card>
          </div>
        </div>
      )}
    </Card>
  );
}
