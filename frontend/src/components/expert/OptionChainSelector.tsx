import { useState, useMemo } from 'react';
import { TrendingUp, TrendingDown, Filter, Sparkles, ChevronDown } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';

interface OptionContract {
  strike: number;
  type: 'call' | 'put';
  bid: number;
  ask: number;
  last: number;
  volume: number;
  openInterest: number;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  iv: number;
}

interface OptionChainSelectorProps {
  symbol?: string;
  currentPrice?: number;
  loading?: boolean;
  onSelect?: (contract: OptionContract) => void;
}

type AutomationStrategy = 'delta-30' | 'delta-50' | 'atm' | 'high-volume' | 'manual';

export function OptionChainSelector({
  symbol = 'SPY',
  currentPrice = 432.15,
  loading = false,
  onSelect,
}: OptionChainSelectorProps) {
  const [selectedExpiration, setSelectedExpiration] = useState<string>('2024-01-19');
  const [automationStrategy, setAutomationStrategy] = useState<AutomationStrategy>('manual');
  const [maxStrikesFromATM, setMaxStrikesFromATM] = useState<number>(10);
  const [selectedContract, setSelectedContract] = useState<OptionContract | null>(null);

  // Mock expiration dates
  const expirations = [
    '2024-01-19',
    '2024-01-26',
    '2024-02-16',
    '2024-03-15',
    '2024-06-21',
  ];

  // Generate mock options chain
  const generateOptionsChain = (): OptionContract[] => {
    const strikes: OptionContract[] = [];
    const atmStrike = Math.round(currentPrice / 5) * 5; // Round to nearest $5
    const strikeRange = 15;

    for (let i = -strikeRange; i <= strikeRange; i++) {
      const strike = atmStrike + i * 5;
      const distanceFromATM = Math.abs(strike - currentPrice);
      
      // Call option
      const callDelta = strike < currentPrice 
        ? 0.5 + (currentPrice - strike) / (2 * currentPrice) * 0.5
        : 0.5 - (strike - currentPrice) / (2 * currentPrice) * 0.5;
      
      const callPrice = Math.max(0.05, currentPrice - strike + 10 - distanceFromATM * 0.3);
      
      strikes.push({
        strike,
        type: 'call',
        bid: Math.max(0.05, callPrice - 0.10),
        ask: callPrice + 0.10,
        last: callPrice,
        volume: Math.floor(Math.random() * 5000) + 100,
        openInterest: Math.floor(Math.random() * 10000) + 500,
        delta: Math.max(0.01, Math.min(0.99, callDelta)),
        gamma: 0.01 + Math.random() * 0.02,
        theta: -(0.05 + Math.random() * 0.15),
        vega: 0.10 + Math.random() * 0.20,
        iv: 0.15 + Math.random() * 0.25,
      });

      // Put option
      const putDelta = strike > currentPrice
        ? -(0.5 + (strike - currentPrice) / (2 * currentPrice) * 0.5)
        : -(0.5 - (currentPrice - strike) / (2 * currentPrice) * 0.5);
      
      const putPrice = Math.max(0.05, strike - currentPrice + 10 - distanceFromATM * 0.3);
      
      strikes.push({
        strike,
        type: 'put',
        bid: Math.max(0.05, putPrice - 0.10),
        ask: putPrice + 0.10,
        last: putPrice,
        volume: Math.floor(Math.random() * 5000) + 100,
        openInterest: Math.floor(Math.random() * 10000) + 500,
        delta: Math.max(-0.99, Math.min(-0.01, putDelta)),
        gamma: 0.01 + Math.random() * 0.02,
        theta: -(0.05 + Math.random() * 0.15),
        vega: 0.10 + Math.random() * 0.20,
        iv: 0.15 + Math.random() * 0.25,
      });
    }

    return strikes;
  };

  const optionsChain = useMemo(() => generateOptionsChain(), [currentPrice, selectedExpiration]);

  // Filter options based on distance from ATM
  const filteredOptions = useMemo(() => {
    return optionsChain.filter(option => {
      const distanceFromATM = Math.abs(option.strike - currentPrice);
      return distanceFromATM <= maxStrikesFromATM * 5;
    });
  }, [optionsChain, currentPrice, maxStrikesFromATM]);

  // Group by strike
  const strikeGroups = useMemo(() => {
    const groups = new Map<number, { call?: OptionContract; put?: OptionContract }>();
    
    filteredOptions.forEach(option => {
      if (!groups.has(option.strike)) {
        groups.set(option.strike, {});
      }
      const group = groups.get(option.strike)!;
      if (option.type === 'call') {
        group.call = option;
      } else {
        group.put = option;
      }
    });

    return Array.from(groups.entries())
      .sort((a, b) => b[0] - a[0]); // Sort strikes descending
  }, [filteredOptions]);

  // Apply automation strategy
  const getAutomatedSelection = (): OptionContract | null => {
    switch (automationStrategy) {
      case 'delta-30':
        return filteredOptions.find(opt => 
          opt.type === 'call' && Math.abs(opt.delta - 0.30) < 0.05
        ) || null;
      
      case 'delta-50':
        return filteredOptions.find(opt => 
          Math.abs(Math.abs(opt.delta) - 0.50) < 0.05
        ) || null;
      
      case 'atm':
        const atmStrike = filteredOptions.reduce((prev, curr) => 
          Math.abs(curr.strike - currentPrice) < Math.abs(prev.strike - currentPrice) ? curr : prev
        );
        return atmStrike;
      
      case 'high-volume':
        return filteredOptions.reduce((prev, curr) => 
          curr.volume > prev.volume ? curr : prev
        );
      
      default:
        return null;
    }
  };

  const automatedContract = automationStrategy !== 'manual' ? getAutomatedSelection() : null;

  const handleSelectContract = (contract: OptionContract) => {
    setSelectedContract(contract);
    onSelect?.(contract);
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Options Chain</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="h-10 bg-muted/50 rounded animate-pulse" />
            <div className="h-32 bg-muted/50 rounded animate-pulse" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Filter className="h-4 w-4" />
            Options Chain Selector
          </CardTitle>
          <Badge variant="outline">{symbol}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Expiration Selector */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground">Expiration Date</Label>
          <Select value={selectedExpiration} onValueChange={setSelectedExpiration}>
            <SelectTrigger className="bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-50">
              {expirations.map(exp => (
                <SelectItem key={exp} value={exp} className="hover:bg-muted">
                  {exp}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Automation Strategy */}
        <div className="space-y-2">
          <Label className="text-xs text-muted-foreground flex items-center gap-1">
            <Sparkles className="h-3 w-3" />
            Automation Strategy
          </Label>
          <Select value={automationStrategy} onValueChange={(v) => setAutomationStrategy(v as AutomationStrategy)}>
            <SelectTrigger className="bg-background">
              <SelectValue />
            </SelectTrigger>
            <SelectContent className="bg-popover border-border z-50">
              <SelectItem value="manual" className="hover:bg-muted">Manual Selection</SelectItem>
              <SelectItem value="atm" className="hover:bg-muted">At-The-Money (ATM)</SelectItem>
              <SelectItem value="delta-30" className="hover:bg-muted">0.30 Delta (OTM Call)</SelectItem>
              <SelectItem value="delta-50" className="hover:bg-muted">0.50 Delta (Near ATM)</SelectItem>
              <SelectItem value="high-volume" className="hover:bg-muted">Highest Volume</SelectItem>
            </SelectContent>
          </Select>
          {automatedContract && (
            <div className="p-2 bg-primary/10 border border-primary/20 rounded-lg">
              <p className="text-xs text-primary font-medium">
                Suggested: ${automatedContract.strike} {automatedContract.type.toUpperCase()} @ ${automatedContract.last.toFixed(2)}
              </p>
            </div>
          )}
        </div>

        {/* Strike Range Filter */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <Label className="text-xs text-muted-foreground">Strikes from ATM</Label>
            <span className="text-xs font-mono text-foreground">±{maxStrikesFromATM}</span>
          </div>
          <Slider
            value={[maxStrikesFromATM]}
            onValueChange={(v) => setMaxStrikesFromATM(v[0])}
            min={5}
            max={20}
            step={1}
            className="py-2"
          />
        </div>

        {/* Options Chain Display */}
        <Tabs defaultValue="chain" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="chain">Chain View</TabsTrigger>
            <TabsTrigger value="greeks">Greeks View</TabsTrigger>
          </TabsList>
          
          <TabsContent value="chain" className="mt-4 space-y-1 max-h-96 overflow-y-auto">
            {/* Header */}
            <div className="grid grid-cols-7 gap-1 text-xs font-semibold text-muted-foreground pb-2 border-b border-border sticky top-0 bg-card">
              <div className="col-span-2 text-right">CALL</div>
              <div className="text-center">Strike</div>
              <div className="col-span-2">PUT</div>
              <div className="text-center">Vol</div>
              <div className="text-center">OI</div>
            </div>

            {/* Strikes */}
            {strikeGroups.map(([strike, { call, put }]) => {
              const isATM = Math.abs(strike - currentPrice) < 2.5;
              const isSelected = selectedContract?.strike === strike;

              return (
                <div
                  key={strike}
                  className={cn(
                    "grid grid-cols-7 gap-1 text-xs py-1.5 rounded hover:bg-muted/50 transition-colors",
                    isATM && "bg-primary/5 border-l-2 border-primary",
                    isSelected && "bg-primary/10"
                  )}
                >
                  {/* Call */}
                  <button
                    onClick={() => call && handleSelectContract(call)}
                    className={cn(
                      "col-span-2 text-right hover:bg-muted rounded px-1 transition-colors",
                      automatedContract?.strike === strike && automatedContract?.type === 'call' && "bg-primary/20"
                    )}
                  >
                    {call && (
                      <div className="space-y-0.5">
                        <div className="font-mono font-semibold text-foreground">${call.last.toFixed(2)}</div>
                        <div className="text-muted-foreground">Δ {call.delta.toFixed(2)}</div>
                      </div>
                    )}
                  </button>

                  {/* Strike */}
                  <div className="text-center font-mono font-bold text-foreground self-center">
                    ${strike}
                    {isATM && <TrendingUp className="inline h-3 w-3 ml-1 text-primary" />}
                  </div>

                  {/* Put */}
                  <button
                    onClick={() => put && handleSelectContract(put)}
                    className={cn(
                      "col-span-2 text-left hover:bg-muted rounded px-1 transition-colors",
                      automatedContract?.strike === strike && automatedContract?.type === 'put' && "bg-primary/20"
                    )}
                  >
                    {put && (
                      <div className="space-y-0.5">
                        <div className="font-mono font-semibold text-foreground">${put.last.toFixed(2)}</div>
                        <div className="text-muted-foreground">Δ {put.delta.toFixed(2)}</div>
                      </div>
                    )}
                  </button>

                  {/* Volume */}
                  <div className="text-center text-muted-foreground self-center">
                    {call ? call.volume : put?.volume}
                  </div>

                  {/* Open Interest */}
                  <div className="text-center text-muted-foreground self-center">
                    {call ? call.openInterest : put?.openInterest}
                  </div>
                </div>
              );
            })}
          </TabsContent>

          <TabsContent value="greeks" className="mt-4 space-y-2 max-h-96 overflow-y-auto">
            {strikeGroups.map(([strike, { call, put }]) => (
              <div key={strike} className="p-2 border border-border rounded-lg hover:bg-muted/30 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-mono font-bold text-foreground">${strike}</span>
                  <Badge variant="outline" className="text-xs">
                    {Math.abs(strike - currentPrice).toFixed(2)} from ATM
                  </Badge>
                </div>
                
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {call && (
                    <div className="space-y-1 p-2 bg-green-500/10 rounded">
                      <div className="font-semibold text-green-400 flex items-center gap-1">
                        <TrendingUp className="h-3 w-3" />
                        CALL ${call.last.toFixed(2)}
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-muted-foreground">
                        <span>Delta: {call.delta.toFixed(3)}</span>
                        <span>Gamma: {call.gamma.toFixed(3)}</span>
                        <span>Theta: {call.theta.toFixed(3)}</span>
                        <span>Vega: {call.vega.toFixed(3)}</span>
                        <span className="col-span-2">IV: {(call.iv * 100).toFixed(1)}%</span>
                      </div>
                    </div>
                  )}
                  
                  {put && (
                    <div className="space-y-1 p-2 bg-red-500/10 rounded">
                      <div className="font-semibold text-red-400 flex items-center gap-1">
                        <TrendingDown className="h-3 w-3" />
                        PUT ${put.last.toFixed(2)}
                      </div>
                      <div className="grid grid-cols-2 gap-1 text-muted-foreground">
                        <span>Delta: {put.delta.toFixed(3)}</span>
                        <span>Gamma: {put.gamma.toFixed(3)}</span>
                        <span>Theta: {put.theta.toFixed(3)}</span>
                        <span>Vega: {put.vega.toFixed(3)}</span>
                        <span className="col-span-2">IV: {(put.iv * 100).toFixed(1)}%</span>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </TabsContent>
        </Tabs>

        {/* Selected Contract Summary */}
        {selectedContract && (
          <div className="p-3 bg-primary/10 border border-primary/20 rounded-lg space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-primary">Selected Contract</span>
              <Button 
                size="sm" 
                onClick={() => setSelectedContract(null)}
                variant="ghost"
                className="h-6 text-xs"
              >
                Clear
              </Button>
            </div>
            <div className="text-sm font-mono">
              <span className="font-bold">${selectedContract.strike}</span>{' '}
              <span className={selectedContract.type === 'call' ? 'text-green-400' : 'text-red-400'}>
                {selectedContract.type.toUpperCase()}
              </span>{' '}
              @ ${selectedContract.last.toFixed(2)}
            </div>
            <div className="grid grid-cols-4 gap-2 text-xs text-muted-foreground">
              <div>Δ {selectedContract.delta.toFixed(3)}</div>
              <div>Γ {selectedContract.gamma.toFixed(3)}</div>
              <div>Θ {selectedContract.theta.toFixed(3)}</div>
              <div>ν {selectedContract.vega.toFixed(3)}</div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
