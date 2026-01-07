import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { OverviewPage } from "@/pages/OverviewPage";
import { AgentDetailPage } from "@/pages/AgentDetailPage";
import { DeployReportPage } from "@/pages/DeployReportPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/agents/:name" element={<AgentDetailPage />} />
          <Route path="/reports/deploy" element={<DeployReportPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

