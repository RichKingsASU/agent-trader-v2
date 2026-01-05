import { useEffect, useState, useRef } from "react";
import { getFirestore, onSnapshot, Timestamp, query, orderBy, limit } from "firebase/firestore";
import { Card } from "@/components/ui/card";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, TrendingDown } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { tenantCollection, tenantDoc } from "@/lib/tenancy/firestore";

interface EquityDataPoint {
  timestamp: number;
  equity: number;
  date?: string;
}

interface AccountSnapshot {
  updated_at?: Timestamp;
  equity?: number;
}

const CACHE_KEY = "equity_history_cache";
const MAX_HISTORY_POINTS = 100;
const SAMPLE_INTERVAL_MS = 60000; // Sample every 60 seconds

export const EquityChart = () => {
  const { tenantId } = useAuth();
  const [equityHistory, setEquityHistory] = useState<EquityDataPoint[]>([]);
  const [currentEquity, setCurrentEquity] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const lastSampleTime = useRef<number>(0);

  // Load from localStorage on mount (warm cache)
  useEffect(() => {
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      if (cached) {
        const parsed = JSON.parse(cached) as EquityDataPoint[];
        setEquityHistory(parsed);
      }
    } catch (error) {
      console.error("Error loading equity history from cache:", error);
    }
  }, []);

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
          const data = snapshot.data() as AccountSnapshot;
          const equity = data.equity ?? null;
          setCurrentEquity(equity);

          // Sample equity at intervals to build history
          const now = Date.now();
          if (equity !== null && now - lastSampleTime.current >= SAMPLE_INTERVAL_MS) {
            lastSampleTime.current = now;
            
            const newPoint: EquityDataPoint = {
              timestamp: now,
              equity: equity,
              date: new Date(now).toLocaleTimeString(),
            };

            setEquityHistory((prev) => {
              const updated = [...prev, newPoint];
              // Keep only the last MAX_HISTORY_POINTS
              const trimmed = updated.slice(-MAX_HISTORY_POINTS);
              
              // Save to localStorage
              try {
                localStorage.setItem(CACHE_KEY, JSON.stringify(trimmed));
              } catch (error) {
                console.error("Error saving equity history to cache:", error);
              }
              
              return trimmed;
            });
          }
        }
        setIsLoading(false);
      },
      (error) => {
        console.error("Error fetching account snapshot:", error);
        setIsLoading(false);
      }
    );

    return () => unsubscribe();
  }, [tenantId]);

  // Optionally fetch historical equity from Firestore (if available in the future)
  useEffect(() => {
    if (!tenantId) return;

    const db = getFirestore();
    
    // Try to fetch equity history if it exists in Firestore
    // This is a placeholder for future implementation
    // Uncomment and modify when equity history collection is available
    /*
    const historyRef = tenantCollection(db, tenantId, "equity_history");
    const historyQuery = query(historyRef, orderBy("timestamp", "desc"), limit(100));
    
    const unsubscribe = onSnapshot(
      historyQuery,
      (snapshot) => {
        const history: EquityDataPoint[] = [];
        snapshot.forEach((doc) => {
          const data = doc.data();
          history.push({
            timestamp: data.timestamp?.toMillis() ?? 0,
            equity: data.equity ?? 0,
            date: new Date(data.timestamp?.toMillis() ?? 0).toLocaleTimeString(),
          });
        });
        
        // Merge with local history
        if (history.length > 0) {
          setEquityHistory(history.reverse());
        }
      },
      (error) => {
        console.error("Error fetching equity history:", error);
      }
    );

    return () => unsubscribe();
    */
  }, [tenantId]);

  const getEquityChange = () => {
    if (equityHistory.length < 2) return { value: 0, percentage: 0 };
    
    const first = equityHistory[0].equity;
    const last = equityHistory[equityHistory.length - 1].equity;
    const change = last - first;
    const percentage = (change / first) * 100;
    
    return { value: change, percentage };
  };

  const change = getEquityChange();
  const isPositive = change.value >= 0;

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatCompactCurrency = (value: number) => {
    if (value >= 1000000) {
      return `$${(value / 1000000).toFixed(2)}M`;
    } else if (value >= 1000) {
      return `$${(value / 1000).toFixed(1)}K`;
    }
    return formatCurrency(value);
  };

  if (isLoading) {
    return (
      <Card className="glass-card p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-muted rounded w-1/3"></div>
          <div className="h-64 bg-muted rounded"></div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="glass-intense p-6">
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-lg font-bold text-foreground uppercase tracking-wider ui-label">
            Portfolio Equity
          </h3>
          {isPositive ? (
            <TrendingUp className="h-5 w-5 text-bull" />
          ) : (
            <TrendingDown className="h-5 w-5 text-bear" />
          )}
        </div>
        
        <div className="flex items-baseline gap-4">
          <div className="number-mono text-3xl font-bold text-foreground">
            {currentEquity !== null ? formatCurrency(currentEquity) : "N/A"}
          </div>
          
          {equityHistory.length >= 2 && (
            <div className="flex flex-col">
              <span className={`number-mono text-lg font-semibold ${isPositive ? "text-bull neon-glow-green" : "text-bear neon-glow-red"}`}>
                {isPositive ? "+" : ""}{formatCurrency(change.value)}
              </span>
              <span className={`number-mono text-sm ${isPositive ? "text-bull" : "text-bear"}`}>
                ({isPositive ? "+" : ""}{change.percentage.toFixed(2)}%)
              </span>
            </div>
          )}
        </div>
        
        <p className="text-xs text-muted-foreground mt-2 ui-label">
          {equityHistory.length > 0 
            ? `Tracking ${equityHistory.length} data points` 
            : "Building history... Please wait."}
        </p>
      </div>

      {equityHistory.length > 0 ? (
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={equityHistory}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
            <XAxis 
              dataKey="date" 
              stroke="hsl(var(--muted-foreground))"
              tick={{ fontSize: 10 }}
              tickFormatter={(value) => {
                // Show every 5th tick to avoid crowding
                return value;
              }}
            />
            <YAxis 
              stroke="hsl(var(--muted-foreground))"
              tick={{ fontSize: 10 }}
              tickFormatter={(value) => formatCompactCurrency(value)}
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: "hsl(var(--card))",
                border: "1px solid hsl(var(--border))",
                borderRadius: "8px",
                padding: "8px",
              }}
              labelStyle={{ color: "hsl(var(--foreground))", fontWeight: "bold" }}
              itemStyle={{ color: "hsl(var(--primary))" }}
              formatter={(value: number) => [formatCurrency(value), "Equity"]}
            />
            <Line 
              type="monotone" 
              dataKey="equity" 
              stroke="hsl(var(--primary))" 
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 6, fill: "hsl(var(--primary))", stroke: "hsl(var(--background))", strokeWidth: 2 }}
            />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div className="h-64 flex items-center justify-center bg-muted/20 rounded-lg border border-white/5">
          <div className="text-center space-y-2">
            <p className="text-muted-foreground ui-label">No equity history available yet</p>
            <p className="text-xs text-muted-foreground">
              Chart will populate as data is collected
            </p>
          </div>
        </div>
      )}
      
      <div className="mt-4 pt-4 border-t border-white/10">
        <p className="text-xs text-muted-foreground ui-label">
          📊 Live equity tracking with warm cache. Data is sampled every minute and persisted locally.
        </p>
      </div>
    </Card>
  );
};
