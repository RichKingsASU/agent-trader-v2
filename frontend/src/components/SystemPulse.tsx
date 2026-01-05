import { useEffect, useState } from "react";
import { getFirestore, onSnapshot, Timestamp } from "firebase/firestore";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Activity, AlertCircle, CheckCircle2, Clock } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { tenantDoc } from "@/lib/tenancy/firestore";

interface AccountSnapshot {
  updated_at?: Timestamp;
  updated_at_iso?: string;
  equity?: number;
  broker?: string;
}

export const SystemPulse = () => {
  const { tenantId } = useAuth();
  const [accountSnapshot, setAccountSnapshot] = useState<AccountSnapshot | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [timeSinceSync, setTimeSinceSync] = useState<number | null>(null);

  // Listen to account updates from Firestore
  useEffect(() => {
    if (!tenantId) {
      setIsLoading(false);
      return;
    }

    const db = getFirestore();
    const docRef = tenantDoc(db, tenantId, "accounts", "primary");
    
    const unsubscribe = onSnapshot(
      docRef,
      (snapshot) => {
        if (snapshot.exists()) {
          setAccountSnapshot(snapshot.data() as AccountSnapshot);
        } else {
          setAccountSnapshot(null);
        }
        setIsLoading(false);
      },
      (error) => {
        console.error("Error fetching account snapshot:", error);
        setAccountSnapshot(null);
        setIsLoading(false);
      }
    );

    return () => unsubscribe();
  }, [tenantId]);

  // Update time since sync every second
  useEffect(() => {
    const interval = setInterval(() => {
      if (accountSnapshot?.updated_at) {
        const lastUpdate = accountSnapshot.updated_at.toDate();
        const now = new Date();
        const diffInSeconds = Math.floor((now.getTime() - lastUpdate.getTime()) / 1000);
        setTimeSinceSync(diffInSeconds);
      } else {
        setTimeSinceSync(null);
      }
    }, 1000);

    return () => clearInterval(interval);
  }, [accountSnapshot]);

  const getStatus = () => {
    if (isLoading) return "loading";
    if (!accountSnapshot || timeSinceSync === null) return "unknown";
    if (timeSinceSync < 120) return "live"; // < 2 minutes
    if (timeSinceSync < 300) return "stale"; // < 5 minutes
    return "offline";
  };

  const formatTimeSince = (seconds: number | null): string => {
    if (seconds === null) return "Unknown";
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s ago`;
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m ago`;
  };

  const status = getStatus();

  return (
    <Card className="glass-card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-primary" />
          <h3 className="text-sm font-bold text-foreground uppercase tracking-wider ui-label">
            System Pulse
          </h3>
        </div>
        
        {status === "live" && (
          <Badge className="neon-border-green bg-bull/20 text-bull border-bull animate-pulse">
            <CheckCircle2 className="h-3 w-3 mr-1" />
            LIVE
          </Badge>
        )}
        
        {status === "stale" && (
          <Badge className="bg-warning/20 text-warning border-warning border">
            <Clock className="h-3 w-3 mr-1" />
            STALE
          </Badge>
        )}
        
        {status === "offline" && (
          <Badge className="neon-border-red bg-bear/20 text-bear border-bear">
            <AlertCircle className="h-3 w-3 mr-1" />
            OFFLINE
          </Badge>
        )}
        
        {status === "loading" && (
          <Badge className="bg-muted text-muted-foreground border border-muted-foreground/20">
            Loading...
          </Badge>
        )}
        
        {status === "unknown" && (
          <Badge className="bg-muted text-muted-foreground border border-muted-foreground/20">
            <AlertCircle className="h-3 w-3 mr-1" />
            UNKNOWN
          </Badge>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex justify-between items-center text-sm">
          <span className="text-muted-foreground ui-label">Account Sync</span>
          <span className="number-mono font-semibold text-foreground">
            {accountSnapshot?.broker?.toUpperCase() || "N/A"}
          </span>
        </div>
        
        <div className="flex justify-between items-center text-sm">
          <span className="text-muted-foreground ui-label">Last Heartbeat</span>
          <span className={`number-mono font-semibold ${
            status === "live" ? "text-bull neon-glow-green" : 
            status === "stale" ? "text-warning" : 
            "text-bear"
          }`}>
            {formatTimeSince(timeSinceSync)}
          </span>
        </div>

        {accountSnapshot?.updated_at_iso && (
          <div className="text-xs text-muted-foreground mt-2 pt-2 border-t border-white/10">
            <div className="ui-label">Timestamp</div>
            <div className="number-mono mt-1">
              {new Date(accountSnapshot.updated_at_iso).toLocaleString()}
            </div>
          </div>
        )}

        {status === "live" && (
          <div className="mt-3 p-2 rounded-md bg-bull/10 border border-bull/30">
            <p className="text-xs text-bull ui-label">
              ✓ System is operational. Account data is being synchronized.
            </p>
          </div>
        )}

        {(status === "offline" || status === "stale") && (
          <div className="mt-3 p-2 rounded-md bg-bear/10 border border-bear/30">
            <p className="text-xs text-bear ui-label">
              ⚠ Account sync may be delayed. Check Firebase Functions.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
};
