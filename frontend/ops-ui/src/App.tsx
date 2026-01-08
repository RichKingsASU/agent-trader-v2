import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { AuthGate } from "@/components/AuthGate";
import { OverviewFirestorePage } from "@/pages/OverviewFirestorePage";
import { IngestHealthPage } from "@/pages/IngestHealthPage";
import { ServiceDetailPage } from "@/pages/ServiceDetailPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

export function App() {
  return (
    <BrowserRouter>
      <Layout>
        <AuthGate>
          <Routes>
            <Route path="/" element={<OverviewFirestorePage />} />
            <Route path="/ingest" element={<IngestHealthPage />} />
            <Route path="/services/:serviceId" element={<ServiceDetailPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </AuthGate>
      </Layout>
    </BrowserRouter>
  );
}

