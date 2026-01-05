import { Badge } from "@/components/ui/badge";
import type { LiveStatus } from "@/hooks/useMarketLiveQuotes";

interface SystemStatusBadgeProps {
  status: LiveStatus;
  heartbeatAt?: Date | null;
  title?: string;
  className?: string;
}

export function SystemStatusBadge({ status, heartbeatAt, title, className }: SystemStatusBadgeProps) {
  const effectiveTitle =
    title ?? (heartbeatAt ? `Last heartbeat: ${heartbeatAt.toLocaleString()}` : undefined);
  const base = "text-[10px] px-2 py-1 border";

  if (status === "LIVE") {
    return (
      <Badge
        title={effectiveTitle}
        className={`${base} bg-bull/20 text-bull border-bull/30 ${className ?? ""}`}
      >
        LIVE
      </Badge>
    );
  }

  if (status === "STALE") {
    return (
      <Badge
        title={effectiveTitle}
        className={`${base} bg-amber-500/15 text-amber-600 border-amber-500/30 ${className ?? ""}`}
      >
        STALE
      </Badge>
    );
  }

  return (
    <Badge
      title={effectiveTitle}
      className={`${base} bg-bear/20 text-bear border-bear/30 ${className ?? ""}`}
    >
      OFFLINE
    </Badge>
  );
}

