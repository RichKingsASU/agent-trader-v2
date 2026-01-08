import * as React from "react";
import type { User } from "firebase/auth";
import { onAuthStateChanged } from "firebase/auth";
import { auth } from "@/firebase";

export function useAuthUser(): { user: User | null; isLoading: boolean; error: string | null } {
  const [user, setUser] = React.useState<User | null>(null);
  const [isLoading, setIsLoading] = React.useState<boolean>(Boolean(auth));
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!auth) {
      setIsLoading(false);
      setUser(null);
      setError(null);
      return;
    }
    const unsub = onAuthStateChanged(
      auth,
      (u) => {
        setUser(u);
        setIsLoading(false);
      },
      (e) => {
        setError(e instanceof Error ? e.message : String(e));
        setIsLoading(false);
      },
    );
    return () => unsub();
  }, []);

  return { user, isLoading, error };
}

