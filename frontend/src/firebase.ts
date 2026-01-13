import { initializeApp, type FirebaseApp } from "firebase/app";
import { getFirestore, type Firestore, connectFirestoreEmulator } from "firebase/firestore";
import { getAuth, type Auth, connectAuthEmulator } from "firebase/auth";
import { getFunctions, type Functions, connectFunctionsEmulator } from "firebase/functions";
import { getStorage, type FirebaseStorage, connectStorageEmulator } from "firebase/storage";

type EmulatorHostPort = { host: string; port: number };

function parseHostPort(raw: string | undefined, fallback: EmulatorHostPort): EmulatorHostPort {
  if (!raw) return fallback;
  const trimmed = raw.trim();
  if (!trimmed) return fallback;
  const [hostRaw, portRaw] = trimmed.split(":");
  const host = (hostRaw || "").trim() || fallback.host;
  const port = Number((portRaw || "").trim());
  return { host, port: Number.isFinite(port) && port > 0 ? port : fallback.port };
}

function parseEmulatorHosts(raw: string | undefined): Partial<Record<"firestore" | "auth" | "functions" | "storage", string>> {
  if (!raw) return {};
  const trimmed = raw.trim();
  if (!trimmed) return {};

  // Supports either JSON: {"firestore":"localhost:8080", ...}
  // or CSV: firestore=localhost:8080,auth=localhost:9099,functions=localhost:5001,storage=localhost:9199
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      return {
        firestore: typeof parsed.firestore === "string" ? parsed.firestore : undefined,
        auth: typeof parsed.auth === "string" ? parsed.auth : undefined,
        functions: typeof parsed.functions === "string" ? parsed.functions : undefined,
        storage: typeof parsed.storage === "string" ? parsed.storage : undefined,
      };
    } catch {
      return {};
    }
  }

  const out: Partial<Record<"firestore" | "auth" | "functions" | "storage", string>> = {};
  for (const part of trimmed.split(",")) {
    const [kRaw, vRaw] = part.split("=");
    const k = (kRaw || "").trim();
    const v = (vRaw || "").trim();
    if (!v) continue;
    if (k === "firestore" || k === "auth" || k === "functions" || k === "storage") out[k] = v;
  }
  return out;
}

function getEmulatorConfig(): {
  firestore: EmulatorHostPort;
  authUrl: string;
  functions: EmulatorHostPort;
  storage: EmulatorHostPort;
} {
  const overrides = parseEmulatorHosts(import.meta.env.VITE_FIREBASE_EMULATOR_HOSTS);
  const firestore = parseHostPort(overrides.firestore, { host: "localhost", port: 8080 });
  const functions = parseHostPort(overrides.functions, { host: "localhost", port: 5001 });
  const storage = parseHostPort(overrides.storage, { host: "localhost", port: 9199 });

  const authHostPort = parseHostPort(overrides.auth, { host: "localhost", port: 9099 });
  const authUrl =
    overrides.auth && overrides.auth.trim().startsWith("http")
      ? overrides.auth.trim()
      : `http://${authHostPort.host}:${authHostPort.port}`;

  return { firestore, authUrl, functions, storage };
}

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey &&
    firebaseConfig.authDomain &&
    firebaseConfig.projectId &&
    firebaseConfig.appId,
);

// Initialize Firebase (only if configured; local/dev should run without external SaaS)
const app: FirebaseApp | null = isFirebaseConfigured ? initializeApp(firebaseConfig) : null;
const db: Firestore | null = app ? getFirestore(app) : null;
const auth: Auth | null = app ? getAuth(app) : null;
const functions: Functions | null = app ? getFunctions(app) : null;
const storage: FirebaseStorage | null = app ? getStorage(app) : null;

let emulatorsConnected = false;
function connectEmulatorsIfEnabled(): void {
  // Safety rule: in local dev, use emulators by default unless explicitly disabled.
  if (!import.meta.env.DEV) return;
  const useEmulators = String(import.meta.env.VITE_USE_FIREBASE_EMULATORS ?? "true") !== "false";
  if (!useEmulators) return;
  if (emulatorsConnected) return;
  if (!app) return;

  emulatorsConnected = true;
  const cfg = getEmulatorConfig();
  if (db) connectFirestoreEmulator(db, cfg.firestore.host, cfg.firestore.port);
  if (auth) connectAuthEmulator(auth, cfg.authUrl, { disableWarnings: true });
  if (functions) connectFunctionsEmulator(functions, cfg.functions.host, cfg.functions.port);
  if (storage) connectStorageEmulator(storage, cfg.storage.host, cfg.storage.port);
}

connectEmulatorsIfEnabled();

export { db, auth, app, functions, storage };
