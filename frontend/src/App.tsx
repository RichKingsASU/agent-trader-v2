import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "./contexts/ThemeContext";
import { LayoutProvider } from "./contexts/LayoutContext";
import { AuthProvider } from "./contexts/AuthContext";
import { UserTradingProvider } from "./contexts/UserTradingContext";
import { MainLayout } from "./layouts/MainLayout";
import Index from "./pages/Index";
import F1Dashboard from "./pages/F1Dashboard";
import Console from "./pages/Console";
import Options from "./pages/Options";
import OptionsDashboard from "./components/OptionsDashboard";
import Developer from "./pages/Developer";
import Auth from "./pages/Auth";
import Settings from "./pages/Settings";
import Allocation from "./pages/Allocation";
import NotFound from "./pages/NotFound";
import Landing from "./pages/Landing";
import Backtesting from "./pages/Backtesting";
import Analytics from "./pages/Analytics";
import WhaleFlow from "./pages/WhaleFlow";
import BacktestDashboard from "./pages/BacktestDashboard";

import OpsLayout from "./pages/ops/OpsLayout";
import OpsOverview from "./pages/ops/OpsOverview";
import OptionsExplorer from "./pages/ops/OptionsExplorer";
import NewsViewer from "./pages/ops/NewsViewer";
import JobHealth from "./pages/ops/JobHealth";
import OpsDebug from "./pages/ops/OpsDebug";
import MissionControl from "./pages/MissionControl";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <ThemeProvider>
      <LayoutProvider>
        <BrowserRouter>
          <AuthProvider>
            <UserTradingProvider>
              <TooltipProvider>
                <Toaster />
                <Sonner />
                <MainLayout>
                  <Routes>
                  <Route path="/" element={<F1Dashboard />} />
                  <Route path="/landing" element={<Landing />} />
                  <Route path="/auth" element={<Auth />} />
                  <Route path="/settings" element={<Settings />} />
                  <Route path="/allocation" element={<Allocation />} />
                  <Route path="/analytics" element={<Analytics />} />
                  <Route path="/legacy" element={<Index />} />
                  <Route path="/console/:symbol" element={<Console />} />
                  <Route path="/options" element={<Options />} />
                  <Route path="/options-dashboard" element={<OptionsDashboard />} />
                  <Route path="/whale-flow" element={<WhaleFlow />} />
                  <Route path="/developer" element={<Developer />} />
                  <Route path="/mission-control" element={<MissionControl />} />
                  <Route path="/backtest" element={<BacktestDashboard />} />
                  <Route path="/ops" element={<OpsLayout />}>
                    <Route index element={<OpsOverview />} />
                    <Route path="options" element={<OptionsExplorer />} />
                    <Route path="news" element={<NewsViewer />} />
                    <Route path="jobs" element={<JobHealth />} />
                    <Route path="debug" element={<OpsDebug />} />
                  </Route>
                  <Route path="/backtesting" element={<Backtesting />} />
                  
                  
                  {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </MainLayout>
            </TooltipProvider>
            </UserTradingProvider>
          </AuthProvider>
        </BrowserRouter>
      </LayoutProvider>
    </ThemeProvider>
  </QueryClientProvider>
);

export default App;
