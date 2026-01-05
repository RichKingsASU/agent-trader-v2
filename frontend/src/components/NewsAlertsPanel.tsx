import { Card } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Newspaper, Bell, TrendingUp, AlertTriangle } from "lucide-react";

interface NewsItem {
  timestamp: string;
  headline: string;
  source: string;
  impact: "high" | "medium" | "low";
}

interface AlertItem {
  timestamp: string;
  headline: string;
  source: string;
  impact: "high" | "medium" | "low";
}

export function NewsAlertsPanel() {
  // Mock news data
  const newsItems: NewsItem[] = [
    {
      timestamp: new Date(Date.now() - 300000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Fed announces rate decision - holds steady at 5.25%",
      source: "Reuters",
      impact: "high",
    },
    {
      timestamp: new Date(Date.now() - 600000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Tech sector rallies on strong earnings from major players",
      source: "Bloomberg",
      impact: "medium",
    },
    {
      timestamp: new Date(Date.now() - 900000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Oil prices surge 3% on supply concerns",
      source: "CNBC",
      impact: "medium",
    },
    {
      timestamp: new Date(Date.now() - 1200000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Dollar strengthens against major currencies",
      source: "MarketWatch",
      impact: "low",
    },
    {
      timestamp: new Date(Date.now() - 1500000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Weekly jobless claims lower than expected",
      source: "WSJ",
      impact: "high",
    },
  ];

  // Mock alerts data
  const alertItems: AlertItem[] = [
    {
      timestamp: new Date(Date.now() - 180000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "SPY broke above 433 resistance - momentum strong",
      source: "Technical Alert",
      impact: "high",
    },
    {
      timestamp: new Date(Date.now() - 420000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Unusual options activity detected in QQQ Dec calls",
      source: "Flow Alert",
      impact: "high",
    },
    {
      timestamp: new Date(Date.now() - 720000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "VIX spike to 18.5 - volatility increasing",
      source: "Vol Alert",
      impact: "medium",
    },
    {
      timestamp: new Date(Date.now() - 1020000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "AAPL approaching key support at $175",
      source: "Technical Alert",
      impact: "medium",
    },
    {
      timestamp: new Date(Date.now() - 1320000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
      headline: "Market breadth improving - 70% stocks above 20-day MA",
      source: "Market Alert",
      impact: "low",
    },
  ];

  const getImpactBadge = (impact: "high" | "medium" | "low") => {
    const variants = {
      high: "destructive",
      medium: "default",
      low: "secondary",
    } as const;

    const icons = {
      high: <AlertTriangle className="h-3 w-3 mr-1" />,
      medium: <TrendingUp className="h-3 w-3 mr-1" />,
      low: null,
    };

    return (
      <Badge variant={variants[impact]} className="text-[10px] px-2 py-0.5">
        {icons[impact]}
        {impact.toUpperCase()}
      </Badge>
    );
  };

  return (
    <Card className="p-4">
      <Tabs defaultValue="news" className="w-full">
        <TabsList className="w-full grid grid-cols-2 mb-4">
          <TabsTrigger value="news" className="text-xs">
            <Newspaper className="h-3.5 w-3.5 mr-1.5" />
            News
          </TabsTrigger>
          <TabsTrigger value="alerts" className="text-xs">
            <Bell className="h-3.5 w-3.5 mr-1.5" />
            Alerts
          </TabsTrigger>
        </TabsList>

        <TabsContent value="news" className="mt-0">
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-3">
              {newsItems.map((item, index) => (
                <div
                  key={index}
                  className="border-b border-border pb-3 last:border-0 hover:bg-accent/5 transition-colors rounded-md p-2 -m-2"
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <span className="text-[10px] number-mono text-muted-foreground">
                      {item.timestamp}
                    </span>
                    {getImpactBadge(item.impact)}
                  </div>
                  <h4 className="text-sm font-medium leading-tight mb-1.5">
                    {item.headline}
                  </h4>
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-muted-foreground">{item.source}</span>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>

        <TabsContent value="alerts" className="mt-0">
          <ScrollArea className="h-[400px] pr-4">
            <div className="space-y-3">
              {alertItems.map((item, index) => (
                <div
                  key={index}
                  className="border-b border-border pb-3 last:border-0 hover:bg-accent/5 transition-colors rounded-md p-2 -m-2"
                >
                  <div className="flex items-start justify-between gap-2 mb-1.5">
                    <span className="text-[10px] number-mono text-muted-foreground">
                      {item.timestamp}
                    </span>
                    {getImpactBadge(item.impact)}
                  </div>
                  <h4 className="text-sm font-medium leading-tight mb-1.5">
                    {item.headline}
                  </h4>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px] px-2 py-0">
                      {item.source}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </Card>
  );
}
