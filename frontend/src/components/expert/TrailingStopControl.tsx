import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { AlertCircle, TrendingUp, TrendingDown } from "lucide-react";
import { calculateStopLevel, calculateStopDistance, type StopLossConfig, type PositionInfo } from "@/utils/stopCalculations";

interface TrailingStopControlProps {
  position?: {
    symbol: string;
    side: 'long' | 'short';
    entryPrice: number;
    currentPrice: number;
    quantity: number;
  };
  atrValue?: number;
  onApply?: (config: StopLossConfig) => void;
}

export function TrailingStopControl({ position, atrValue = 2.5, onApply }: TrailingStopControlProps) {
  const [stopType, setStopType] = useState<'fixed' | 'trailing'>('trailing');
  const [fixedPrice, setFixedPrice] = useState<string>("");
  const [trailingDistance, setTrailingDistance] = useState<string>("1.5");
  const [trailingUnit, setTrailingUnit] = useState<'percent' | 'atr'>('atr');
  const [enableTrailing, setEnableTrailing] = useState(true);

  if (!position) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-muted-foreground" />
            Risk Control
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">No active position to manage</p>
        </CardContent>
      </Card>
    );
  }

  const config: StopLossConfig = {
    type: stopType,
    fixedPrice: stopType === 'fixed' ? parseFloat(fixedPrice) || undefined : undefined,
    trailingDistance: stopType === 'trailing' ? parseFloat(trailingDistance) || 1.5 : undefined,
    trailingUnit,
    atrValue,
  };

  const positionInfo: PositionInfo = {
    side: position.side,
    entryPrice: position.entryPrice,
    currentPrice: position.currentPrice,
    highestPrice: position.side === 'long' ? Math.max(position.currentPrice, position.entryPrice) : undefined,
    lowestPrice: position.side === 'short' ? Math.min(position.currentPrice, position.entryPrice) : undefined,
  };

  const activeStopLevel = calculateStopLevel(positionInfo, config);
  const stopDistance = calculateStopDistance(position.currentPrice, activeStopLevel, atrValue);

  const handleApply = () => {
    if (onApply) {
      onApply(config);
    }
    console.log("Applied stop configuration:", config);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg flex items-center gap-2">
          {position.side === 'long' ? (
            <TrendingUp className="h-5 w-5 text-green-600" />
          ) : (
            <TrendingDown className="h-5 w-5 text-red-600" />
          )}
          Risk Control
          <Badge variant="outline" className="ml-auto">
            {position.symbol}
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Stop Type Selection */}
        <div className="space-y-2">
          <Label>Stop Type</Label>
          <Select value={stopType} onValueChange={(v) => setStopType(v as 'fixed' | 'trailing')}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="fixed">Fixed Stop-Loss</SelectItem>
              <SelectItem value="trailing">Trailing Stop</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Fixed Stop Price */}
        {stopType === 'fixed' && (
          <div className="space-y-2">
            <Label htmlFor="fixedPrice">Stop-Loss Price</Label>
            <Input
              id="fixedPrice"
              type="number"
              step="0.01"
              placeholder={`e.g., ${(position.entryPrice * 0.98).toFixed(2)}`}
              value={fixedPrice}
              onChange={(e) => setFixedPrice(e.target.value)}
            />
          </div>
        )}

        {/* Trailing Stop Configuration */}
        {stopType === 'trailing' && (
          <>
            <div className="flex items-center justify-between">
              <Label htmlFor="enableTrailing">Enable Trailing Stop</Label>
              <Switch
                id="enableTrailing"
                checked={enableTrailing}
                onCheckedChange={setEnableTrailing}
              />
            </div>

            {enableTrailing && (
              <>
                <div className="space-y-2">
                  <Label htmlFor="trailingDistance">Trailing Distance</Label>
                  <div className="flex gap-2">
                    <Input
                      id="trailingDistance"
                      type="number"
                      step="0.1"
                      placeholder="1.5"
                      value={trailingDistance}
                      onChange={(e) => setTrailingDistance(e.target.value)}
                      className="flex-1"
                    />
                    <Select value={trailingUnit} onValueChange={(v) => setTrailingUnit(v as 'percent' | 'atr')}>
                      <SelectTrigger className="w-24">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="atr">ATR</SelectItem>
                        <SelectItem value="percent">%</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    {trailingUnit === 'atr' 
                      ? `Current ATR: ${atrValue.toFixed(2)}`
                      : 'Percentage of price'
                    }
                  </p>
                </div>
              </>
            )}
          </>
        )}

        {/* Active Stop Level Display */}
        <div className="p-3 bg-muted/50 rounded-lg space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">Active Stop Level</span>
            <span className="text-lg font-bold">${activeStopLevel.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Distance from current</span>
            <div className="text-right">
              <div className={position.side === 'long' ? 'text-red-600' : 'text-green-600'}>
                -{stopDistance.percent.toFixed(2)}%
              </div>
              {stopDistance.atr && (
                <div className="text-xs text-muted-foreground">
                  {stopDistance.atr.toFixed(2)} ATR
                </div>
              )}
            </div>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Risk per share</span>
            <span className="font-medium">${stopDistance.dollars.toFixed(2)}</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">Total risk ({position.quantity} shares)</span>
            <span className="font-bold text-red-600">
              ${(stopDistance.dollars * position.quantity).toFixed(2)}
            </span>
          </div>
        </div>

        {/* Apply Button */}
        <Button onClick={handleApply} className="w-full">
          Apply to Position
        </Button>

        {/* Info Text */}
        <p className="text-xs text-muted-foreground">
          {position.side === 'long' 
            ? 'For long positions, the stop moves up as price rises but never moves down.'
            : 'For short positions, the stop moves down as price falls but never moves up.'
          }
        </p>
      </CardContent>
    </Card>
  );
}
