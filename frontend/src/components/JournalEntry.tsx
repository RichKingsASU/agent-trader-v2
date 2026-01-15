import React, { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Separator } from "@/components/ui/separator";
import { Loader2, BookOpen, TrendingUp, TrendingDown, Clock, Target, AlertCircle } from "lucide-react";
import { getFirestore, query, orderBy, limit, onSnapshot, QuerySnapshot, DocumentData } from "firebase/firestore";
import { app } from "@/firebase";
import { useAuth } from "@/contexts/AuthContext";
import { userCollection } from "@/lib/tenancy/firestore";

interface JournalEntry {
  id: string;
  trade_id: string;
  symbol: string;
  side: "BUY" | "SELL";
  entry_price: string;
  exit_price: string;
  realized_pnl: string;
  quantity: string;
  quant_grade: string;
  ai_feedback: string;
  market_regime?: string;
  created_at: any;
  closed_at: any;
  analyzed_at: any;
  error?: string;
}

export const TradingJournal: React.FC = () => {
  const { user } = useAuth();
  const [entries, setEntries] = useState<JournalEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) {
      setEntries([]);
      setLoading(false);
      return;
    }

    const db = getFirestore(app);
    const journalRef = userCollection(db, user.uid, "tradeJournal");
    
    // Query journal entries, ordered by most recent
    const q = query(
      journalRef,
      orderBy("analyzed_at", "desc"),
      limit(20)
    );

    const unsubscribe = onSnapshot(
      q,
      (snapshot: QuerySnapshot<DocumentData>) => {
        const entriesData: JournalEntry[] = [];
        
        snapshot.forEach((doc) => {
          const data = doc.data();
          entriesData.push({
            id: doc.id,
            trade_id: data.trade_id,
            symbol: data.symbol,
            side: data.side,
            entry_price: data.entry_price || "0",
            exit_price: data.exit_price || "0",
            realized_pnl: data.realized_pnl || "0",
            quantity: data.quantity || "0",
            quant_grade: data.quant_grade || "N/A",
            ai_feedback: data.ai_feedback || "",
            market_regime: data.market_regime,
            created_at: data.created_at,
            closed_at: data.closed_at,
            analyzed_at: data.analyzed_at,
            error: data.error,
          });
        });

        setEntries(entriesData);
        setLoading(false);
        setError(null);
      },
      (err) => {
        console.error("Error fetching journal entries:", err);
        setError(err.message || "Failed to fetch journal entries");
        setLoading(false);
      }
    );

    return () => unsubscribe();
  }, [user]);

  const getGradeBadge = (grade: string) => {
    const gradeUpper = grade.toUpperCase();
    
    if (gradeUpper.startsWith("A")) {
      return <Badge className="bg-emerald-500 hover:bg-emerald-600 text-lg px-3">{grade}</Badge>;
    } else if (gradeUpper.startsWith("B")) {
      return <Badge className="bg-blue-500 hover:bg-blue-600 text-lg px-3">{grade}</Badge>;
    } else if (gradeUpper.startsWith("C")) {
      return <Badge className="bg-yellow-500 hover:bg-yellow-600 text-lg px-3">{grade}</Badge>;
    } else if (gradeUpper.startsWith("D")) {
      return <Badge className="bg-orange-500 hover:bg-orange-600 text-lg px-3">{grade}</Badge>;
    } else if (gradeUpper.startsWith("F")) {
      return <Badge className="bg-red-500 hover:bg-red-600 text-lg px-3">{grade}</Badge>;
    } else {
      return <Badge variant="secondary" className="text-lg px-3">{grade}</Badge>;
    }
  };

  const formatPrice = (price: string) => {
    const num = parseFloat(price);
    return isNaN(num) ? "$0.00" : `$${num.toFixed(2)}`;
  };

  const formatPnL = (pnl: string) => {
    const num = parseFloat(pnl);
    if (isNaN(num)) return "$0.00";
    
    const formatted = num >= 0 ? `+$${num.toFixed(2)}` : `-$${Math.abs(num).toFixed(2)}`;
    const color = num >= 0 ? "text-emerald-500" : "text-red-500";
    
    return <span className={`font-semibold ${color}`}>{formatted}</span>;
  };

  const formatTimestamp = (timestamp: any) => {
    if (!timestamp) return "N/A";
    
    try {
      if (timestamp.toDate) {
        return timestamp.toDate().toLocaleString();
      }
      return new Date(timestamp).toLocaleString();
    } catch {
      return "N/A";
    }
  };

  const parseAIFeedback = (feedback: string) => {
    // Parse the structured AI feedback
    const sections = {
      grade: "",
      analysis: "",
      tips: [] as string[],
      regimeImpact: "",
    };

    try {
      // Extract Analysis section
      const analysisMatch = feedback.match(/\*\*Analysis\*\*:\s*(.+?)(?=\*\*Quant Tips\*\*|$)/s);
      if (analysisMatch) {
        sections.analysis = analysisMatch[1].trim();
      }

      // Extract Quant Tips
      const tipsMatch = feedback.match(/\*\*Quant Tips\*\*:\s*(.+?)(?=\*\*Regime Impact\*\*|$)/s);
      if (tipsMatch) {
        const tipsText = tipsMatch[1].trim();
        const tipLines = tipsText.split(/\n\d+\./).filter(t => t.trim());
        sections.tips = tipLines.map(t => t.trim().replace(/^\d+\.\s*/, ""));
      }

      // Extract Regime Impact
      const regimeMatch = feedback.match(/\*\*Regime Impact\*\*:\s*(.+?)$/s);
      if (regimeMatch) {
        sections.regimeImpact = regimeMatch[1].trim();
      }
    } catch (err) {
      console.error("Error parsing AI feedback:", err);
    }

    return sections;
  };

  if (loading && entries.length === 0) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-6 w-6" />
            Trading Journal
          </CardTitle>
          <CardDescription>AI-powered trade analysis by Gemini 1.5 Flash</CardDescription>
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
            <BookOpen className="h-6 w-6" />
            Trading Journal
          </CardTitle>
          <CardDescription>AI-powered trade analysis by Gemini 1.5 Flash</CardDescription>
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

  if (!user) {
    return (
      <Card className="w-full">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <BookOpen className="h-6 w-6" />
            Trading Journal
          </CardTitle>
          <CardDescription>AI-powered trade analysis by Gemini 1.5 Flash</CardDescription>
        </CardHeader>
        <CardContent>
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Please sign in to view your trading journal
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="w-full">
      <CardHeader>
        <CardTitle className="text-2xl flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          Trading Journal
        </CardTitle>
        <CardDescription>
          AI-analyzed trades: {entries.length} entries • Powered by Gemini 1.5 Flash
        </CardDescription>
      </CardHeader>
      
      <CardContent className="space-y-6">
        {entries.length === 0 ? (
          <Alert>
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>No journal entries yet</AlertTitle>
            <AlertDescription>
              Close some shadow trades to start building your AI-analyzed trading journal
            </AlertDescription>
          </Alert>
        ) : (
          entries.map((entry) => {
            const parsed = parseAIFeedback(entry.ai_feedback);
            const pnlNum = parseFloat(entry.realized_pnl);
            const isProfitable = pnlNum >= 0;

            return (
              <Card key={entry.id} className="border-border">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold">{entry.symbol}</span>
                      <Badge variant={entry.side === "BUY" ? "default" : "secondary"}>
                        {entry.side}
                      </Badge>
                      {getGradeBadge(entry.quant_grade)}
                    </div>
                    <div className="text-right">
                      <div className="text-2xl font-bold">
                        {formatPnL(entry.realized_pnl)}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {entry.quantity} shares
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-4 text-sm text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Target className="h-3 w-3" />
                      Entry: {formatPrice(entry.entry_price)}
                    </div>
                    <div className="flex items-center gap-1">
                      <TrendingUp className="h-3 w-3" />
                      Exit: {formatPrice(entry.exit_price)}
                    </div>
                    {entry.market_regime && (
                      <Badge variant="outline" className="text-xs">
                        {entry.market_regime}
                      </Badge>
                    )}
                  </div>
                </CardHeader>

                <CardContent className="space-y-4">
                  {entry.error ? (
                    <Alert variant="destructive">
                      <AlertCircle className="h-4 w-4" />
                      <AlertDescription>{entry.error}</AlertDescription>
                    </Alert>
                  ) : (
                    <>
                      {/* AI Analysis */}
                      {parsed.analysis && (
                        <div>
                          <h4 className="font-semibold text-sm mb-2">AI Analysis</h4>
                          <p className="text-sm text-muted-foreground">{parsed.analysis}</p>
                        </div>
                      )}

                      <Separator />

                      {/* Quant Tips */}
                      {parsed.tips.length > 0 && (
                        <div>
                          <h4 className="font-semibold text-sm mb-2">Actionable Quant Tips</h4>
                          <ul className="space-y-2">
                            {parsed.tips.map((tip, idx) => (
                              <li key={idx} className="text-sm text-muted-foreground flex gap-2">
                                <span className="text-primary font-semibold">{idx + 1}.</span>
                                <span>{tip}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Regime Impact */}
                      {parsed.regimeImpact && (
                        <>
                          <Separator />
                          <div>
                            <h4 className="font-semibold text-sm mb-2">Market Regime Impact</h4>
                            <p className="text-sm text-muted-foreground">{parsed.regimeImpact}</p>
                          </div>
                        </>
                      )}

                      {/* Timestamp */}
                      <div className="flex items-center gap-1 text-xs text-muted-foreground">
                        <Clock className="h-3 w-3" />
                        Analyzed: {formatTimestamp(entry.analyzed_at)}
                      </div>
                    </>
                  )}
                </CardContent>
              </Card>
            );
          })
        )}
      </CardContent>
    </Card>
  );
};
