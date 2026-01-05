import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { 
  Activity, 
  Zap, 
  Clock, 
  AlertCircle, 
  CheckCircle, 
  XCircle,
  DollarSign,
  TrendingUp,
  Server,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useAuth } from "@/contexts/AuthContext";

interface APILatency {
  service: string;
  avg_ms: number;
  min_ms: number;
  max_ms: number;
  p50_ms: number;
  p95_ms: number;
  p99_ms: number;
  count: number;
  error_rate: number;
}

interface HeartbeatStatus {
  service_id: string;
  status: "healthy" | "degraded" | "down" | "unknown";
  last_heartbeat: string | null;
  seconds_since_heartbeat: number | null;
  is_stale: boolean;
}

interface TokenUsage {
  user_id: string;
  total_requests: number;
  total_tokens: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_cost: number;
  avg_tokens_per_request: number;
}

interface SystemHealthData {
  timestamp: string;
  alpaca_latency: APILatency;
  gemini_latency: APILatency;
  heartbeat_status: HeartbeatStatus;
  token_usage_top_users: TokenUsage[];
}

const getStatusColor = (status: string) => {
  switch (status) {
    case "healthy":
      return "text-green-600 bg-green-100 dark:bg-green-900/20";
    case "degraded":
      return "text-yellow-600 bg-yellow-100 dark:bg-yellow-900/20";
    case "down":
      return "text-red-600 bg-red-100 dark:bg-red-900/20";
    default:
      return "text-gray-600 bg-gray-100 dark:bg-gray-900/20";
  }
};

const getStatusIcon = (status: string) => {
  switch (status) {
    case "healthy":
      return <CheckCircle className="h-5 w-5" />;
    case "degraded":
      return <AlertCircle className="h-5 w-5" />;
    case "down":
      return <XCircle className="h-5 w-5" />;
    default:
      return <Activity className="h-5 w-5" />;
  }
};

const LatencyCard = ({ latency }: { latency: APILatency }) => {
  const isHealthy = latency.avg_ms < 500 && latency.error_rate < 5;
  const statusColor = isHealthy ? "text-green-600" : latency.avg_ms > 1000 ? "text-red-600" : "text-yellow-600";

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Zap className="h-4 w-4" />
          {latency.service.charAt(0).toUpperCase() + latency.service.slice(1)} API
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Average Latency</span>
          <span className={`text-2xl font-bold ${statusColor}`}>
            {latency.avg_ms.toFixed(0)}ms
          </span>
        </div>
        
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">P50</span>
            <span className="font-mono">{latency.p50_ms.toFixed(0)}ms</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">P95</span>
            <span className="font-mono">{latency.p95_ms.toFixed(0)}ms</span>
          </div>
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">P99</span>
            <span className="font-mono">{latency.p99_ms.toFixed(0)}ms</span>
          </div>
        </div>

        <div className="pt-2 border-t">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Error Rate</span>
            <span className={latency.error_rate > 5 ? "text-red-600 font-semibold" : "text-green-600"}>
              {latency.error_rate.toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center justify-between text-xs mt-1">
            <span className="text-muted-foreground">Requests (15m)</span>
            <span className="font-mono">{latency.count}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

const HeartbeatCard = ({ heartbeat }: { heartbeat: HeartbeatStatus }) => {
  const statusColor = getStatusColor(heartbeat.status);
  const StatusIcon = () => getStatusIcon(heartbeat.status);

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Activity className="h-4 w-4" />
          System Heartbeat
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">Status</span>
          <Badge className={`${statusColor} flex items-center gap-1`}>
            <StatusIcon />
            {heartbeat.status.toUpperCase()}
          </Badge>
        </div>

        {heartbeat.last_heartbeat && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              Last Seen
            </div>
            <div className="text-xs font-mono">
              {new Date(heartbeat.last_heartbeat).toLocaleString()}
            </div>
            {heartbeat.seconds_since_heartbeat !== null && (
              <div className="text-xs">
                <span className="text-muted-foreground">
                  {heartbeat.seconds_since_heartbeat < 60
                    ? `${Math.round(heartbeat.seconds_since_heartbeat)}s ago`
                    : `${Math.round(heartbeat.seconds_since_heartbeat / 60)}m ago`}
                </span>
              </div>
            )}
          </div>
        )}

        {heartbeat.is_stale && (
          <Alert variant="destructive" className="py-2">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription className="text-xs">
              Heartbeat is stale! System may be offline or experiencing issues.
            </AlertDescription>
          </Alert>
        )}

        <div className="pt-2 border-t">
          <div className="text-xs text-muted-foreground mb-1">Expected: Update every 120s</div>
          {heartbeat.seconds_since_heartbeat !== null && (
            <Progress 
              value={Math.min((heartbeat.seconds_since_heartbeat / 120) * 100, 100)} 
              className="h-2"
            />
          )}
        </div>
      </CardContent>
    </Card>
  );
};

const TokenUsageCard = ({ usage }: { usage: TokenUsage[] }) => {
  const currentUser = usage[0]; // Assuming first is current user or we show top user

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <DollarSign className="h-4 w-4" />
          Gemini 2.5 Flash Token Usage
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {currentUser ? (
          <>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Total Cost (24h)</span>
                <span className="text-2xl font-bold text-blue-600">
                  ${currentUser.total_cost.toFixed(4)}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Total Tokens</div>
                  <div className="text-lg font-semibold">
                    {currentUser.total_tokens.toLocaleString()}
                  </div>
                </div>
                <div className="space-y-1">
                  <div className="text-xs text-muted-foreground">Requests</div>
                  <div className="text-lg font-semibold">
                    {currentUser.total_requests}
                  </div>
                </div>
              </div>

              <div className="pt-2 border-t space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Prompt Tokens</span>
                  <span className="font-mono">{currentUser.prompt_tokens.toLocaleString()}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Completion Tokens</span>
                  <span className="font-mono">{currentUser.completion_tokens.toLocaleString()}</span>
                </div>
                <div className="flex items-center justify-between text-xs">
                  <span className="text-muted-foreground">Avg per Request</span>
                  <span className="font-mono">{Math.round(currentUser.avg_tokens_per_request)}</span>
                </div>
              </div>
            </div>

            <Alert className="py-2">
              <TrendingUp className="h-4 w-4" />
              <AlertDescription className="text-xs">
                <strong>SaaS Tier Ready:</strong> Track usage for billing tiers
              </AlertDescription>
            </Alert>
          </>
        ) : (
          <div className="text-center py-6 text-muted-foreground text-sm">
            No token usage data available
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export const SystemHealth = () => {
  const [healthData, setHealthData] = useState<SystemHealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const { tenantId, user } = useAuth();

  const fetchSystemHealth = async () => {
    if (!tenantId) return;

    try {
      // In production, this would call your backend API
      // For now, using mock data structure
      const mockData: SystemHealthData = {
        timestamp: new Date().toISOString(),
        alpaca_latency: {
          service: "alpaca",
          avg_ms: 245,
          min_ms: 120,
          max_ms: 580,
          p50_ms: 230,
          p95_ms: 450,
          p99_ms: 550,
          count: 234,
          error_rate: 1.2,
        },
        gemini_latency: {
          service: "gemini",
          avg_ms: 892,
          min_ms: 520,
          max_ms: 1450,
          p50_ms: 850,
          p95_ms: 1200,
          p99_ms: 1400,
          count: 87,
          error_rate: 0.5,
        },
        heartbeat_status: {
          service_id: "market_ingest",
          status: "healthy",
          last_heartbeat: new Date(Date.now() - 45000).toISOString(),
          seconds_since_heartbeat: 45,
          is_stale: false,
        },
        token_usage_top_users: [
          {
            user_id: user?.uid || "current_user",
            total_requests: 156,
            total_tokens: 234567,
            prompt_tokens: 189234,
            completion_tokens: 45333,
            total_cost: 0.0234,
            avg_tokens_per_request: 1503,
          },
        ],
      };

      setHealthData(mockData);
      setError(null);
    } catch (err) {
      setError("Failed to fetch system health data");
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchSystemHealth();
    
    // Refresh every 15 seconds
    const interval = setInterval(fetchSystemHealth, 15000);
    
    return () => clearInterval(interval);
  }, [tenantId, user]);

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            System Health Monitor
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-24 bg-muted animate-pulse rounded" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (error || !healthData) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Server className="h-5 w-5" />
            System Health Monitor
          </CardTitle>
        </CardHeader>
        <CardContent>
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              {error || "Failed to load system health data"}
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <Server className="h-6 w-6" />
          System Health Monitor
        </h2>
        <div className="text-xs text-muted-foreground">
          Last updated: {new Date(healthData.timestamp).toLocaleTimeString()}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <LatencyCard latency={healthData.alpaca_latency} />
        <LatencyCard latency={healthData.gemini_latency} />
        <HeartbeatCard heartbeat={healthData.heartbeat_status} />
      </div>

      <TokenUsageCard usage={healthData.token_usage_top_users} />

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">System Status Summary</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-green-600">
                {healthData.alpaca_latency.count + healthData.gemini_latency.count}
              </div>
              <div className="text-xs text-muted-foreground">Total API Calls (15m)</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-blue-600">
                {((healthData.alpaca_latency.avg_ms + healthData.gemini_latency.avg_ms) / 2).toFixed(0)}ms
              </div>
              <div className="text-xs text-muted-foreground">Avg Response Time</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-purple-600">
                {healthData.token_usage_top_users[0]?.total_requests || 0}
              </div>
              <div className="text-xs text-muted-foreground">AI Requests (24h)</div>
            </div>
            <div>
              <div className={`text-2xl font-bold ${getStatusColor(healthData.heartbeat_status.status).split(' ')[0]}`}>
                {healthData.heartbeat_status.status === "healthy" ? "✓" : "✗"}
              </div>
              <div className="text-xs text-muted-foreground">System Status</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};
