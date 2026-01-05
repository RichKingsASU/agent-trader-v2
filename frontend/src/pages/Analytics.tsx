import React, { useState } from "react";
import { GEXVisualization } from "@/components/institutional/GEXVisualization";
import { SentimentHeatmap } from "@/components/institutional/SentimentHeatmap";
import { ExecutionAudit } from "@/components/institutional/ExecutionAudit";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BarChart3, Brain, Target, TrendingUp } from "lucide-react";

/**
 * Institutional Analytics Dashboard
 * 
 * A professional-grade analytics suite featuring:
 * 1. GEX Visualization - Real-time gamma exposure mapping
 * 2. Sentiment Heatmap - AI-powered sentiment analysis via Gemini 1.5 Flash
 * 3. Execution Audit - Slippage analysis and execution quality metrics
 * 
 * This dashboard provides institutional-level insights that go beyond simple P&L,
 * making it a powerful selling point for SaaS offerings.
 */
const Analytics: React.FC = () => {
  // Default tenant ID - in production, this would come from auth context
  const [tenantId, setTenantId] = useState("demo-tenant");
  const [gexSymbol, setGexSymbol] = useState("SPY");

  return (
    <div className="container mx-auto p-6 space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-4xl font-bold tracking-tight flex items-center gap-3">
              <TrendingUp className="h-10 w-10" />
              Institutional Analytics
            </h1>
            <p className="text-muted-foreground mt-2">
              Professional-grade trading analytics powered by AI and advanced options analytics
            </p>
          </div>
          <Badge className="bg-gradient-to-r from-purple-500 to-pink-500 text-white text-lg px-4 py-2">
            Premium
          </Badge>
        </div>
      </div>

      {/* Configuration Panel */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Dashboard Configuration</CardTitle>
          <CardDescription>Configure analysis parameters</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <Label htmlFor="tenantId">Tenant ID</Label>
              <Input
                id="tenantId"
                value={tenantId}
                onChange={(e) => setTenantId(e.target.value)}
                placeholder="Enter tenant ID"
              />
            </div>
            <div>
              <Label htmlFor="gexSymbol">GEX Analysis Symbol</Label>
              <Input
                id="gexSymbol"
                value={gexSymbol}
                onChange={(e) => setGexSymbol(e.target.value.toUpperCase())}
                placeholder="Enter symbol (e.g., SPY)"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Feature Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-l-4 border-l-emerald-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <BarChart3 className="h-5 w-5 text-emerald-500" />
              GEX Visualization
            </CardTitle>
            <CardDescription>
              Real-time gamma exposure mapping showing call/put walls and market regime
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-l-4 border-l-purple-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Brain className="h-5 w-5 text-purple-500" />
              Sentiment Heatmap
            </CardTitle>
            <CardDescription>
              AI-powered sentiment analysis using Gemini 1.5 Flash for actionable insights
            </CardDescription>
          </CardHeader>
        </Card>

        <Card className="border-l-4 border-l-blue-500">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Target className="h-5 w-5 text-blue-500" />
              Execution Audit
            </CardTitle>
            <CardDescription>
              Detailed slippage analysis showing execution quality vs. intended prices
            </CardDescription>
          </CardHeader>
        </Card>
      </div>

      {/* Main Analytics Sections */}
      <Tabs defaultValue="gex" className="space-y-6">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="gex" className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4" />
            GEX
          </TabsTrigger>
          <TabsTrigger value="sentiment" className="flex items-center gap-2">
            <Brain className="h-4 w-4" />
            Sentiment
          </TabsTrigger>
          <TabsTrigger value="execution" className="flex items-center gap-2">
            <Target className="h-4 w-4" />
            Execution
          </TabsTrigger>
        </TabsList>

        {/* GEX Visualization Tab */}
        <TabsContent value="gex" className="space-y-4">
          <div className="bg-muted/30 p-4 rounded-lg border border-border">
            <h3 className="font-semibold mb-2">About GEX (Gamma Exposure)</h3>
            <p className="text-sm text-muted-foreground">
              Gamma Exposure (GEX) measures the aggregate gamma positioning of market makers. 
              It provides insights into market volatility expectations and potential price support/resistance levels.
            </p>
            <ul className="mt-2 text-sm text-muted-foreground list-disc list-inside space-y-1">
              <li><strong>Long Gamma Regime:</strong> Market makers dampen volatility (range-bound trading expected)</li>
              <li><strong>Short Gamma Regime:</strong> Market makers amplify volatility (trending moves expected)</li>
              <li><strong>Call/Put Walls:</strong> Strikes with highest open interest that may act as magnets or barriers</li>
            </ul>
          </div>
          
          <GEXVisualization symbol={gexSymbol} tenantId={tenantId} />
        </TabsContent>

        {/* Sentiment Heatmap Tab */}
        <TabsContent value="sentiment" className="space-y-4">
          <div className="bg-muted/30 p-4 rounded-lg border border-border">
            <h3 className="font-semibold mb-2">About AI Sentiment Analysis</h3>
            <p className="text-sm text-muted-foreground">
              Our sentiment analysis uses Gemini 1.5 Flash to analyze news headlines and assess their impact 
              on company fundamentals and cash flows. This goes beyond simple positive/negative sentiment 
              to provide actionable insights.
            </p>
            <ul className="mt-2 text-sm text-muted-foreground list-disc list-inside space-y-1">
              <li><strong>Sentiment Score:</strong> Ranges from -1.0 (very bearish) to +1.0 (very bullish)</li>
              <li><strong>Confidence:</strong> AI's confidence in its analysis (0-100%)</li>
              <li><strong>Cash Flow Impact:</strong> Analysis of how news affects future cash generation</li>
              <li><strong>Action:</strong> AI-recommended action (BUY, SELL, HOLD)</li>
            </ul>
          </div>
          
          <SentimentHeatmap tenantId={tenantId} />
        </TabsContent>

        {/* Execution Audit Tab */}
        <TabsContent value="execution" className="space-y-4">
          <div className="bg-muted/30 p-4 rounded-lg border border-border">
            <h3 className="font-semibold mb-2">About Execution Quality</h3>
            <p className="text-sm text-muted-foreground">
              Execution quality is critical for algorithmic trading. Slippage - the difference between 
              intended and executed prices - directly impacts profitability. Our audit tracks every execution 
              to ensure optimal performance.
            </p>
            <ul className="mt-2 text-sm text-muted-foreground list-disc list-inside space-y-1">
              <li><strong>Slippage:</strong> Measured in basis points (bps) and dollars</li>
              <li><strong>Negative Slippage:</strong> Better than expected (green) - you saved money!</li>
              <li><strong>Positive Slippage:</strong> Worse than expected (red) - cost of execution</li>
              <li><strong>Quality Grades:</strong> Excellent (&lt;-10 bps) to Bad (&gt;25 bps)</li>
            </ul>
          </div>
          
          <ExecutionAudit tenantId={tenantId} />
        </TabsContent>
      </Tabs>

      {/* SaaS Value Proposition */}
      <Card className="bg-gradient-to-r from-purple-500/10 via-pink-500/10 to-orange-500/10 border-2 border-primary/20">
        <CardHeader>
          <CardTitle className="text-2xl">Why This Matters for SaaS</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <h4 className="font-semibold text-lg mb-2">🎯 Beyond Simple P&L</h4>
            <p className="text-sm text-muted-foreground">
              While most trading platforms only show profit and loss, our institutional analytics 
              reveal <strong>why</strong> you're making or losing money. This depth of insight is 
              what professional traders and institutions pay premium prices for.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-4">
            <div className="bg-background/50 p-4 rounded-lg">
              <h5 className="font-semibold mb-2">Market Structure Insights</h5>
              <p className="text-xs text-muted-foreground">
                GEX analysis reveals hidden market dynamics that impact your trades
              </p>
            </div>
            
            <div className="bg-background/50 p-4 rounded-lg">
              <h5 className="font-semibold mb-2">AI-Powered Intelligence</h5>
              <p className="text-xs text-muted-foreground">
                Gemini 1.5 Flash provides institutional-grade fundamental analysis at scale
              </p>
            </div>
            
            <div className="bg-background/50 p-4 rounded-lg">
              <h5 className="font-semibold mb-2">Execution Transparency</h5>
              <p className="text-xs text-muted-foreground">
                Know exactly how much each trade costs you in slippage and fees
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default Analytics;
