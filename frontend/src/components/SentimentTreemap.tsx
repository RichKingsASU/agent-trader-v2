import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, AlertCircle, RefreshCw, TrendingUp, TrendingDown, Sparkles } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { getFirestore, query, orderBy, limit, onSnapshot, QuerySnapshot, DocumentData } from "firebase/firestore";
import { app } from "@/firebase";
import { marketDataCollection } from "@/lib/tenancy/firestore";

interface SectorSentiment {
  sector: string;
  symbol: string;
  marketCap: number; // Market cap in billions
  sentimentScore: number; // -1.0 to 1.0
  change24h: number; // % change
  volume: number;
  aiSummary: string;
  timestamp: any;
}

interface TreemapTile {
  sector: string;
  symbol: string;
  marketCap: number;
  sentimentScore: number;
  color: string;
  size: number; // Relative size for rendering
  x: number;
  y: number;
  width: number;
  height: number;
}

export const SentimentTreemap: React.FC = () => {
  const [sentiments, setSentiments] = useState<SectorSentiment[]>([]);
  const [tiles, setTiles] = useState<TreemapTile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedTile, setSelectedTile] = useState<TreemapTile | null>(null);

  useEffect(() => {
    const db = getFirestore(app);
    
    // Listen to marketData/sentiment/sectors collection
    const sentimentRef = marketDataCollection(db, "sentiment", "sectors");
    const q = query(
      sentimentRef,
      orderBy("marketCap", "desc"),
      limit(30) // Top 30 stocks by market cap
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot: QuerySnapshot<DocumentData>) => {
        const sentimentsData: SectorSentiment[] = [];
        
        snapshot.forEach((doc) => {
          const data = doc.data();
          sentimentsData.push({
            sector: data.sector || "Unknown",
            symbol: data.symbol || doc.id,
            marketCap: data.marketCap || 0,
            sentimentScore: data.sentimentScore || 0,
            change24h: data.change24h || 0,
            volume: data.volume || 0,
            aiSummary: data.aiSummary || "",
            timestamp: data.timestamp,
          });
        });

        setSentiments(sentimentsData);
        
        // Calculate treemap layout
        const calculatedTiles = calculateTreemap(sentimentsData, 1000, 600);
        setTiles(calculatedTiles);
        
        setLoading(false);
        setError(null);
      },
      (err) => {
        console.error("Error fetching sentiment data:", err);
        setError(err.message || "Failed to fetch sentiment data");
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, []);

  const calculateTreemap = (
    data: SectorSentiment[],
    containerWidth: number,
    containerHeight: number
  ): TreemapTile[] => {
    if (data.length === 0) return [];

    // Sort by market cap (descending)
    const sorted = [...data].sort((a, b) => b.marketCap - a.marketCap);
    
    // Calculate total market cap
    const totalMarketCap = sorted.reduce((sum, item) => sum + item.marketCap, 0);
    
    // Simple squarified treemap algorithm
    const tiles: TreemapTile[] = [];
    let currentX = 0;
    let currentY = 0;
    let rowHeight = 0;
    let rowWidth = 0;
    const padding = 2;
    
    for (const item of sorted) {
      const size = (item.marketCap / totalMarketCap) * (containerWidth * containerHeight);
      const area = size;
      
      // Calculate tile dimensions
      const tileWidth = Math.sqrt(area * (containerWidth / containerHeight));
      const tileHeight = area / tileWidth;
      
      // Simple row-based layout
      if (currentX + tileWidth > containerWidth) {
        currentX = 0;
        currentY += rowHeight + padding;
        rowHeight = 0;
      }
      
      const color = getSentimentColor(item.sentimentScore);
      
      tiles.push({
        sector: item.sector,
        symbol: item.symbol,
        marketCap: item.marketCap,
        sentimentScore: item.sentimentScore,
        color,
        size: item.marketCap,
        x: currentX,
        y: currentY,
        width: Math.min(tileWidth, containerWidth - currentX),
        height: tileHeight,
      });
      
      currentX += tileWidth + padding;
      rowHeight = Math.max(rowHeight, tileHeight);
    }
    
    return tiles;
  };

  const getSentimentColor = (score: number): string => {
    // Map sentiment score (-1.0 to 1.0) to color
    if (score > 0.7) {
      return "hsl(120, 75%, 35%)"; // Dark green - Very Bullish
    } else if (score > 0.3) {
      return "hsl(120, 60%, 50%)"; // Green - Bullish
    } else if (score > -0.3) {
      return "hsl(45, 60%, 50%)"; // Yellow - Neutral
    } else if (score > -0.7) {
      return "hsl(25, 70%, 45%)"; // Orange - Bearish
    } else {
      return "hsl(0, 70%, 40%)"; // Red - Very Bearish
    }
  };

  const getSentimentLabel = (score: number): string => {
    if (score > 0.7) return "Very Bullish";
    if (score > 0.3) return "Bullish";
    if (score > -0.3) return "Neutral";
    if (score > -0.7) return "Bearish";
    return "Very Bearish";
  };

  const formatMarketCap = (cap: number): string => {
    if (cap >= 1000) {
      return `$${(cap / 1000).toFixed(1)}T`;
    } else if (cap >= 1) {
      return `$${cap.toFixed(0)}B`;
    } else {
      return `$${(cap * 1000).toFixed(0)}M`;
    }
  };

  if (loading && tiles.length === 0) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-6 w-6" />
            Sentiment Heatmap (Treemap)
          </CardTitle>
          <CardDescription>Market sentiment by market cap and AI score</CardDescription>
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
            <Sparkles className="h-6 w-6" />
            Sentiment Heatmap (Treemap)
          </CardTitle>
          <CardDescription>Market sentiment by market cap and AI score</CardDescription>
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
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-2xl flex items-center gap-2">
              <Sparkles className="h-6 w-6" />
              Sentiment Heatmap
            </CardTitle>
            <CardDescription>
              {sentiments.length} stocks visualized by market cap and AI sentiment
            </CardDescription>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.location.reload()}
          >
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </CardHeader>
      
      <CardContent className="space-y-4">
        {/* AI Summary Alert */}
        {sentiments.length > 0 && (
          <Alert className="border-blue-500/50 bg-blue-500/10">
            <Sparkles className="h-4 w-4" />
            <AlertDescription className="ml-6">
              <span className="font-semibold">Market Overview:</span>{" "}
              {(() => {
                const bullishCount = sentiments.filter(s => s.sentimentScore > 0.3).length;
                const bearishCount = sentiments.filter(s => s.sentimentScore < -0.3).length;
                const bullishPct = (bullishCount / sentiments.length * 100).toFixed(0);
                const bearishPct = (bearishCount / sentiments.length * 100).toFixed(0);
                
                if (bullishCount > bearishCount * 1.5) {
                  return `Strong bullish sentiment dominates: ${bullishPct}% of tracked stocks show positive momentum.`;
                } else if (bearishCount > bullishCount * 1.5) {
                  return `Bearish sentiment prevails: ${bearishPct}% of tracked stocks show negative momentum.`;
                } else {
                  return `Mixed market sentiment: ${bullishPct}% bullish, ${bearishPct}% bearish. Exercise caution.`;
                }
              })()}
            </AlertDescription>
          </Alert>
        )}

        {/* Treemap Visualization */}
        <div className="relative w-full bg-muted/30 rounded-lg border border-border overflow-hidden" style={{ height: "600px" }}>
          <svg width="100%" height="100%" viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid meet">
            {tiles.map((tile, idx) => (
              <TooltipProvider key={idx}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <g
                      onClick={() => setSelectedTile(tile)}
                      className="cursor-pointer transition-all hover:opacity-90"
                      style={{ cursor: "pointer" }}
                    >
                      <rect
                        x={tile.x}
                        y={tile.y}
                        width={tile.width}
                        height={tile.height}
                        fill={tile.color}
                        stroke="rgba(255,255,255,0.2)"
                        strokeWidth="2"
                        rx="4"
                      />
                      {tile.width > 60 && tile.height > 40 && (
                        <>
                          <text
                            x={tile.x + tile.width / 2}
                            y={tile.y + tile.height / 2 - 5}
                            textAnchor="middle"
                            fill="white"
                            fontSize="14"
                            fontWeight="bold"
                          >
                            {tile.symbol}
                          </text>
                          <text
                            x={tile.x + tile.width / 2}
                            y={tile.y + tile.height / 2 + 12}
                            textAnchor="middle"
                            fill="rgba(255,255,255,0.8)"
                            fontSize="10"
                          >
                            {tile.sentimentScore >= 0 ? "+" : ""}{tile.sentimentScore.toFixed(2)}
                          </text>
                        </>
                      )}
                    </g>
                  </TooltipTrigger>
                  
                  <TooltipContent side="right" className="max-w-md p-4">
                    <div className="space-y-2">
                      <div>
                        <h4 className="font-bold text-lg">{tile.symbol}</h4>
                        <p className="text-xs text-muted-foreground">{tile.sector}</p>
                      </div>
                      
                      <div className="grid grid-cols-2 gap-2 text-sm">
                        <div>
                          <div className="text-xs text-muted-foreground">Market Cap</div>
                          <div className="font-semibold">{formatMarketCap(tile.marketCap)}</div>
                        </div>
                        <div>
                          <div className="text-xs text-muted-foreground">Sentiment</div>
                          <div className="font-semibold">{getSentimentLabel(tile.sentimentScore)}</div>
                        </div>
                      </div>
                      
                      <div>
                        <div className="text-xs font-semibold mb-1">AI Score</div>
                        <div className="text-2xl font-bold" style={{ color: tile.color }}>
                          {tile.sentimentScore >= 0 ? "+" : ""}{tile.sentimentScore.toFixed(2)}
                        </div>
                      </div>
                      
                      <div className="pt-2 border-t text-xs text-muted-foreground">
                        Click for detailed analysis
                      </div>
                    </div>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            ))}
          </svg>
        </div>

        {/* Selected Tile Details */}
        {selectedTile && (
          <Card className="border-2" style={{ borderColor: selectedTile.color }}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-xl">{selectedTile.symbol}</CardTitle>
                  <CardDescription>{selectedTile.sector}</CardDescription>
                </div>
                <Badge
                  className="text-lg px-4 py-2"
                  style={{
                    backgroundColor: selectedTile.color,
                    color: "white",
                  }}
                >
                  {getSentimentLabel(selectedTile.sentimentScore)}
                </Badge>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-xs text-muted-foreground mb-1">Market Cap</div>
                  <div className="text-2xl font-bold">{formatMarketCap(selectedTile.marketCap)}</div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground mb-1">AI Sentiment Score</div>
                  <div className="text-2xl font-bold" style={{ color: selectedTile.color }}>
                    {selectedTile.sentimentScore >= 0 ? "+" : ""}{selectedTile.sentimentScore.toFixed(2)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-muted-foreground mb-1">Tile Size</div>
                  <div className="text-2xl font-bold">{((selectedTile.size / sentiments.reduce((sum, s) => sum + s.marketCap, 0)) * 100).toFixed(1)}%</div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Legend */}
        <div className="p-4 bg-muted/30 rounded-lg border border-border">
          <h4 className="font-semibold mb-3 text-sm">Color Scale: AI Sentiment Score (-1.0 to +1.0)</h4>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded" style={{ backgroundColor: "hsl(120, 75%, 35%)" }} />
              <div>
                <div className="text-xs font-semibold">Very Bullish</div>
                <div className="text-xs text-muted-foreground">&gt; +0.7</div>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded" style={{ backgroundColor: "hsl(120, 60%, 50%)" }} />
              <div>
                <div className="text-xs font-semibold">Bullish</div>
                <div className="text-xs text-muted-foreground">+0.3 to +0.7</div>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded" style={{ backgroundColor: "hsl(45, 60%, 50%)" }} />
              <div>
                <div className="text-xs font-semibold">Neutral</div>
                <div className="text-xs text-muted-foreground">-0.3 to +0.3</div>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded" style={{ backgroundColor: "hsl(25, 70%, 45%)" }} />
              <div>
                <div className="text-xs font-semibold">Bearish</div>
                <div className="text-xs text-muted-foreground">-0.7 to -0.3</div>
              </div>
            </div>
            
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded" style={{ backgroundColor: "hsl(0, 70%, 40%)" }} />
              <div>
                <div className="text-xs font-semibold">Very Bearish</div>
                <div className="text-xs text-muted-foreground">&lt; -0.7</div>
              </div>
            </div>
          </div>
          
          <div className="mt-3 text-xs text-muted-foreground">
            <strong>Tile Size:</strong> Proportional to market capitalization. Larger tiles = larger companies.
          </div>
        </div>
      </CardContent>
    </Card>
  );
};
