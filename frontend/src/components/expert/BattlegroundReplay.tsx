import { useState, useEffect, useRef } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Play, Pause, RotateCcw, FastForward } from "lucide-react";
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

interface BattlegroundReplayProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  session: BattleSession | null;
}

export const BattlegroundReplay = ({ open, onOpenChange, session }: BattlegroundReplayProps) => {
  const [currentTick, setCurrentTick] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const priceTicks = session?.priceTicks || [];
  const statusChanges = session?.statusChanges || [];
  const autoDetectionTrigger = session?.autoDetectionTrigger;

  useEffect(() => {
    if (isPlaying && currentTick < priceTicks.length - 1) {
      intervalRef.current = setInterval(() => {
        setCurrentTick(prev => {
          if (prev >= priceTicks.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 100 / playbackSpeed);
    } else if (!isPlaying && intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isPlaying, currentTick, priceTicks.length, playbackSpeed]);

  const handleReset = () => {
    setIsPlaying(false);
    setCurrentTick(0);
  };

  const handleSliderChange = (value: number[]) => {
    setCurrentTick(value[0]);
    setIsPlaying(false);
  };

  if (!session || !priceTicks.length) {
    return (
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-4xl">
          <DialogHeader>
            <DialogTitle>Battle Replay</DialogTitle>
          </DialogHeader>
          <div className="text-center py-8 text-muted-foreground">
            No replay data available for this session.
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  const currentData = priceTicks[currentTick];
  const visibleHistory = priceTicks.slice(Math.max(0, currentTick - 60), currentTick + 1);
  const elapsedTime = currentData.timestamp - priceTicks[0].timestamp;
  const isAutoDetectionMoment = autoDetectionTrigger && 
    Math.abs(currentData.timestamp - autoDetectionTrigger.timestamp) < 1000;

  const getStatusColor = (s: BattleStatus) => {
    switch (s) {
      case "TESTING": return "bg-yellow-500";
      case "DEFENDING": return "bg-blue-500";
      case "HOLDING": return "bg-green-500";
      case "WEAKENING": return "bg-orange-500";
      case "BROKEN": return "bg-red-500";
      default: return "bg-gray-500";
    }
  };

  const recentStatusChange = statusChanges.find(
    sc => Math.abs(sc.timestamp - currentData.timestamp) < 1000
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-5xl h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center justify-between">
            <DialogTitle className="text-2xl font-bold">
              🎬 Battle Replay: {session.symbol} @ ${session.priceLevel.toFixed(2)}
            </DialogTitle>
            <Badge variant={session.outcome === 'win' ? 'default' : 'destructive'}>
              {session.outcome === 'win' ? '✅ WIN' : '💥 LOSS'}
            </Badge>
          </div>
        </DialogHeader>

        <div className="flex-1 space-y-4 overflow-y-auto">
          {/* Playback Controls */}
          <Card className="p-4 bg-muted/50">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <Button
                  size="icon"
                  variant="outline"
                  onClick={handleReset}
                >
                  <RotateCcw className="h-4 w-4" />
                </Button>
                <Button
                  size="icon"
                  onClick={() => setIsPlaying(!isPlaying)}
                >
                  {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
                </Button>
                <div className="flex items-center gap-2">
                  <FastForward className="h-4 w-4 text-muted-foreground" />
                  <Button
                    size="sm"
                    variant={playbackSpeed === 1 ? "default" : "outline"}
                    onClick={() => setPlaybackSpeed(1)}
                  >
                    1x
                  </Button>
                  <Button
                    size="sm"
                    variant={playbackSpeed === 2 ? "default" : "outline"}
                    onClick={() => setPlaybackSpeed(2)}
                  >
                    2x
                  </Button>
                  <Button
                    size="sm"
                    variant={playbackSpeed === 4 ? "default" : "outline"}
                    onClick={() => setPlaybackSpeed(4)}
                  >
                    4x
                  </Button>
                </div>
                <div className="ml-auto text-sm font-mono text-muted-foreground">
                  {Math.floor(elapsedTime / 1000)}s / {session.duration}s
                </div>
              </div>

              <Slider
                value={[currentTick]}
                onValueChange={handleSliderChange}
                max={priceTicks.length - 1}
                step={1}
                className="w-full"
              />

              <div className="text-xs text-muted-foreground text-center">
                Tick {currentTick + 1} of {priceTicks.length}
              </div>
            </div>
          </Card>

          {/* Auto-Detection Alert */}
          {isAutoDetectionMoment && autoDetectionTrigger && (
            <Card className="p-4 bg-primary/20 border-primary animate-pulse">
              <div className="text-center">
                <div className="text-lg font-bold mb-1">🎯 Auto-Detection Triggered!</div>
                <div className="text-sm">{autoDetectionTrigger.reason}</div>
              </div>
            </Card>
          )}

          {/* Status Change Alert */}
          {recentStatusChange && (
            <Card className="p-3 bg-accent border-accent-foreground/20">
              <div className="text-center text-sm font-semibold">
                Status Changed: {recentStatusChange.fromStatus} → {recentStatusChange.toStatus}
              </div>
            </Card>
          )}

          {/* Price Chart */}
          <Card className="p-4 bg-black/40">
            <div className="relative h-40">
              <svg className="w-full h-full">
                {/* Price level line */}
                <line
                  x1="0"
                  y1="50%"
                  x2="100%"
                  y2="50%"
                  stroke="hsl(var(--primary))"
                  strokeWidth="2"
                  strokeDasharray="4 2"
                />
                
                {/* Price history line */}
                <polyline
                  points={visibleHistory.map((tick, i) => {
                    const x = (i / Math.max(visibleHistory.length - 1, 1)) * 100;
                    const y = 50 - ((tick.price - session.priceLevel) / session.priceLevel * 100) * 300;
                    return `${x}%,${Math.max(0, Math.min(100, y))}%`;
                  }).join(" ")}
                  fill="none"
                  stroke="hsl(var(--foreground))"
                  strokeWidth="2"
                />

                {/* Current price marker */}
                {visibleHistory.length > 0 && (
                  <circle
                    cx="100%"
                    cy={Math.max(0, Math.min(100, 50 - ((currentData.price - session.priceLevel) / session.priceLevel * 100) * 300)) + "%"}
                    r="4"
                    fill="hsl(var(--primary))"
                    className="animate-pulse"
                  />
                )}
              </svg>
              
              <div className="absolute top-2 left-2 text-xs font-mono text-muted-foreground">
                Level: ${session.priceLevel.toFixed(2)}
              </div>
              <div className="absolute top-2 right-2 text-sm font-mono font-bold">
                ${currentData.price.toFixed(2)}
              </div>
            </div>
          </Card>

          {/* Current Status */}
          <Card className="p-6">
            <div className="space-y-3">
              <div className="flex items-center gap-3">
                <span className="text-sm font-semibold text-muted-foreground">STATUS:</span>
                <Badge className={`text-lg px-4 py-1 ${getStatusColor(currentData.status)}`}>
                  {currentData.status}
                </Badge>
              </div>
            </div>
          </Card>

          {/* Conviction Meter */}
          <Card className="p-6">
            <div className="space-y-3">
              <div className="flex justify-between text-sm font-semibold">
                <span className="text-red-500">🐻 BEARS</span>
                <span className="text-green-500">BULLS 🐂</span>
              </div>
              
              <div className="relative">
                <Progress value={currentData.conviction} className="h-6" />
                <div 
                  className="absolute top-0 left-1/2 transform -translate-x-1/2 h-6 w-1 bg-foreground/50"
                />
                <div 
                  className="absolute top-0 h-6 w-2 bg-foreground transform -translate-x-1/2 transition-all duration-300"
                  style={{ left: `${currentData.conviction}%` }}
                />
              </div>
              
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Bearish: {(100 - currentData.conviction).toFixed(0)}%</span>
                <span>Bullish: {currentData.conviction.toFixed(0)}%</span>
              </div>
            </div>
          </Card>

          {/* Timeline of Status Changes */}
          <Card className="p-4">
            <div className="text-sm font-semibold mb-3">Status Timeline</div>
            <div className="space-y-2 max-h-32 overflow-y-auto">
              {statusChanges.map((change, idx) => {
                const isPast = change.timestamp <= currentData.timestamp;
                return (
                  <div 
                    key={idx}
                    className={`text-xs p-2 rounded ${isPast ? 'bg-muted' : 'bg-muted/30 text-muted-foreground'}`}
                  >
                    <span className="font-mono">{Math.floor((change.timestamp - priceTicks[0].timestamp) / 1000)}s</span>
                    {" → "}
                    <span className="font-semibold">{change.fromStatus} → {change.toStatus}</span>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      </DialogContent>
    </Dialog>
  );
};
