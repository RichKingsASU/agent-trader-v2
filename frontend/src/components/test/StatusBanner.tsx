import { useEffect, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Database, CheckCircle, XCircle, Loader2 } from "lucide-react";
import { getFirestore, query, limit, getDocs } from "firebase/firestore";

import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection } from "@/lib/tenancy/firestore";

const StatusBanner = () => {
  const [status, setStatus] = useState<"checking" | "connected" | "error">("checking");
  const { tenantId } = useAuth();

  useEffect(() => {
    const checkConnection = async () => {
      try {
        if (!tenantId) return;
        const db = getFirestore();
        const tradesRef = tenantCollection(db, tenantId, "paper_trades");
        const q = query(tradesRef, limit(1));
        await getDocs(q);
        setStatus("connected");
      } catch {
        setStatus("error");
      }
    };
    checkConnection();
  }, [tenantId]);

  return (
    <Card className="bg-card border-border">
      <CardContent className="py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Database className="h-6 w-6 text-primary" />
            <div>
              <h1 className="text-xl font-bold text-foreground">AgentTrader Hybrid Dashboard</h1>
              <p className="text-sm text-muted-foreground">Data source: Firebase Firestore</p>
            </div>
          </div>
          
          <Badge 
            variant={status === "connected" ? "default" : status === "error" ? "destructive" : "secondary"}
            className="flex items-center gap-1.5"
          >
            {status === "checking" && <Loader2 className="h-3 w-3 animate-spin" />}
            {status === "connected" && <CheckCircle className="h-3 w-3" />}
            {status === "error" && <XCircle className="h-3 w-3" />}
            {status === "checking" ? "Checking..." : status === "connected" ? "Connected" : "Connection Error"}
          </Badge>
        </div>
        
        <p className="text-xs text-muted-foreground mt-2">
          Backend ingestion loops and Alpaca paper auth are assumed running. Collections: market_data_1m, paper_trades, live_quotes
        </p>
      </CardContent>
    </Card>
  );
};

export default StatusBanner;
