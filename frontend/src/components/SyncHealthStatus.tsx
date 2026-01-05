import { useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type SyncLight = "Green" | "Yellow" | "Red" | "Gray";

function computeSyncLight(updatedAt: Date | null, loading: boolean): SyncLight {
  if (loading) return "Gray";
  if (!updatedAt) return "Red";

  const ageSec = (Date.now() - updatedAt.getTime()) / 1000;
  if (ageSec <= 60) return "Green";
  if (ageSec <= 300) return "Yellow";
  return "Red";
}

function badgeClassFor(light: SyncLight): string {
  const base = "text-[10px] px-2 py-1 border ui-label";
  if (light === "Green") return `${base} bg-bull/20 text-bull border-bull/30`;
  if (light === "Yellow") return `${base} bg-amber-500/15 text-amber-600 border-amber-500/30`;
  if (light === "Red") return `${base} bg-bear/20 text-bear border-bear/30`;
  return `${base} bg-white/5 text-slate-200 border-white/10`;
}

function firebaseConsoleFunctionUrl(projectId: string, region?: string, functionName?: string): string {
  // If we know the function, link directly to it; otherwise link to the Functions list.
  if (functionName && functionName.trim().length > 0) {
    const r = (region && region.trim().length > 0 ? region.trim() : "us-central1").replaceAll("/", "");
    const fn = encodeURIComponent(functionName.trim());
    // Firebase Console Functions detail page.
    return `https://console.firebase.google.com/project/${encodeURIComponent(projectId)}/functions/details/${encodeURIComponent(r)}/${fn}`;
  }
  return `https://console.firebase.google.com/project/${encodeURIComponent(projectId)}/functions`;
}

export function SyncHealthStatus({
  updatedAt,
  loading = false,
  className,
}: {
  updatedAt: Date | null;
  loading?: boolean;
  className?: string;
}) {
  const light = useMemo(() => computeSyncLight(updatedAt, loading), [updatedAt, loading]);
  const title = updatedAt ? `Account sync updated: ${updatedAt.toLocaleString()}` : "Account sync updated: none";

  const projectId = (import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined) ?? "";
  const functionName = (import.meta.env.VITE_SYNC_FUNCTION_NAME as string | undefined) ?? "";
  const region = (import.meta.env.VITE_SYNC_FUNCTION_REGION as string | undefined) ?? "";

  const syncUrl = projectId ? firebaseConsoleFunctionUrl(projectId, region, functionName) : "";

  return (
    <div className={`flex items-center gap-2 ${className ?? ""}`}>
      <Badge title={title} className={badgeClassFor(light)}>
        SYNC {light === "Green" ? "OK" : light === "Yellow" ? "STALE" : light === "Red" ? "RED" : "…"}
      </Badge>

      {light === "Red" && (
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-7 px-2 text-[10px] border-white/10 bg-transparent hover:bg-accent/10"
          disabled={!syncUrl}
          title={
            syncUrl
              ? "Open Firebase Console to manually trigger the sync function"
              : "Missing VITE_FIREBASE_PROJECT_ID; cannot build console link"
          }
        >
          <a href={syncUrl || "#"} target="_blank" rel="noreferrer">
            Sync Now
          </a>
        </Button>
      )}
    </div>
  );
}

