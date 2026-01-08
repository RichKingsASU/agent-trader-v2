import * as React from "react";
import { signInAnonymously, signOut } from "firebase/auth";
import { auth, isFirebaseConfigured } from "@/firebase";
import { ErrorBanner } from "@/components/ErrorBanner";
import { useAuthUser } from "@/hooks/useAuthUser";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading, error } = useAuthUser();
  const [actionError, setActionError] = React.useState<string | null>(null);

  if (!isFirebaseConfigured) {
    return (
      <div className="grid">
        <div className="card" style={{ gridColumn: "span 12" }}>
          <h2>Firebase not configured</h2>
          <div className="muted">
            Set Firebase config via <span className="mono">window.__OPS_DASHBOARD_CONFIG__.firebase</span> (runtime{" "}
            <span className="mono">config.js</span>) or Vite env vars <span className="mono">VITE_FIREBASE_*</span>.
          </div>
        </div>
      </div>
    );
  }

  if (error) return <ErrorBanner message={`Auth error: ${error}`} />;
  if (!auth) return <ErrorBanner message="Firebase Auth is unavailable (client not initialized)." />;

  if (!user) {
    return (
      <div className="grid">
        <div style={{ gridColumn: "span 12" }}>
          {actionError ? <ErrorBanner message={actionError} /> : null}
        </div>
        <div className="card" style={{ gridColumn: "span 12" }}>
          <h2>Sign in</h2>
          <div className="muted" style={{ marginBottom: 10 }}>
            This dashboard is read-only and uses Firestore realtime listeners.
          </div>
          <button
            disabled={isLoading}
            onClick={async () => {
              setActionError(null);
              try {
                await signInAnonymously(auth);
              } catch (e) {
                setActionError(e instanceof Error ? e.message : String(e));
              }
            }}
          >
            Continue (anonymous auth)
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="meta" style={{ marginBottom: 10 }}>
        Signed in: <span className="mono">{user.uid}</span>{" "}
        <button
          style={{ marginLeft: 10 }}
          onClick={async () => {
            setActionError(null);
            try {
              await signOut(auth);
            } catch (e) {
              setActionError(e instanceof Error ? e.message : String(e));
            }
          }}
        >
          Sign out
        </button>
      </div>
      {actionError ? <ErrorBanner message={actionError} /> : null}
      {children}
    </>
  );
}

