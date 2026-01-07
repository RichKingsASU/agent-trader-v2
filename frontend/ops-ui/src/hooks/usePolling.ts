import * as React from "react";

export function usePolling<T>(
  loader: () => Promise<{ ok: true; data: T } | { ok: false; error: string }>,
  intervalMs = 10_000,
) {
  const [data, setData] = React.useState<T | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [lastRefreshed, setLastRefreshed] = React.useState<Date | null>(null);

  React.useEffect(() => {
    let isMounted = true;
    let inFlight = false;

    const tick = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const res = await loader();
        if (!isMounted) return;
        if (res.ok) {
          setData(res.data);
          setError(null);
          setLastRefreshed(new Date());
        } else {
          // Keep last good data; show error banner.
          setError(res.error);
          setLastRefreshed(new Date());
        }
      } finally {
        if (isMounted) setIsLoading(false);
        inFlight = false;
      }
    };

    void tick();
    const id = window.setInterval(() => void tick(), intervalMs);
    return () => {
      isMounted = false;
      window.clearInterval(id);
    };
  }, [loader, intervalMs]);

  return { data, error, isLoading, lastRefreshed };
}

