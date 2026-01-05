import { useState, useEffect, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Volume2, VolumeX, CheckCircle, XCircle, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BattlegroundHistory } from "./BattlegroundHistory";
import { useToast } from "@/hooks/use-toast";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Slider } from "@/components/ui/slider";

type BattleStatus = "TESTING" | "DEFENDING" | "WEAKENING" | "BROKEN" | "HOLDING";

interface PriceTick {
  timestamp: number;
  price: number;
  status: BattleStatus;
  conviction: number;
}

interface StatusChange {
  timestamp: number;
  fromStatus: BattleStatus;
  toStatus: BattleStatus;
}

interface BattleSession {
  id: string;
  timestamp: Date;
  symbol: string;
  priceLevel: number;
  outcome: 'win' | 'loss' | 'active';
  finalStatus: string;
  statusSequence: string[];
  duration: number;
  priceTicks?: PriceTick[];
  statusChanges?: StatusChange[];
  autoDetectionTrigger?: {
    timestamp: number;
    reason: string;
  };
}

interface BattlegroundModeProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  symbol: string;
  priceLevel: number;
  currentPrice: number;
  sessions: BattleSession[];
  onSessionComplete: (session: BattleSession) => void;
}

interface DetectionThresholds {
  bouncePercent: number;      // Percentage above level for win (default 0.3)
  breakPercent: number;        // Percentage below level for loss (default 0.3)
  sustainedTickCount: number;  // Number of consecutive ticks to confirm (default 5)
  testDistance: number;        // Dollar amount to consider "tested" (default 0.20)
}

const DEFAULT_THRESHOLDS: DetectionThresholds = {
  bouncePercent: 0.3,
  breakPercent: 0.3,
  sustainedTickCount: 5,
  testDistance: 0.20
};

const loadThresholds = (): DetectionThresholds => {
  const stored = localStorage.getItem('battleground-thresholds');
  if (stored) {
    try {
      const parsed = JSON.parse(stored);
      return {
        bouncePercent: Number(parsed.bouncePercent) || DEFAULT_THRESHOLDS.bouncePercent,
        breakPercent: Number(parsed.breakPercent) || DEFAULT_THRESHOLDS.breakPercent,
        sustainedTickCount: Number(parsed.sustainedTickCount) || DEFAULT_THRESHOLDS.sustainedTickCount,
        testDistance: Number(parsed.testDistance) || DEFAULT_THRESHOLDS.testDistance,
      };
    } catch {
      return DEFAULT_THRESHOLDS;
    }
  }
  return DEFAULT_THRESHOLDS;
};

const saveThresholds = (thresholds: DetectionThresholds) => {
  localStorage.setItem('battleground-thresholds', JSON.stringify(thresholds));
};

export const BattlegroundMode = ({
  open, 
  onOpenChange, 
  symbol, 
  priceLevel,
  currentPrice: initialPrice,
  sessions,
  onSessionComplete
}: BattlegroundModeProps) => {
  const { toast } = useToast();
  const [currentPrice, setCurrentPrice] = useState(initialPrice);
  const [status, setStatus] = useState<BattleStatus>("TESTING");
  const [conviction, setConviction] = useState(50); // 0 = Bears, 100 = Bulls
  const [timeToClose, setTimeToClose] = useState(60);
  const [priceHistory, setPriceHistory] = useState<number[]>([initialPrice]);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [wickData, setWickData] = useState({ bullish: 0, bearish: 0 });
  const [sessionId] = useState(`battle_${Date.now()}`);
  const [sessionStartTime] = useState(Date.now());
  const [statusHistory, setStatusHistory] = useState<BattleStatus[]>([]);
  const [battleActive, setBattleActive] = useState(true);
  const [lowestPrice, setLowestPrice] = useState(initialPrice);
  const [highestPrice, setHighestPrice] = useState(initialPrice);
  const [priceTicks, setPriceTicks] = useState<PriceTick[]>([]);
  const [statusChanges, setStatusChanges] = useState<StatusChange[]>([]);
  const [thresholds, setThresholds] = useState<DetectionThresholds>(loadThresholds());
  const [settingsOpen, setSettingsOpen] = useState(false);
  
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const lastStatusRef = useRef<BattleStatus>(status);
  const autoCompleteTriggeredRef = useRef(false);

  const handleThresholdChange = (key: keyof DetectionThresholds, value: number) => {
    const newThresholds = { ...thresholds, [key]: value };
    setThresholds(newThresholds);
    saveThresholds(newThresholds);
  };

  // Initialize audio
  useEffect(() => {
    audioRef.current = new Audio();
  }, []);

  // Simulate real-time price updates
  useEffect(() => {
    if (!open) return;

    const interval = setInterval(() => {
      setCurrentPrice(prev => {
        const volatility = 0.15;
        const trend = Math.random() > 0.5 ? 1 : -1;
        const change = (Math.random() * volatility) * trend;
        const newPrice = prev + change;
        
        // Track highest and lowest prices
        setHighestPrice(h => Math.max(h, newPrice));
        setLowestPrice(l => Math.min(l, newPrice));
        
        setPriceHistory(hist => [...hist.slice(-120), newPrice]);
        return newPrice;
      });

      setTimeToClose(prev => {
        if (prev <= 0) return 60;
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [open]);

  // Calculate status and conviction
  useEffect(() => {
    if (!open) return;

    const distanceToLevel = currentPrice - priceLevel;
    const percentDistance = (distanceToLevel / priceLevel) * 100;
    
    // Analyze recent price action
    const recentPrices = priceHistory.slice(-10);
    const wicksBelow = recentPrices.filter((p, i) => {
      if (i === 0) return false;
      return p < priceLevel && recentPrices[i - 1] >= priceLevel;
    }).length;
    
    const wicksAbove = recentPrices.filter((p, i) => {
      if (i === 0) return false;
      return p > priceLevel && recentPrices[i - 1] <= priceLevel;
    }).length;

    setWickData({ bullish: wicksBelow * 10, bearish: wicksAbove * 10 });

    // Determine status
    let newStatus: BattleStatus = "TESTING";
    let newConviction = 50;

    if (Math.abs(percentDistance) < 0.05) {
      newStatus = "TESTING";
      newConviction = 50 + (wicksBelow - wicksAbove) * 5;
    } else if (distanceToLevel > 0 && distanceToLevel < 0.5) {
      newStatus = "HOLDING";
      newConviction = 60 + wicksBelow * 5;
    } else if (distanceToLevel < 0 && distanceToLevel > -0.3) {
      if (wicksBelow > wicksAbove * 2) {
        newStatus = "DEFENDING";
        newConviction = 55 + wicksBelow * 5;
      } else {
        newStatus = "WEAKENING";
        newConviction = 40 - wicksAbove * 5;
      }
    } else if (distanceToLevel < -0.5) {
      newStatus = "BROKEN";
      newConviction = 20;
      
      // Play alert sound on break
      if (lastStatusRef.current !== "BROKEN" && audioEnabled && audioRef.current) {
        const alertTone = new AudioContext();
        const oscillator = alertTone.createOscillator();
        const gainNode = alertTone.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(alertTone.destination);
        
        oscillator.frequency.value = 800;
        oscillator.type = 'sine';
        gainNode.gain.setValueAtTime(0.3, alertTone.currentTime);
        gainNode.gain.exponentialRampToValueAtTime(0.01, alertTone.currentTime + 0.5);
        
        oscillator.start(alertTone.currentTime);
        oscillator.stop(alertTone.currentTime + 0.5);
      }
    }

    newConviction = Math.max(0, Math.min(100, newConviction));
    
    setStatus(newStatus);
    setConviction(newConviction);
    
    // Track status changes
    if (lastStatusRef.current !== newStatus) {
      setStatusHistory(prev => [...prev, newStatus]);
      setStatusChanges(prev => [...prev, {
        timestamp: Date.now(),
        fromStatus: lastStatusRef.current,
        toStatus: newStatus
      }]);
    }
    
    // Record price tick with status and conviction
    setPriceTicks(prev => [...prev, {
      timestamp: Date.now(),
      price: currentPrice,
      status: newStatus,
      conviction: newConviction
    }]);
    
    lastStatusRef.current = newStatus;
  }, [currentPrice, priceHistory, priceLevel, open, audioEnabled]);

  // Automatic outcome detection with configurable thresholds
  useEffect(() => {
    if (!open || !battleActive || autoCompleteTriggeredRef.current) return;

    const distanceToLevel = currentPrice - priceLevel;
    const percentFromLevel = (Math.abs(distanceToLevel) / priceLevel) * 100;
    
    // Win condition: Price bounced significantly above the level
    // Must have tested the level (gotten close) and then bounced back up
    const testedLevel = lowestPrice <= priceLevel + thresholds.testDistance;
    const bouncedSignificantly = currentPrice > priceLevel + (priceLevel * (thresholds.bouncePercent / 100));
    const sustainedBounce = priceHistory.slice(-thresholds.sustainedTickCount).every(p => p > priceLevel);
    
    if (testedLevel && bouncedSignificantly && sustainedBounce && percentFromLevel > thresholds.bouncePercent) {
      autoCompleteTriggeredRef.current = true;
      const reason = `Price bounced ${percentFromLevel.toFixed(2)}% above level after testing it at $${lowestPrice.toFixed(2)} (threshold: ${thresholds.bouncePercent}%)`;
      setTimeout(() => handleBattleEnd('win', true, reason), 500);
      return;
    }
    
    // Loss condition: Price broke through and continued downward
    // Must have broken below the level and continued dropping
    const brokeThroughLevel = currentPrice < priceLevel - (thresholds.testDistance / 2);
    const continuedDrop = currentPrice < priceLevel - (priceLevel * (thresholds.breakPercent / 100));
    const sustainedBreak = priceHistory.slice(-thresholds.sustainedTickCount).every(p => p < priceLevel - (thresholds.testDistance / 4));
    const droppedFromHigh = highestPrice > priceLevel;
    
    if (brokeThroughLevel && continuedDrop && sustainedBreak && droppedFromHigh && percentFromLevel > thresholds.breakPercent) {
      autoCompleteTriggeredRef.current = true;
      const reason = `Price broke through and dropped ${percentFromLevel.toFixed(2)}% below level, continuing downward from high of $${highestPrice.toFixed(2)} (threshold: ${thresholds.breakPercent}%)`;
      setTimeout(() => handleBattleEnd('loss', true, reason), 500);
      return;
    }
  }, [currentPrice, priceHistory, priceLevel, open, battleActive, lowestPrice, highestPrice, thresholds]);

  const getStatusColor = (s: BattleStatus) => {
    switch (s) {
      case "TESTING": return "bg-yellow-500";
      case "DEFENDING": return "bg-blue-500";
      case "HOLDING": return "bg-green-500";
      case "WEAKENING": return "bg-orange-500";
      case "BROKEN": return "bg-red-500 animate-pulse";
      default: return "bg-gray-500";
    }
  };

  const getStatusDescription = (s: BattleStatus) => {
    switch (s) {
      case "TESTING": return "Price is touching the line, wicks are forming";
      case "DEFENDING": return "Long wicks forming below - buyers stepping in!";
      case "HOLDING": return "Level is holding strong, bouncing up";
      case "WEAKENING": return "Candle closed below - shot across the bow";
      case "BROKEN": return "LEVEL BROKEN - Battle lost!";
      default: return "";
    }
  };

  const distanceToLevel = currentPrice - priceLevel;
  const nextTargetUp = priceLevel + 1.89;
  const nextTargetDown = priceLevel - 1.06;

  const handleBattleEnd = (outcome: 'win' | 'loss', isAutomatic = false, autoReason?: string) => {
    if (!battleActive) return; // Prevent duplicate calls
    
    const duration = Math.floor((Date.now() - sessionStartTime) / 1000);
    const session: BattleSession = {
      id: sessionId,
      timestamp: new Date(),
      symbol,
      priceLevel,
      outcome,
      finalStatus: status,
      statusSequence: [...new Set(statusHistory)],
      duration,
      priceTicks,
      statusChanges,
      autoDetectionTrigger: isAutomatic && autoReason ? {
        timestamp: Date.now(),
        reason: autoReason
      } : undefined
    };
    
    onSessionComplete(session);
    setBattleActive(false);
    
    toast({
      title: outcome === 'win' 
        ? `🎯 Battle Won!${isAutomatic ? ' (Auto-detected)' : ''}` 
        : `💥 Battle Lost${isAutomatic ? ' (Auto-detected)' : ''}`,
      description: `${symbol} @ $${priceLevel.toFixed(2)} - Final status: ${status}`,
      variant: outcome === 'win' ? 'default' : 'destructive'
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl h-[80vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="text-2xl font-bold">
              ⚔️ Battleground Mode: {symbol} @ ${priceLevel.toFixed(2)}
            </DialogTitle>
            <div className="flex items-center gap-2">
              <Popover open={settingsOpen} onOpenChange={setSettingsOpen}>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="icon">
                    <Settings className="h-4 w-4" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80">
                  <div className="space-y-4">
                    <div>
                      <h4 className="font-semibold mb-2">Auto-Detection Settings</h4>
                      <p className="text-xs text-muted-foreground mb-4">
                        Adjust sensitivity for automatic win/loss detection
                      </p>
                    </div>

                    <div className="space-y-3">
                      <div className="space-y-2">
                        <div className="flex justify-between items-center">
                          <Label className="text-xs">Bounce % (Win)</Label>
                          <span className="text-xs font-mono">{thresholds.bouncePercent}%</span>
                        </div>
                        <Slider
                          value={[thresholds.bouncePercent]}
                          onValueChange={(v) => handleThresholdChange('bouncePercent', v[0])}
                          min={0.1}
                          max={1.0}
                          step={0.05}
                          className="w-full"
                        />
                        <p className="text-xs text-muted-foreground">
                          Price must bounce above level by this %
                        </p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex justify-between items-center">
                          <Label className="text-xs">Break % (Loss)</Label>
                          <span className="text-xs font-mono">{thresholds.breakPercent}%</span>
                        </div>
                        <Slider
                          value={[thresholds.breakPercent]}
                          onValueChange={(v) => handleThresholdChange('breakPercent', v[0])}
                          min={0.1}
                          max={1.0}
                          step={0.05}
                          className="w-full"
                        />
                        <p className="text-xs text-muted-foreground">
                          Price must drop below level by this %
                        </p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex justify-between items-center">
                          <Label className="text-xs">Sustained Ticks</Label>
                          <span className="text-xs font-mono">{thresholds.sustainedTickCount}</span>
                        </div>
                        <Slider
                          value={[thresholds.sustainedTickCount]}
                          onValueChange={(v) => handleThresholdChange('sustainedTickCount', v[0])}
                          min={3}
                          max={10}
                          step={1}
                          className="w-full"
                        />
                        <p className="text-xs text-muted-foreground">
                          Consecutive ticks required to confirm
                        </p>
                      </div>

                      <div className="space-y-2">
                        <div className="flex justify-between items-center">
                          <Label className="text-xs">Test Distance ($)</Label>
                          <Input
                            type="number"
                            value={thresholds.testDistance}
                            onChange={(e) => handleThresholdChange('testDistance', parseFloat(e.target.value) || 0.20)}
                            step="0.05"
                            min="0.05"
                            max="1.00"
                            className="w-20 h-7 text-xs"
                          />
                        </div>
                        <p className="text-xs text-muted-foreground">
                          How close price must get to "test" level
                        </p>
                      </div>
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setThresholds(DEFAULT_THRESHOLDS);
                        saveThresholds(DEFAULT_THRESHOLDS);
                      }}
                      className="w-full"
                    >
                      Reset to Defaults
                    </Button>
                  </div>
                </PopoverContent>
              </Popover>
              
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setAudioEnabled(!audioEnabled)}
              >
                {audioEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
              </Button>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 space-y-4 overflow-y-auto">
          {/* Battle Outcome Buttons */}
          {battleActive && (
            <Card className="p-3 bg-muted/50">
              <div className="text-xs text-muted-foreground mb-2 text-center">
                Auto-detection: ±{thresholds.bouncePercent}%/{thresholds.breakPercent}%, {thresholds.sustainedTickCount} ticks | Manual override:
              </div>
              <div className="grid grid-cols-2 gap-3">
                <Button
                  onClick={() => handleBattleEnd('win', false)}
                  className="bg-green-600 hover:bg-green-700"
                  size="sm"
                >
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Mark Win
                </Button>
                <Button
                  onClick={() => handleBattleEnd('loss', false)}
                  variant="destructive"
                  size="sm"
                >
                  <XCircle className="h-4 w-4 mr-2" />
                  Mark Loss
                </Button>
              </div>
            </Card>
          )}

          {!battleActive && (
            <Card className="p-4 bg-green-500/20 border-green-500/50">
              <div className="text-center">
                <div className="text-lg font-semibold mb-1">✅ Battle Concluded</div>
                <div className="text-sm text-muted-foreground">
                  Review performance statistics below
                </div>
              </div>
            </Card>
          )}
          
          {/* Heartbeat Ticker */}
          <Card className="p-4 bg-black/40">
            <div className="relative h-32">
              <svg className="w-full h-full">
                {/* Price level line */}
                <line
                  x1="0"
                  y1="50%"
                  x2="100%"
                  y2="50%"
                  stroke="hsl(var(--primary))"
                  strokeWidth="3"
                  className="animate-pulse"
                />
                
                {/* Price history line */}
                <polyline
                  points={priceHistory.map((p, i) => {
                    const x = (i / (priceHistory.length - 1)) * 100;
                    const y = 50 - ((p - priceLevel) / priceLevel * 100) * 200;
                    return `${x}%,${Math.max(0, Math.min(100, y))}%`;
                  }).join(" ")}
                  fill="none"
                  stroke="hsl(var(--foreground))"
                  strokeWidth="2"
                />
              </svg>
              
              <div className="absolute top-2 left-2 text-sm font-mono">
                Level: ${priceLevel.toFixed(2)}
              </div>
              <div className="absolute top-2 right-2 text-sm font-mono font-bold">
                ${currentPrice.toFixed(2)}
              </div>
            </div>
          </Card>

          {/* Breach Status */}
          <Card className="p-6">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-muted-foreground">STATUS:</span>
                <Badge className={`text-lg px-4 py-1 ${getStatusColor(status)}`}>
                  {status}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">{getStatusDescription(status)}</p>
            </div>
          </Card>

          {/* Tug-of-War Meter */}
          <Card className="p-6">
            <div className="space-y-3">
              <div className="flex justify-between text-sm font-semibold">
                <span className="text-red-500">🐻 BEARS</span>
                <span className="text-green-500">BULLS 🐂</span>
              </div>
              
              <div className="relative">
                <Progress value={conviction} className="h-6" />
                <div 
                  className="absolute top-0 left-1/2 transform -translate-x-1/2 h-6 w-1 bg-foreground/50"
                />
                <div 
                  className="absolute top-0 h-6 w-2 bg-foreground transform -translate-x-1/2 transition-all duration-300"
                  style={{ left: `${conviction}%` }}
                />
              </div>
              
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Bearish Pressure: {(100 - conviction).toFixed(0)}%</span>
                <span>Bullish Pressure: {conviction.toFixed(0)}%</span>
              </div>
            </div>
          </Card>

          {/* At-a-Glance Data */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Time to Close</div>
              <div className="text-2xl font-mono font-bold">
                {Math.floor(timeToClose / 60)}:{(timeToClose % 60).toString().padStart(2, '0')}
              </div>
            </Card>

            <Card className={`p-4 ${distanceToLevel < 0 ? 'bg-red-500/20' : 'bg-green-500/20'}`}>
              <div className="text-xs text-muted-foreground mb-1">Distance to Line</div>
              <div className="text-2xl font-mono font-bold">
                {distanceToLevel >= 0 ? '+' : ''}{distanceToLevel.toFixed(2)}
              </div>
            </Card>

            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Next Target (Up)</div>
              <div className="text-2xl font-mono font-bold text-green-500">
                ${nextTargetUp.toFixed(2)}
              </div>
            </Card>

            <Card className="p-4">
              <div className="text-xs text-muted-foreground mb-1">Next Target (Down)</div>
              <div className="text-2xl font-mono font-bold text-red-500">
                ${nextTargetDown.toFixed(2)}
              </div>
            </Card>
          </div>

          {/* Wick Analysis */}
          <Card className="p-4">
            <div className="text-sm font-semibold mb-2">Wick Formation</div>
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Bullish Wicks (Buyers):</span>
                <div className="flex items-center gap-2">
                  <Progress value={wickData.bullish} className="h-2 w-24" />
                  <span className="text-xs font-mono">{wickData.bullish}%</span>
                </div>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-xs text-muted-foreground">Bearish Wicks (Sellers):</span>
                <div className="flex items-center gap-2">
                  <Progress value={wickData.bearish} className="h-2 w-24" />
                  <span className="text-xs font-mono">{wickData.bearish}%</span>
                </div>
              </div>
            </div>
          </Card>

          {/* Performance History */}
          <BattlegroundHistory sessions={sessions} />
        </div>
      </DialogContent>
    </Dialog>
  );
};
