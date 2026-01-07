import React, { useState } from "react";
import { WhaleFlowTracker } from "@/components/WhaleFlowTracker";
import { DashboardHeader } from "@/components/DashboardHeader";

/**
 * Whale Flow Page
 * 
 * This page displays institutional-level options flow tracking with advanced filtering.
 * Features:
 * - Real-time Firestore listener on market_intelligence/options_flow/live
 * - Heat map showing Bullish vs Bearish premium flow
 * - Golden Sweeps detection (>$1M premium, <14 DTE)
 * - Smart filters: Aggressive Only, OTM Focus, GEX Overlay
 * - Integration with GEX regime signals
 */
export default function WhaleFlow() {
  const [currentSymbol, setCurrentSymbol] = useState("SPY");

  return (
    <div className="min-h-screen bg-background">
      <DashboardHeader
        currentSymbol={currentSymbol}
        onSymbolChange={setCurrentSymbol}
        environment="production"
      />
      
      <main className="container mx-auto py-8 px-4">
        <div className="mb-6">
          <h1 className="text-3xl font-bold mb-2">Institutional Options Flow</h1>
          <p className="text-muted-foreground">
            Track whale trades and institutional positioning in real-time
          </p>
        </div>

        <WhaleFlowTracker maxTrades={100} />
      </main>
    </div>
  );
}
