import { Card } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Radio, TrendingUp, AlertCircle, Info } from "lucide-react";
import { useEffect, useRef } from "react";

interface NewsItem {
  time: string;
  headline: string;
  impact: "high" | "medium" | "low";
  keywords: string[];
}

const mockNews: NewsItem[] = [
  {
    time: "14:32",
    headline: "Fed Chair Powell signals potential rate cut in upcoming meeting",
    impact: "high",
    keywords: ["Fed", "Powell", "rate cut"],
  },
  {
    time: "14:28",
    headline: "NVDA announces new AI chip beating analyst expectations",
    impact: "high",
    keywords: ["NVDA", "AI chip"],
  },
  {
    time: "14:25",
    headline: "SPY breaks resistance at $432, volume surge detected",
    impact: "medium",
    keywords: ["SPY", "resistance", "volume"],
  },
  {
    time: "14:20",
    headline: "Tech sector leads market rally with 1.5% gains",
    impact: "medium",
    keywords: ["Tech", "rally"],
  },
  {
    time: "14:15",
    headline: "Oil prices dip 2% on inventory report",
    impact: "low",
    keywords: ["Oil", "inventory"],
  },
  {
    time: "14:10",
    headline: "AAPL trading above VWAP, bullish sentiment detected",
    impact: "medium",
    keywords: ["AAPL", "VWAP", "bullish"],
  },
];

export const RadioFeed = () => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Auto-scroll to bottom when new items are added
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  const getImpactIcon = (impact: string) => {
    switch (impact) {
      case "high":
        return <AlertCircle className="h-3 w-3" />;
      case "medium":
        return <TrendingUp className="h-3 w-3" />;
      default:
        return <Info className="h-3 w-3" />;
    }
  };

  const highlightKeywords = (text: string, keywords: string[]) => {
    let highlighted = text;
    keywords.forEach((keyword) => {
      const regex = new RegExp(`(${keyword})`, "gi");
      highlighted = highlighted.replace(
        regex,
        `<span class="text-primary font-bold">$1</span>`
      );
    });
    return highlighted;
  };

  return (
    <Card className="h-full bg-card/30 backdrop-blur-sm border-white/10">
      <div className="p-3 border-b border-white/10 flex items-center gap-2">
        <Radio className="h-4 w-4 text-primary" />
        <h3 className="text-xs font-bold uppercase tracking-wider ui-label">
          Radio Feed
        </h3>
        <Badge className="ml-auto bg-primary/20 text-primary border-primary/30 text-xs">
          LIVE
        </Badge>
      </div>
      <ScrollArea className="h-[calc(100%-3rem)]" ref={scrollRef}>
        <div className="p-3 space-y-2">
          {mockNews.map((item, idx) => (
            <div
              key={idx}
              className="p-3 rounded-lg bg-background/50 border border-white/5 hover:border-primary/20 transition-all animate-fade-in"
            >
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-xs number-mono text-muted-foreground font-medium">
                  {item.time}
                </span>
                <Badge
                  className={`text-xs px-1.5 py-0 ${
                    item.impact === "high"
                      ? "bg-bear/20 text-bear border-bear/30"
                      : item.impact === "medium"
                      ? "bg-yellow-500/20 text-yellow-500 border-yellow-500/30"
                      : "bg-muted/50 text-muted-foreground border-muted"
                  }`}
                >
                  {getImpactIcon(item.impact)}
                </Badge>
              </div>
              <p
                className="text-sm leading-relaxed"
                dangerouslySetInnerHTML={{
                  __html: highlightKeywords(item.headline, item.keywords),
                }}
              />
            </div>
          ))}
        </div>
      </ScrollArea>
    </Card>
  );
};
