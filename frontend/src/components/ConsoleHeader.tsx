import { Link } from "react-router-dom";
import { ArrowLeft, Wifi, WifiOff, Home, BarChart3, Terminal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useNavigate, useLocation } from "react-router-dom";
import { SystemStatusBadge } from "@/components/SystemStatusBadge";
import type { LiveStatus } from "@/hooks/useMarketLiveQuotes";

interface ConsoleHeaderProps {
  symbol?: string;
  companyName?: string;
  lastPrice?: number;
  priceChange?: number;
  priceChangePct?: number;
  dayBias?: string;
  session: string;
  connected: boolean;
  lastUpdate: Date;
  loading: boolean;
  ingestStatus?: LiveStatus;
  heartbeatAt?: Date | null;
}

export const ConsoleHeader = ({
  symbol,
  companyName,
  lastPrice,
  priceChange,
  priceChangePct,
  dayBias,
  session,
  connected,
  lastUpdate,
  loading,
  ingestStatus,
  heartbeatAt,
}: ConsoleHeaderProps) => {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="border-b border-border bg-card">
      <div className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            {/* Back Button */}
            <Link to="/">
              <Button variant="ghost" size="sm">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Dashboard
              </Button>
            </Link>

            {/* Navigation Buttons */}
            <div className="flex items-center gap-1 border-l border-border pl-4">
              <Button
                variant={location.pathname === "/" ? "default" : "ghost"}
                size="sm"
                onClick={() => navigate("/")}
                className="h-8 px-3"
                title="F1 Dashboard"
              >
                <Home className="h-4 w-4 mr-1" />
                <span className="text-xs">Dashboard</span>
              </Button>
              <Button
                variant={location.pathname === "/options" ? "default" : "ghost"}
                size="sm"
                onClick={() => navigate("/options")}
                className="h-8 px-3"
                title="Options Analysis Center"
              >
                <BarChart3 className="h-4 w-4 mr-1" />
                <span className="text-xs">Options</span>
              </Button>
              <Button
                variant={location.pathname.startsWith("/console") ? "default" : "ghost"}
                size="sm"
                onClick={() => navigate(`/console/${symbol || 'SPY'}`)}
                className="h-8 px-3"
                title="Decision Console"
              >
                <Terminal className="h-4 w-4 mr-1" />
                <span className="text-xs">Console</span>
              </Button>
            </div>

            {/* Symbol Info */}
            <div className="border-l border-border pl-4">
              <div className="flex items-baseline gap-3">
                <h1 className="text-2xl font-bold">{symbol}</h1>
                {!loading && (
                  <>
                    <span className="text-sm text-muted-foreground">
                      {companyName}
                    </span>
                    <div className="flex items-baseline gap-2">
                      <span className="text-xl font-semibold number-mono">
                        ${lastPrice?.toFixed(2)}
                      </span>
                      <span className={priceChange && priceChange >= 0 ? "text-bull" : "text-bear"}>
                        {priceChange && priceChange >= 0 ? "+" : ""}
                        {priceChange?.toFixed(2)} (
                        {priceChangePct && priceChangePct >= 0 ? "+" : ""}
                        {priceChangePct?.toFixed(2)}%)
                      </span>
                    </div>
                  </>
                )}
              </div>
              <div className="flex gap-2 mt-2">
                {!loading && (
                  <>
                    <Badge variant={dayBias === "Bullish" ? "default" : "secondary"}>
                      {dayBias}
                    </Badge>
                    <Badge variant="outline">{session}</Badge>
                    {ingestStatus ? (
                      <SystemStatusBadge status={ingestStatus} heartbeatAt={heartbeatAt} className="text-[10px] px-2 py-0.5" />
                    ) : (
                      <Badge variant="outline" className="flex items-center gap-1">
                        {connected ? (
                          <>
                            <Wifi className="h-3 w-3 text-bull" />
                            <span>Live</span>
                          </>
                        ) : (
                          <>
                            <WifiOff className="h-3 w-3 text-muted-foreground" />
                            <span>Delayed</span>
                          </>
                        )}
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground">
                      Updated {lastUpdate.toLocaleTimeString()}
                    </span>
                  </>
                )}
                {loading && (
                  <>
                    <Skeleton className="h-5 w-16" />
                    <Skeleton className="h-5 w-20" />
                    <Skeleton className="h-5 w-16" />
                  </>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
