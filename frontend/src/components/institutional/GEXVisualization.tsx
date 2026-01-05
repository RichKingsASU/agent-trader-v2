import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, TrendingUp, TrendingDown, AlertCircle } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, ReferenceLine, Cell } from "recharts";

interface GEXDataPoint {
  strike: number;
  call_gex: number;
  put_gex: number;
  net_gex: number;
  open_interest_calls: number;
  open_interest_puts: number;
}

interface GEXVisualizationData {
  symbol: string;
  spot_price: number;
  net_gex: number;
  call_gex_total: number;
  put_gex_total: number;
  regime: string;
  regime_description: string;
  strikes: GEXDataPoint[];
  call_wall: number | null;
  put_wall: number | null;
  timestamp: string;
  strikes_analyzed: number;
}

interface GEXVisualizationProps {
  symbol: string;
  tenantId: string;
}

export const GEXVisualization: React.FC<GEXVisualizationProps> = ({ symbol, tenantId }) => {
  const [data, setData] = useState<GEXVisualizationData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchGEXData();
    // Refresh every 60 seconds
    const interval = setInterval(fetchGEXData, 60000);
    return () => clearInterval(interval);
  }, [symbol, tenantId]);

  const fetchGEXData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await fetch(
        `http://localhost:8001/api/institutional/gex/${symbol}?tenant_id=${tenantId}`
      );
      
      if (!response.ok) {
        throw new Error(`Failed to fetch GEX data: ${response.statusText}`);
      }
      
      const result = await response.json();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch GEX data");
      console.error("Error fetching GEX data:", err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle>GEX Visualization (Gamma Map)</CardTitle>
          <CardDescription>Real-time gamma exposure analysis</CardDescription>
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
          <CardTitle>GEX Visualization (Gamma Map)</CardTitle>
          <CardDescription>Real-time gamma exposure analysis</CardDescription>
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

  if (!data) {
    return null;
  }

  // Prepare chart data
  const chartData = data.strikes.map(strike => ({
    strike: strike.strike.toFixed(2),
    callGEX: strike.call_gex / 1000000, // Convert to millions for readability
    putGEX: Math.abs(strike.put_gex) / 1000000, // Absolute value for display
    netGEX: strike.net_gex / 1000000,
    isCallWall: strike.strike === data.call_wall,
    isPutWall: strike.strike === data.put_wall,
  }));

  // Regime styling
  const getRegimeBadge = () => {
    switch (data.regime) {
      case "LONG_GAMMA":
        return (
          <Badge className="bg-emerald-500 hover:bg-emerald-600">
            <TrendingDown className="h-3 w-3 mr-1" />
            Long Gamma (Low Vol)
          </Badge>
        );
      case "SHORT_GAMMA":
        return (
          <Badge className="bg-red-500 hover:bg-red-600">
            <TrendingUp className="h-3 w-3 mr-1" />
            Short Gamma (High Vol)
          </Badge>
        );
      default:
        return <Badge variant="secondary">Neutral</Badge>;
    }
  };

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-2xl">{data.symbol} Gamma Exposure Map</CardTitle>
            <CardDescription>
              Real-time GEX analysis • {data.strikes_analyzed} strikes • Updated {new Date(data.timestamp).toLocaleTimeString()}
            </CardDescription>
          </div>
          {getRegimeBadge()}
        </div>
      </CardHeader>
      
      <CardContent className="space-y-6">
        {/* Key Metrics */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Spot Price</div>
            <div className="text-2xl font-bold">${data.spot_price.toFixed(2)}</div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Net GEX</div>
            <div className={`text-2xl font-bold ${data.net_gex > 0 ? 'text-emerald-500' : 'text-red-500'}`}>
              ${(data.net_gex / 1000000).toFixed(2)}M
            </div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Call Wall</div>
            <div className="text-2xl font-bold text-emerald-500">
              {data.call_wall ? `$${data.call_wall.toFixed(2)}` : 'N/A'}
            </div>
          </div>
          
          <div className="bg-muted/50 p-4 rounded-lg">
            <div className="text-sm text-muted-foreground">Put Wall</div>
            <div className="text-2xl font-bold text-red-500">
              {data.put_wall ? `$${data.put_wall.toFixed(2)}` : 'N/A'}
            </div>
          </div>
        </div>

        {/* Regime Description */}
        <div className="bg-muted/30 p-4 rounded-lg border border-border">
          <h4 className="font-semibold mb-2">Market Regime Analysis</h4>
          <p className="text-sm text-muted-foreground">{data.regime_description}</p>
        </div>

        {/* GEX Chart */}
        <div className="w-full h-[400px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 20, right: 30, left: 20, bottom: 60 }}>
              <CartesianGrid strokeDasharray="3 3" className="opacity-30" />
              <XAxis 
                dataKey="strike" 
                angle={-45} 
                textAnchor="end" 
                height={80}
                label={{ value: 'Strike Price ($)', position: 'insideBottom', offset: -10 }}
              />
              <YAxis 
                label={{ value: 'GEX (Millions $)', angle: -90, position: 'insideLeft' }}
              />
              <Tooltip 
                contentStyle={{ 
                  backgroundColor: 'hsl(var(--background))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '8px'
                }}
                formatter={(value: number) => [`$${value.toFixed(2)}M`, '']}
              />
              <Legend 
                verticalAlign="top" 
                height={36}
                wrapperStyle={{ paddingBottom: '20px' }}
              />
              
              {/* Spot price reference line */}
              <ReferenceLine 
                x={data.spot_price.toFixed(2)} 
                stroke="hsl(var(--primary))" 
                strokeWidth={2}
                label={{ value: 'Spot', position: 'top' }}
              />
              
              {/* Call wall reference line */}
              {data.call_wall && (
                <ReferenceLine 
                  x={data.call_wall.toFixed(2)} 
                  stroke="rgb(16, 185, 129)" 
                  strokeDasharray="5 5"
                  label={{ value: 'Call Wall', position: 'top' }}
                />
              )}
              
              {/* Put wall reference line */}
              {data.put_wall && (
                <ReferenceLine 
                  x={data.put_wall.toFixed(2)} 
                  stroke="rgb(239, 68, 68)" 
                  strokeDasharray="5 5"
                  label={{ value: 'Put Wall', position: 'top' }}
                />
              )}
              
              <Bar 
                dataKey="callGEX" 
                fill="rgb(16, 185, 129)" 
                name="Call GEX"
                radius={[4, 4, 0, 0]}
              >
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-call-${index}`}
                    fill={entry.isCallWall ? "rgb(5, 150, 105)" : "rgb(16, 185, 129)"}
                  />
                ))}
              </Bar>
              
              <Bar 
                dataKey="putGEX" 
                fill="rgb(239, 68, 68)" 
                name="Put GEX"
                radius={[4, 4, 0, 0]}
              >
                {chartData.map((entry, index) => (
                  <Cell 
                    key={`cell-put-${index}`}
                    fill={entry.isPutWall ? "rgb(220, 38, 38)" : "rgb(239, 68, 68)"}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Additional Metrics */}
        <div className="grid grid-cols-2 gap-4 pt-4 border-t">
          <div>
            <div className="text-sm text-muted-foreground">Total Call GEX</div>
            <div className="text-lg font-semibold text-emerald-500">
              ${(data.call_gex_total / 1000000).toFixed(2)}M
            </div>
          </div>
          <div>
            <div className="text-sm text-muted-foreground">Total Put GEX</div>
            <div className="text-lg font-semibold text-red-500">
              ${(Math.abs(data.put_gex_total) / 1000000).toFixed(2)}M
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
