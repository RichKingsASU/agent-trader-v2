import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Sparkles, TrendingUp, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";

interface AIAnalysis {
  grade: string;
  feedback: string;
  analyzed_at?: string;
  model?: string;
}

interface AIPostGameProps {
  analysis?: AIAnalysis;
  pnl?: number;
  className?: string;
}

/**
 * AIPostGame - AI-Powered Trade Analysis Display
 * 
 * Displays Gemini 1.5 Flash analysis of closed trades with:
 * - Letter grade (A-F) based on trade discipline
 * - Actionable "Quant Tip" for improvement
 * 
 * Usage:
 *   <AIPostGame analysis={trade.ai_analysis} pnl={trade.pnl_usd} />
 */
export function AIPostGame({ analysis, pnl = 0, className }: AIPostGameProps) {
  if (!analysis || analysis.grade === "ERROR" || analysis.grade === "N/A") {
    return null;
  }

  // Grade color mapping
  const getGradeColor = (grade: string): string => {
    const letter = grade.charAt(0).toUpperCase();
    switch (letter) {
      case "A":
        return "bg-green-500/20 text-green-400 border-green-500/40";
      case "B":
        return "bg-blue-500/20 text-blue-400 border-blue-500/40";
      case "C":
        return "bg-yellow-500/20 text-yellow-400 border-yellow-500/40";
      case "D":
        return "bg-orange-500/20 text-orange-400 border-orange-500/40";
      case "F":
        return "bg-red-500/20 text-red-400 border-red-500/40";
      default:
        return "bg-gray-500/20 text-gray-400 border-gray-500/40";
    }
  };

  // Get icon based on grade
  const getGradeIcon = (grade: string) => {
    const letter = grade.charAt(0).toUpperCase();
    if (letter === "A" || letter === "B") {
      return <TrendingUp className="h-4 w-4" />;
    }
    return <AlertCircle className="h-4 w-4" />;
  };

  const gradeColor = getGradeColor(analysis.grade);
  const gradeIcon = getGradeIcon(analysis.grade);

  return (
    <Card
      className={cn(
        "p-4 border-purple-500/30 bg-gradient-to-br from-purple-500/10 to-transparent",
        className
      )}
    >
      <div className="flex items-start gap-3">
        {/* AI Icon */}
        <div className="p-2 rounded-lg bg-purple-500/20 border border-purple-500/40">
          <Sparkles className="h-5 w-5 text-purple-400" />
        </div>

        {/* Content */}
        <div className="flex-1 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-semibold text-foreground">
                AI Post-Game Analysis
              </h4>
              {analysis.model && (
                <span className="text-xs text-muted-foreground">
                  ({analysis.model})
                </span>
              )}
            </div>

            {/* Grade Badge */}
            <Badge
              className={cn(
                "text-base font-bold px-3 py-1 rounded-full border-2",
                gradeColor
              )}
            >
              <span className="flex items-center gap-1">
                {gradeIcon}
                Grade: {analysis.grade}
              </span>
            </Badge>
          </div>

          {/* Quant Tip */}
          <div className="p-3 rounded-md bg-background/60 border border-purple-500/20">
            <p className="text-xs text-muted-foreground font-semibold uppercase tracking-wide mb-1">
              Quant Tip:
            </p>
            <p className="text-sm text-foreground leading-relaxed">
              {analysis.feedback}
            </p>
          </div>

          {/* Timestamp */}
          {analysis.analyzed_at && (
            <p className="text-xs text-muted-foreground">
              Analyzed: {new Date(analysis.analyzed_at).toLocaleString()}
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
