import React, { useMemo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Loader2, AlertCircle, TrendingUp, TrendingDown, Waves, Sparkles } from "lucide-react";
import { useWhaleFlow } from "@/hooks/useWhaleFlow";

export const WhaleFlow: React.FC = () => {
  const { trades, systemStatus, loading, error } = useWhaleFlow();

  const activities = useMemo(() => {
    return trades.map((t) => ({
      id: t.id,
      ticker: t.symbol,
      type: (t.is_golden_sweep ? "Sweep" : "Block") as "Sweep" | "Block",
      sentiment:
        (t.sentiment === "bullish" ? "Bullish" : t.sentiment === "bearish" ? "Bearish" : "Neutral") as
          | "Bullish"
          | "Bearish"
          | "Neutral",
      premium: String(t.premium ?? 0),
      strike: t.strike,
      expiry: t.expiry,
      optionType: (t.option_type === "call" ? "Call" : "Put") as "Call" | "Put",
      timestamp: t.timestamp,
    }));
  }, [trades]);

  const dominantFlow = systemStatus?.volatility_bias ? `Volatility bias: ${systemStatus.volatility_bias}` : "";

  const formatPremium = (premium: string) => {
    const num = parseFloat(premium);
    if (isNaN(num)) return "$0";
    
    if (num >= 1_000_000) {
      return `$${(num / 1_000_000).toFixed(2)}M`;
    } else if (num >= 1_000) {
      return `$${(num / 1_000).toFixed(1)}K`;
    } else {
      return `$${num.toFixed(2)}`;
    }
  };

  const getSentimentBadge = (sentiment: "Bullish" | "Bearish" | "Neutral") => {
    switch (sentiment) {
      case "Bullish":
        return (
          <Badge className="bg-emerald-500 hover:bg-emerald-600 flex items-center gap-1">
            <TrendingUp className="h-3 w-3" />
            Bullish
          </Badge>
        );
      case "Bearish":
        return (
          <Badge className="bg-red-500 hover:bg-red-600 flex items-center gap-1">
            <TrendingDown className="h-3 w-3" />
            Bearish
          </Badge>
        );
      default:
        return <Badge variant="secondary">Neutral</Badge>;
    }
  };

  const getTypeBadge = (type: "Sweep" | "Block") => {
    if (type === "Sweep") {
      return (
        <Badge variant="outline" className="border-blue-500 text-blue-500">
          Sweep
        </Badge>
      );
    } else {
      return (
        <Badge variant="outline" className="border-purple-500 text-purple-500">
          Block
        </Badge>
      );
    }
  };

  const formatTimestamp = (timestamp: any) => {
    if (!timestamp) return "N/A";
    
    try {
      // Handle Firestore Timestamp
      if (timestamp.toDate) {
        const date = timestamp.toDate();
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        
        if (diffMins < 1) return "Just now";
        if (diffMins < 60) return `${diffMins}m ago`;
        
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        
        return date.toLocaleDateString();
      }
      
      if (timestamp instanceof Date) return timestamp.toLocaleTimeString();
      return new Date(timestamp).toLocaleTimeString();
    } catch {
      return "N/A";
    }
  };

  if (loading && activities.length === 0) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Waves className="h-6 w-6" />
            Whale Flow Dashboard
          </CardTitle>
          <CardDescription>Institutional order flow from unusual options activity</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Waves className="h-6 w-6" />
            Whale Flow Dashboard
          </CardTitle>
          <CardDescription>Institutional order flow from unusual options activity</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span>{error}</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="text-2xl flex items-center gap-2">
          <Waves className="h-6 w-6" />
          Whale Flow Dashboard
        </CardTitle>
        <CardDescription>
          Tracking {activities.length} unusual options activities • Real-time institutional order flow
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-4">
        {/* AI Analyst Summary */}
        {dominantFlow && (
          <Alert className="border-blue-500/50 bg-blue-500/10">
            <Sparkles className="h-4 w-4" />
            <AlertDescription className="ml-6">
              <span className="font-semibold">AI Analyst:</span> {dominantFlow}
            </AlertDescription>
          </Alert>
        )}

        {/* Whale Flow Table */}
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Ticker</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Sentiment</TableHead>
                <TableHead>Premium</TableHead>
                <TableHead>Strike</TableHead>
                <TableHead>Expiry</TableHead>
                <TableHead>Option</TableHead>
                <TableHead>Time</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {activities.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    No whale flow activity detected yet
                  </TableCell>
                </TableRow>
              ) : (
                activities.map((activity) => (
                  <TableRow key={activity.id} className="hover:bg-muted/50">
                    <TableCell className="font-semibold">
                      <a
                        href={`#/ticker/${activity.ticker}`}
                        className="hover:underline text-blue-500"
                      >
                        {activity.ticker}
                      </a>
                    </TableCell>
                    <TableCell>{getTypeBadge(activity.type)}</TableCell>
                    <TableCell>{getSentimentBadge(activity.sentiment)}</TableCell>
                    <TableCell className="font-mono font-semibold">
                      {formatPremium(activity.premium)}
                    </TableCell>
                    <TableCell className="font-mono">${activity.strike}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {activity.expiry}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={activity.optionType === "Call" ? "border-green-500 text-green-500" : "border-orange-500 text-orange-500"}>
                        {activity.optionType}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatTimestamp(activity.timestamp)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Legend */}
        <div className="mt-4 p-4 bg-muted/30 rounded-lg border border-border">
          <h4 className="font-semibold mb-2 text-sm">Understanding Whale Flow</h4>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-xs text-muted-foreground">
            <div>
              <span className="font-semibold">Sweep:</span> Orders executed across multiple exchanges simultaneously (aggressive)
            </div>
            <div>
              <span className="font-semibold">Block:</span> Large single orders likely from dark pools or private transactions
            </div>
            <div>
              <span className="font-semibold">Bullish Signal:</span> Calls bought at Ask or Puts sold at Bid
            </div>
            <div>
              <span className="font-semibold">Bearish Signal:</span> Puts bought at Ask or Calls sold at Bid
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
