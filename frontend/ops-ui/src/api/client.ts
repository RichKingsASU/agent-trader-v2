import type {
  AgentDetailResponse,
  DeployReportResponse,
  MissionControlAgentsResponse,
  MissionControlEventsResponse,
  SafetyResponse,
} from "@/api/types";

type ApiResult<T> =
  | { ok: true; data: T; status: number }
  | { ok: false; error: string; status?: number };

function normalizeBaseUrl(raw: string): string {
  return raw.replace(/\/+$/, "");
}

function getBaseUrl(): string {
  const runtime = window.__OPS_UI_CONFIG__?.missionControlBaseUrl;
  const env = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_MISSION_CONTROL_BASE_URL;
  return normalizeBaseUrl(runtime || env || "http://agenttrader-mission-control");
}

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const t = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(t);
  }
}

export async function getJson<T>(path: string, timeoutMs = 7000): Promise<ApiResult<T>> {
  const base = getBaseUrl();
  const url = `${base}${path}`;
  try {
    const res = await fetchWithTimeout(
      url,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
        },
      },
      timeoutMs,
    );
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status} from Mission Control` };
    const data = (await res.json()) as T;
    return { ok: true, data, status: res.status };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: `Cannot reach API (${msg})` };
  }
}

export async function getText(path: string, timeoutMs = 7000): Promise<ApiResult<string>> {
  const base = getBaseUrl();
  const url = `${base}${path}`;
  try {
    const res = await fetchWithTimeout(
      url,
      {
        method: "GET",
        headers: {
          Accept: "text/plain, text/markdown, application/json",
        },
      },
      timeoutMs,
    );
    if (!res.ok) return { ok: false, status: res.status, error: `HTTP ${res.status} from Mission Control` };
    const contentType = res.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const json = (await res.json()) as DeployReportResponse;
      if (typeof json === "string") return { ok: true, data: json, status: res.status };
      const md = json.deploy_report_md || json.markdown || json.report_md || json.content;
      return { ok: true, data: md ? String(md) : JSON.stringify(json, null, 2), status: res.status };
    }
    const text = await res.text();
    return { ok: true, data: text, status: res.status };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, error: `Cannot reach API (${msg})` };
  }
}

export const missionControlApi = {
  listAgents: () => getJson<MissionControlAgentsResponse>("/api/v1/agents"),
  getAgent: (agentName: string) => getJson<AgentDetailResponse>(`/api/v1/agents/${encodeURIComponent(agentName)}`),
  getSafety: () => getJson<SafetyResponse>("/api/v1/safety"),
  listRecentEvents: () => getJson<MissionControlEventsResponse>("/api/v1/events/recent"),
  getLatestDeployReport: () => getText("/api/v1/reports/deploy/latest"),
  getBaseUrl,
};

