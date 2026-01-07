import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

import { isFirebaseConfigured, auth as firebaseAuth, db as firebaseDb } from "@/firebase";

// Optional Firebase imports (only used when configured)
import {
  GoogleAuthProvider,
  getIdTokenResult,
  onAuthStateChanged,
  signInWithPopup,
  signOut as firebaseSignOut,
} from "firebase/auth";
import { onSnapshot } from "firebase/firestore";

import { tenantDoc } from "@/lib/tenancy/firestore";

export interface AuthUser {
  uid: string;
  email?: string | null;
  displayName?: string | null;
  photoURL?: string | null;
}

export interface UserProfile {
  display_name?: string | null;
  trading_mode?: "paper" | "live" | string | null;
  avatar_url?: string | null;
  [key: string]: unknown;
}

interface AuthContextType {
  user: AuthUser | null;
  tenantId: string | null;
  profile: UserProfile | null;
  loading: boolean;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const LOCAL_USER_STORAGE_KEY = "agenttrader.local_user";

function readLocalUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(LOCAL_USER_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AuthUser> | null;
    if (!parsed || typeof parsed.uid !== "string" || !parsed.uid.trim()) return null;
    return {
      uid: parsed.uid,
      email: typeof parsed.email === "string" ? parsed.email : parsed.email ?? null,
      displayName: typeof parsed.displayName === "string" ? parsed.displayName : parsed.displayName ?? null,
      photoURL: typeof parsed.photoURL === "string" ? parsed.photoURL : parsed.photoURL ?? null,
    };
  } catch {
    return null;
  }
}

function writeLocalUser(user: AuthUser | null) {
  if (typeof window === "undefined") return;
  try {
    if (!user) {
      window.localStorage.removeItem(LOCAL_USER_STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(LOCAL_USER_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // ignore
  }
}

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);

  // Bootstrap: either Firebase auth state, or local/dev state.
  useEffect(() => {
    // Local mode: no Firebase configuration present.
    if (!isFirebaseConfigured || !firebaseAuth) {
      const local = readLocalUser();
      setUser(local);
      setTenantId(null);
      setProfile(null);
      setLoading(false);
      return;
    }

    const unsubscribe = onAuthStateChanged(firebaseAuth, (fbUser) => {
      if (!fbUser) {
        setUser(null);
        setTenantId(null);
        setProfile(null);
        setLoading(false);
        return;
      }

      setUser({
        uid: fbUser.uid,
        email: fbUser.email ?? null,
        displayName: fbUser.displayName ?? null,
        photoURL: fbUser.photoURL ?? null,
      });

      (async () => {
        const token = await getIdTokenResult(fbUser);
        const claim = (token.claims as any)?.tenant_id ?? (token.claims as any)?.tenantId ?? null;
        setTenantId(typeof claim === "string" && claim.trim() ? claim.trim() : null);
        setLoading(false);
      })().catch((err) => {
        console.error("Failed to load tenant_id from token claims:", err);
        setTenantId(null);
        setProfile(null);
        setLoading(false);
      });
    });

    return unsubscribe;
  }, []);

  // Keep a live profile doc in context (tenant-scoped) when Firebase is enabled.
  useEffect(() => {
    if (!isFirebaseConfigured || !firebaseDb) return;
    if (!user || !tenantId) {
      setProfile(null);
      return;
    }

    const ref = tenantDoc(firebaseDb, tenantId, "profiles", user.uid);
    const unsub = onSnapshot(
      ref,
      (snap) => setProfile((snap.exists() ? (snap.data() as UserProfile) : null) ?? null),
      (err) => {
        console.error("Failed to subscribe to profile:", err);
        setProfile(null);
      },
    );

    return () => unsub();
  }, [user, tenantId]);

  const login = useMemo(() => {
    return async () => {
      // Local mode: create a stable local user so the UI can be exercised without Firebase.
      if (!isFirebaseConfigured || !firebaseAuth) {
        const next: AuthUser = {
          uid: "local",
          email: "local@example.com",
          displayName: "Local User",
          photoURL: null,
        };
        setUser(next);
        setTenantId(null);
        setProfile(null);
        writeLocalUser(next);
        return;
      }

      const googleProvider = new GoogleAuthProvider();
      await signInWithPopup(firebaseAuth, googleProvider);
    };
  }, []);

  const logout = useMemo(() => {
    return async () => {
      if (!isFirebaseConfigured || !firebaseAuth) {
        writeLocalUser(null);
        setUser(null);
        setTenantId(null);
        setProfile(null);
        return;
      }
      await firebaseSignOut(firebaseAuth);
    };
  }, []);

  return (
    <AuthContext.Provider value={{ user, tenantId, profile, loading, login, logout, signOut: logout }}>
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};

