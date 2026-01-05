import { useState } from "react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Play } from "lucide-react";
import { BattlegroundReplay } from "./BattlegroundReplay";

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

interface BattlegroundHistoryProps {
  sessions: BattleSession[];
}

export const BattlegroundHistory = ({ sessions }: BattlegroundHistoryProps) => {
  const [replayOpen, setReplayOpen] = useState(false);
  const [selectedSession, setSelectedSession] = useState<BattleSession | null>(null);

  const handleReplayClick = (session: BattleSession) => {
    setSelectedSession(session);
    setReplayOpen(true);
  };

  // Calculate statistics
  const completedSessions = sessions.filter(s => s.outcome !== 'active');
  const wins = completedSessions.filter(s => s.outcome === 'win').length;
  const losses = completedSessions.filter(s => s.outcome === 'loss').length;
  const winRate = completedSessions.length > 0 ? (wins / completedSessions.length) * 100 : 0;

  // Status pattern analysis
  const statusPatterns = {
    DEFENDING: { wins: 0, total: 0 },
    WEAKENING: { wins: 0, total: 0 },
    HOLDING: { wins: 0, total: 0 },
    BROKEN: { wins: 0, total: 0 },
  };

  completedSessions.forEach(session => {
    session.statusSequence.forEach(status => {
      if (statusPatterns[status as keyof typeof statusPatterns]) {
        statusPatterns[status as keyof typeof statusPatterns].total++;
        if (session.outcome === 'win') {
          statusPatterns[status as keyof typeof statusPatterns].wins++;
        }
      }
    });
  });

  const getSuccessRate = (pattern: keyof typeof statusPatterns) => {
    const data = statusPatterns[pattern];
    return data.total > 0 ? (data.wins / data.total) * 100 : 0;
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case "DEFENDING": return "text-blue-500";
      case "HOLDING": return "text-green-500";
      case "WEAKENING": return "text-orange-500";
      case "BROKEN": return "text-red-500";
      default: return "text-gray-500";
    }
  };

  const recentBattles = completedSessions.slice(-5).reverse();

  return (
    <>
      <BattlegroundReplay 
        open={replayOpen}
        onOpenChange={setReplayOpen}
        session={selectedSession}
      />
      
      <Card className="p-4">
        <h3 className="text-lg font-semibold mb-4">📊 Battle Performance</h3>
      
        {/* Overall Stats */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-green-500">{wins}</div>
            <div className="text-xs text-muted-foreground">Wins</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-500">{losses}</div>
            <div className="text-xs text-muted-foreground">Losses</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold">{winRate.toFixed(0)}%</div>
            <div className="text-xs text-muted-foreground">Win Rate</div>
          </div>
        </div>

        {/* Status Pattern Success Rates */}
        <div className="space-y-3 mb-4">
          <div className="text-sm font-semibold mb-2">Status Pattern Success Rates</div>
          
          {(Object.keys(statusPatterns) as Array<keyof typeof statusPatterns>).map(status => {
            const successRate = getSuccessRate(status);
            const total = statusPatterns[status].total;
            
            return (
              <div key={status} className="space-y-1">
                <div className="flex justify-between items-center text-xs">
                  <span className={`font-mono ${getStatusColor(status)}`}>{status}</span>
                  <span className="text-muted-foreground">
                    {successRate.toFixed(0)}% ({statusPatterns[status].wins}/{total})
                  </span>
                </div>
                <Progress value={successRate} className="h-2" />
              </div>
            );
          })}
        </div>

        {/* Recent Sessions */}
        <div className="space-y-2">
          <div className="text-sm font-semibold mb-2">Recent Battles</div>
          {recentBattles.length > 0 ? (
            <div className="space-y-2 max-h-48 overflow-y-auto">
              {recentBattles.map((session) => (
                <div 
                  key={session.id}
                  className="flex items-center justify-between p-2 rounded bg-muted/50 hover:bg-muted transition-colors"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant={session.outcome === 'win' ? 'default' : 'destructive'}>
                      {session.outcome === 'win' ? 'WIN' : 'LOSS'}
                    </Badge>
                    <span className="text-xs font-mono">
                      {session.symbol} @ ${session.priceLevel.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-foreground">
                      {session.finalStatus} • {session.duration}s
                    </div>
                    {session.priceTicks && session.priceTicks.length > 0 && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleReplayClick(session)}
                        className="h-6 px-2"
                      >
                        <Play className="h-3 w-3" />
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center text-sm text-muted-foreground py-4">
              No completed battles yet. Engage Battleground Mode to start tracking!
            </div>
          )}
        </div>
      </Card>
    </>
  );
};
