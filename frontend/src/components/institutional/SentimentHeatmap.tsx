import React, { useState, useEffect, useMemo, memo } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Loader2, AlertCircle, RefreshCw, Brain } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ResponsiveTreeMap } from "@nivo/treemap";
import { scaleLinear } from "d3-scale";
import { interpolateRgb } from "d3-interpolate";
import { onSnapshot, query } from "firebase/firestore";
import { db } from "@/firebase";
import { marketDataCollection } from "@/lib/tenancy/firestore";

// Data structure for sector sentiment from Firestore
interface SectorSentiment {
  id: string; // Sector name (e.g., "Technology")
  value: number; // Market cap or relative weight
  sentiment: number; // -1.0 (Bearish) to 1.0 (Bullish)
  leadingTicker?: string; // e.g., "NVDA"
}

// Transformed data structure for Nivo
interface TreeMapNode {
  id: string;
  name: string;
  value: number;
  sentiment: number;
  leadingTicker?: string;
  color: string;
}

interface TreeMapData {
  name: string;
  children: TreeMapNode[];
}

interface SentimentHeatmapProps {
  tenantId?: string;
}

// Diverging color scale function: Red -> Gray -> Green
const createDivergingColorScale = () => {
  // Define the three color stops
  const colors = {
    bearish: "#ef4444",  // Red
    neutral: "#71717a",   // Gray
    bullish: "#22c55e"    // Green
  };

  // Create two interpolators: bearish->neutral and neutral->bullish
  const bearishToNeutral = interpolateRgb(colors.bearish, colors.neutral);
  const neutralToBullish = interpolateRgb(colors.neutral, colors.bullish);

  return (sentiment: number): string => {
    // Clamp sentiment to [-1, 1]
    const clampedSentiment = Math.max(-1, Math.min(1, sentiment));
    
    if (clampedSentiment < -0.3) {
      // Extreme Bearish: -1.0 to -0.3
      // Map [-1, -0.3] to [0, 1] for interpolation
      const t = (clampedSentiment + 1) / 0.7; // 0.7 = 1 - 0.3
      return bearishToNeutral(t);
    } else if (clampedSentiment <= 0.3) {
      // Neutral: -0.3 to 0.3
      // Map [-0.3, 0.3] to [0, 1] for interpolation
      const t = (clampedSentiment + 0.3) / 0.6; // 0.6 = 0.3 - (-0.3)
      return bearishToNeutral(0.7 + t * 0.3); // Stay mostly gray
    } else {
      // Extreme Bullish: 0.3 to 1.0
      // Map [0.3, 1] to [0, 1] for interpolation
      const t = (clampedSentiment - 0.3) / 0.7;
      return neutralToBullish(t);
    }
  };
};

// Memoized TreeMap component to prevent unnecessary re-renders
const MemoizedTreeMap = memo<{ data: TreeMapData; colorScale: (sentiment: number) => string }>(
  ({ data, colorScale }) => {
    return (
      <div style={{ height: "500px" }}>
        <ResponsiveTreeMap
          data={data}
          identity="name"
          value="value"
          valueFormat=".02s"
          margin={{ top: 10, right: 10, bottom: 10, left: 10 }}
          labelSkipSize={12}
          labelTextColor={{
            from: "color",
            modifiers: [["darker", 2.4]]
          }}
          parentLabelPosition="left"
          parentLabelTextColor={{
            from: "color",
            modifiers: [["darker", 3]]
          }}
          borderWidth={1}
          borderColor={{
            from: "color",
            modifiers: [["darker", 0.2]]
          }}
          colors={(node: any) => {
            // Use the sentiment value to determine color
            const sentiment = node.data.sentiment || 0;
            return colorScale(sentiment);
          }}
          nodeOpacity={0.9}
          label={(node: any) => {
            return `${node.id}\n${node.data.leadingTicker || ""}`;
          }}
          tooltip={({ node }: any) => (
            <div
              style={{
                padding: "12px 16px",
                background: "rgba(0, 0, 0, 0.9)",
                color: "white",
                borderRadius: "6px",
                boxShadow: "0 4px 6px rgba(0, 0, 0, 0.1)",
                fontSize: "14px",
              }}
            >
              <div style={{ fontWeight: "bold", marginBottom: "8px", fontSize: "16px" }}>
                {node.id}
              </div>
              {node.data.leadingTicker && (
                <div style={{ marginBottom: "4px", color: "#a3a3a3" }}>
                  Leading: <span style={{ color: "white", fontWeight: 600 }}>{node.data.leadingTicker}</span>
                </div>
              )}
              <div style={{ marginBottom: "4px" }}>
                Sentiment: <span style={{ fontWeight: 600, color: node.data.sentiment > 0 ? "#22c55e" : node.data.sentiment < 0 ? "#ef4444" : "#71717a" }}>
                  {node.data.sentiment.toFixed(3)}
                </span>
              </div>
              <div>
                Weight: <span style={{ fontWeight: 600 }}>{node.formattedValue}</span>
              </div>
            </div>
          )}
          animate={true}
          motionConfig="gentle"
        />
      </div>
    );
  },
  (prevProps, nextProps) => {
    // Custom comparison function: only re-render if sentiment changes by more than 0.05
    if (!prevProps.data.children || !nextProps.data.children) return false;
    
    const hasSignificantChange = prevProps.data.children.some((prevNode, idx) => {
      const nextNode = nextProps.data.children[idx];
      if (!nextNode) return true;
      return Math.abs(prevNode.sentiment - nextNode.sentiment) > 0.05;
    });

    return !hasSignificantChange;
  }
);

MemoizedTreeMap.displayName = "MemoizedTreeMap";

export const SentimentHeatmap: React.FC<SentimentHeatmapProps> = ({ tenantId }) => {
  const [sectorData, setSectorData] = useState<SectorSentiment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // Create color scale function (memoized)
  const colorScale = useMemo(() => createDivergingColorScale(), []);

  // Listen to Firestore collection: marketData/sentiment/sectors
  useEffect(() => {
    setLoading(true);
    setError(null);

    try {
      const sectorsQuery = query(marketDataCollection(db, "sentiment", "sectors"));
      
      const unsubscribe = onSnapshot(
        sectorsQuery,
        (snapshot) => {
          const sectors: SectorSentiment[] = [];
          
          snapshot.forEach((doc) => {
            const data = doc.data();
            sectors.push({
              id: doc.id,
              value: data.value || data.marketCap || 100,
              sentiment: data.sentiment || 0,
              leadingTicker: data.leadingTicker || data.leading_ticker,
            });
          });

          setSectorData(sectors);
          setLastUpdate(new Date());
          setLoading(false);
        },
        (err) => {
          console.error("Error fetching sentiment data:", err);
          setError("Failed to load sentiment data from Firestore");
          setLoading(false);
        }
      );

      return () => unsubscribe();
    } catch (err) {
      console.error("Error setting up Firestore listener:", err);
      setError("Failed to connect to Firestore");
      setLoading(false);
    }
  }, [tenantId]);

  // Transform data for Nivo TreeMap
  const treeMapData: TreeMapData = useMemo(() => {
    return {
      name: "Market",
      children: sectorData.map((sector) => ({
        id: sector.id,
        name: sector.id,
        value: sector.value,
        sentiment: sector.sentiment,
        leadingTicker: sector.leadingTicker,
        color: colorScale(sector.sentiment),
      })),
    };
  }, [sectorData, colorScale]);

  const handleRefresh = () => {
    // Firestore listener automatically updates, but we can trigger a visual refresh
    setLastUpdate(new Date());
  };

  if (loading && sectorData.length === 0) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-6 w-6" />
            Sentiment Heatmap
          </CardTitle>
          <CardDescription>AI-driven sentiment across market sectors</CardDescription>
        </CardHeader>
        <CardContent className="flex items-center justify-center py-12">
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
            <Brain className="h-6 w-6" />
            Sentiment Heatmap
          </CardTitle>
          <CardDescription>AI-driven sentiment across market sectors</CardDescription>
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

  if (sectorData.length === 0) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Brain className="h-6 w-6" />
            Sentiment Heatmap
          </CardTitle>
          <CardDescription>AI-driven sentiment across market sectors</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="text-muted-foreground text-center py-8">
            No sector sentiment data available. Configure data in Firestore at:<br />
            <code className="text-xs bg-muted px-2 py-1 rounded mt-2 inline-block">
              marketData/sentiment/sectors
            </code>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-2xl flex items-center gap-2">
              <Brain className="h-6 w-6" />
              Sentiment Heatmap
            </CardTitle>
            <CardDescription>
              AI-driven sentiment across {sectorData.length} market sectors
              {lastUpdate && (
                <> • Updated {lastUpdate.toLocaleTimeString()}</>
              )}
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleRefresh}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        {/* TreeMap Visualization */}
        <MemoizedTreeMap data={treeMapData} colorScale={colorScale} />

        {/* Diverging Color Legend */}
        <div className="mt-6 p-4 bg-muted/30 rounded-lg border border-border">
          <h4 className="font-semibold mb-3 text-sm">Sentiment Color Scale</h4>
          
          {/* Horizontal Gradient Bar */}
          <div className="relative h-12 rounded-lg overflow-hidden mb-4">
            <div
              className="absolute inset-0"
              style={{
                background: `linear-gradient(to right, #ef4444 0%, #71717a 50%, #22c55e 100%)`,
              }}
            />
            <div className="absolute inset-0 flex items-center justify-between px-3 text-white font-semibold text-sm drop-shadow-lg">
              <span>Bearish</span>
              <span className="text-gray-200">Neutral</span>
              <span>Bullish</span>
            </div>
          </div>

          {/* Trading Actions Guide */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <div className="flex items-start gap-2">
              <div className="w-4 h-4 rounded mt-0.5" style={{ backgroundColor: "#ef4444" }} />
              <div>
                <div className="font-semibold">Volatility Expansion (Down)</div>
                <div className="text-muted-foreground">Hedge / Buy Puts / Sell Rallies</div>
              </div>
            </div>

            <div className="flex items-start gap-2">
              <div className="w-4 h-4 rounded mt-0.5" style={{ backgroundColor: "#71717a" }} />
              <div>
                <div className="font-semibold">Consolidation / Chop</div>
                <div className="text-muted-foreground">Scalp Ranges / Iron Condors</div>
              </div>
            </div>

            <div className="flex items-start gap-2">
              <div className="w-4 h-4 rounded mt-0.5" style={{ backgroundColor: "#22c55e" }} />
              <div>
                <div className="font-semibold">Trend Continuation (Up)</div>
                <div className="text-muted-foreground">Buy Dips / Long LEAPS</div>
              </div>
            </div>
          </div>

          <div className="mt-3 pt-3 border-t border-border text-xs text-muted-foreground">
            <strong>Why Diverging Scale?</strong> Institutional dashboards avoid rainbow scales to reduce cognitive load.
            This diverging palette lets you ignore gray (noise) and instantly focus on saturated red/green (signal).
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
