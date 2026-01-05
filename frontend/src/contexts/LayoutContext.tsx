import { createContext, useContext, useState, useEffect, ReactNode } from "react";

export interface LayoutState {
  showAccountPanel: boolean;
  showBotStatus: boolean;
  showOptionsPositions: boolean;
  showOrderTicket: boolean;
  showNews: boolean;
  showNotes: boolean;
  showKPIs: boolean;
  showOptionsChain: boolean;
  showTradeHistory: boolean;
  // F1 Dashboard widgets
  showWatchlist: boolean;
  showTelemetry: boolean;
  showBattleStation: boolean;
  showRadioFeed: boolean;
  showVitalsBar: boolean;
  showIndicatorStrip: boolean;
}

export type WorkspacePreset = "scan" | "trade" | "focus" | "full";

const defaultLayout: LayoutState = {
  showAccountPanel: true,
  showBotStatus: true,
  showOptionsPositions: true,
  showOrderTicket: true,
  showNews: true,
  showNotes: true,
  showKPIs: true,
  showOptionsChain: true,
  showTradeHistory: true,
  // F1 Dashboard widgets
  showWatchlist: true,
  showTelemetry: true,
  showBattleStation: true,
  showRadioFeed: true,
  showVitalsBar: true,
  showIndicatorStrip: true,
};

const workspacePresets: Record<WorkspacePreset, LayoutState> = {
  scan: {
    showAccountPanel: true,
    showBotStatus: true,
    showOptionsPositions: false,
    showOrderTicket: false,
    showNews: true,
    showNotes: true,
    showKPIs: true,
    showOptionsChain: false,
    showTradeHistory: true,
    // F1: Watchlist + Chart + News + Vitals
    showWatchlist: true,
    showTelemetry: true,
    showBattleStation: false,
    showRadioFeed: true,
    showVitalsBar: true,
    showIndicatorStrip: true,
  },
  trade: {
    showAccountPanel: true,
    showBotStatus: true,
    showOptionsPositions: true,
    showOrderTicket: true,
    showNews: false,
    showNotes: false,
    showKPIs: false,
    showOptionsChain: true,
    showTradeHistory: false,
    // F1: Watchlist + Chart + Battle Station + Vitals
    showWatchlist: true,
    showTelemetry: true,
    showBattleStation: true,
    showRadioFeed: false,
    showVitalsBar: true,
    showIndicatorStrip: true,
  },
  focus: {
    showAccountPanel: true,
    showBotStatus: false,
    showOptionsPositions: false,
    showOrderTicket: false,
    showNews: false,
    showNotes: false,
    showKPIs: false,
    showOptionsChain: false,
    showTradeHistory: false,
    // F1: Chart + Vitals only
    showWatchlist: false,
    showTelemetry: true,
    showBattleStation: false,
    showRadioFeed: false,
    showVitalsBar: true,
    showIndicatorStrip: false,
  },
  full: defaultLayout,
};

interface LayoutContextType {
  layout: LayoutState;
  updateLayout: (updates: Partial<LayoutState>) => void;
  setWorkspace: (preset: WorkspacePreset) => void;
  currentWorkspace: WorkspacePreset | null;
}

const LayoutContext = createContext<LayoutContextType | undefined>(undefined);

const STORAGE_KEY = "dashboard-layout";

export const LayoutProvider = ({ children }: { children: ReactNode }) => {
  const [layout, setLayout] = useState<LayoutState>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      const savedLayout = JSON.parse(saved);
      // Merge saved data with default to ensure all new properties exist
      return { ...defaultLayout, ...savedLayout };
    }
    return defaultLayout;
  });
  const [currentWorkspace, setCurrentWorkspace] = useState<WorkspacePreset | null>(null);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  }, [layout]);

  const updateLayout = (updates: Partial<LayoutState>) => {
    setLayout((prev) => ({ ...prev, ...updates }));
    setCurrentWorkspace(null); // Clear preset when manually changing
  };

  const setWorkspace = (preset: WorkspacePreset) => {
    setLayout(workspacePresets[preset]);
    setCurrentWorkspace(preset);
  };

  return (
    <LayoutContext.Provider value={{ layout, updateLayout, setWorkspace, currentWorkspace }}>
      {children}
    </LayoutContext.Provider>
  );
};

export const useLayout = () => {
  const context = useContext(LayoutContext);
  if (!context) {
    throw new Error("useLayout must be used within LayoutProvider");
  }
  return context;
};
