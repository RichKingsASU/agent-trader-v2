import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";
import { Link } from "react-router-dom";
import { missionControlApi } from "@/api/client";
import { ErrorBanner } from "@/components/ErrorBanner";
import { usePolling } from "@/hooks/usePolling";
import { formatIso } from "@/utils/time";

export function DeployReportPage() {
  const loader = React.useCallback(async () => {
    const res = await missionControlApi.getLatestDeployReport();
    return res.ok ? ({ ok: true, data: res.data } as const) : ({ ok: false, error: res.error } as const);
  }, []);

  const poll = usePolling(loader, 10_000);
  const md = poll.data || "";

  return (
    <div className="grid">
      <div style={{ gridColumn: "span 12" }}>
        <div style={{ marginBottom: 8 }}>
          <Link to="/">← Overview</Link>
        </div>
        {poll.error ? <ErrorBanner message={poll.error} /> : null}
        <div className="meta" style={{ marginTop: 8 }}>
          Last refreshed: <span className="mono">{formatIso(poll.lastRefreshed)}</span>
        </div>
      </div>

      <div className="card" style={{ gridColumn: "span 12" }}>
        <h2>Latest deploy report</h2>
        {md.trim().length === 0 ? (
          <div className="muted">{poll.isLoading ? "Loading…" : "No deploy report content available."}</div>
        ) : (
          <div className="markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeSanitize]}
              components={{
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noreferrer noopener">
                    {children}
                  </a>
                ),
              }}
            >
              {md}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

