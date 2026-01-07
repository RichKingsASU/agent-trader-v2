import React, { createContext, useContext, useEffect, useState } from "react";
import { 
  getAuth, 
  onAuthStateChanged, 
  signInWithPopup, 
  GoogleAuthProvider, 
  signOut,
  User,
  getIdTokenResult,
} from "firebase/auth";
import { onSnapshot } from "firebase/firestore";

import { auth, db } from "../firebase";
import { tenantDoc } from "@/lib/tenancy/firestore";
import { isOperatorEmail } from "@/lib/auth/operatorAccess";

const ENABLE_PROFILE_DOC =
  ((import.meta.env.VITE_ENABLE_FIRESTORE_PROFILE as string | undefined) ?? "false").trim().toLowerCase() === "true";

export interface UserProfile {
  display_name?: string | null;
  trading_mode?: "paper" | "live" | string | null;
  avatar_url?: string | null;
  [key: string]: unknown;
}



interface AuthContextType {
  user: User | null;
  tenantId: string | null;
  profile: UserProfile | null;
  loading: boolean;
  isOperator: boolean;
  authError: string | null;
  login: () => Promise<void>;
  logout: () => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [isOperator, setIsOperator] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setLoading(true);
      setAuthError(null);

      if (!user) {
        setUser(null);
        setTenantId(null);
        setProfile(null);
        setIsOperator(false);
        setLoading(false);
        return;
      }

      (async () => {
        // Operator-only access: enforce allowlist based on email/domain.
        if (!isOperatorEmail(user.email)) {
          setAuthError("This account is not authorized to access this dashboard.");
          setUser(null);
          setTenantId(null);
          setProfile(null);
          setIsOperator(false);
          setLoading(false);
          await signOut(auth);
          return;
        }

        setUser(user);
        setIsOperator(true);
        const token = await getIdTokenResult(user);
        const claim = (token.claims as any)?.tenant_id ?? (token.claims as any)?.tenantId ?? null;
        setTenantId(typeof claim === "string" && claim.trim() ? claim.trim() : null);
        setLoading(false);
      })().catch((err) => {
        console.error("Failed to load tenant_id from token claims:", err);
        setUser(user);
        setIsOperator(isOperatorEmail(user.email));
        setTenantId(null);
        setProfile(null);
        setLoading(false);
      });
    });
    return unsubscribe;
  }, []);

  // Keep a live profile doc in context (tenant-scoped).
  useEffect(() => {
    if (!ENABLE_PROFILE_DOC) {
      setProfile(null);
      return;
    }

    if (!user || !tenantId) {
      setProfile(null);
      return;
    }

    const ref = tenantDoc(db, tenantId, "profiles", user.uid);
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

  const login = async () => {
    const googleProvider = new GoogleAuthProvider();
    await signInWithPopup(auth, googleProvider);
  };

  const logout = async () => {
    await signOut(auth);
  };

  return (
    <AuthContext.Provider
      value={{ user, tenantId, profile, loading, isOperator, authError, login, logout, signOut: logout }}
    >
      {!loading && children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};