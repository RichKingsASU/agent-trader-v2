import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { Layout, Scan, Target, Focus, Maximize2 } from "lucide-react";
import { useLayout } from "@/contexts/LayoutContext";
import { useLocation } from "react-router-dom";

export const LayoutControls = () => {
  const { layout, updateLayout, setWorkspace, currentWorkspace } = useLayout();
  const location = useLocation();

  // Show different widgets based on current route
  const isF1Dashboard = location.pathname === "/";
  const isLegacyDashboard = location.pathname === "/legacy";

  const f1Widgets = [
    { key: "showWatchlist" as const, label: "Watchlist Tower" },
    { key: "showTelemetry" as const, label: "Chart" },
    { key: "showBattleStation" as const, label: "Battle Station" },
    { key: "showRadioFeed" as const, label: "Radio Feed" },
    { key: "showVitalsBar" as const, label: "Vitals Bar" },
    { key: "showIndicatorStrip" as const, label: "Indicator Strip" },
    { key: "showOptionsChain" as const, label: "Options Chain" },
  ];

  const legacyWidgets = [
    { key: "showAccountPanel" as const, label: "Account & Risk" },
    { key: "showBotStatus" as const, label: "Bot Status" },
    { key: "showOptionsPositions" as const, label: "Options Positions" },
    { key: "showOrderTicket" as const, label: "Order Ticket" },
    { key: "showNews" as const, label: "News & Alerts" },
    { key: "showNotes" as const, label: "Trader Notes" },
    { key: "showKPIs" as const, label: "KPI Metrics" },
    { key: "showOptionsChain" as const, label: "Options Chain" },
    { key: "showTradeHistory" as const, label: "Trade History" },
  ];

  const widgets = isF1Dashboard ? f1Widgets : isLegacyDashboard ? legacyWidgets : f1Widgets;

  return (
    <div className="flex items-center gap-2">
      {/* Quick-Set Workspace Buttons */}
      <div className="flex items-center gap-1 mr-2 border-r border-border pr-2">
        <Button
          variant={currentWorkspace === "scan" ? "default" : "outline"}
          size="sm"
          onClick={() => setWorkspace("scan")}
          className="h-8 px-3"
          title="Scan Mode: News, KPIs, and History for market scanning"
        >
          <Scan className="h-4 w-4 mr-1" />
          <span className="text-xs">Scan</span>
        </Button>
        <Button
          variant={currentWorkspace === "trade" ? "default" : "outline"}
          size="sm"
          onClick={() => setWorkspace("trade")}
          className="h-8 px-3"
          title="Trade Mode: Chart, Order Ticket, and Options Chain for execution"
        >
          <Target className="h-4 w-4 mr-1" />
          <span className="text-xs">Trade</span>
        </Button>
        <Button
          variant={currentWorkspace === "focus" ? "default" : "outline"}
          size="sm"
          onClick={() => setWorkspace("focus")}
          className="h-8 px-3"
          title="Focus Mode: Chart only for distraction-free monitoring"
        >
          <Focus className="h-4 w-4 mr-1" />
          <span className="text-xs">Focus</span>
        </Button>
        <Button
          variant={currentWorkspace === "full" ? "default" : "outline"}
          size="sm"
          onClick={() => setWorkspace("full")}
          className="h-8 px-3"
          title="Full Mode: All widgets visible"
        >
          <Maximize2 className="h-4 w-4 mr-1" />
          <span className="text-xs">Full</span>
        </Button>
      </div>

      {/* Layout Widget Store Menu */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="outline" size="sm" className="h-8 px-3">
            <Layout className="h-4 w-4 mr-1" />
            <span className="text-xs">Layout</span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-64 z-[200]">
          <DropdownMenuLabel className="text-xs font-semibold uppercase tracking-wide">
            Widget Store
          </DropdownMenuLabel>
          <DropdownMenuSeparator />
          <div className="p-2 space-y-3 max-h-96 overflow-y-auto">
            {widgets.map(({ key, label }) => (
              <div key={key} className="flex items-center justify-between">
                <Label htmlFor={key} className="text-sm cursor-pointer">
                  {label}
                </Label>
                <Switch
                  id={key}
                  checked={layout[key]}
                  onCheckedChange={(checked) => updateLayout({ [key]: checked })}
                />
              </div>
            ))}
          </div>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
};
