import { initializeApp, type FirebaseApp, getApps } from "firebase/app";
import { getAuth, type Auth, connectAuthEmulator } from "firebase/auth";
import { getFirestore, type Firestore, connectFirestoreEmulator } from "firebase/firestore";
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

function getEmulatorConfig(env: Record<string, unknown>): {
  firestore: EmulatorHostPort;
  authUrl: string;
  functions: EmulatorHostPort;
  storage: EmulatorHostPort;
} {
  const rawHosts = typeof env.VITE_FIREBASE_EMULATOR_HOSTS === "string" ? env.VITE_FIREBASE_EMULATOR_HOSTS : undefined;
  const overrides = parseEmulatorHosts(rawHosts);

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

type FirebaseConfigShape = {
  apiKey?: string;
  authDomain?: string;
  projectId?: string;
  storageBucket?: string;
  messagingSenderId?: string;
  appId?: string;
};

function getRuntimeFirebaseConfig(): FirebaseConfigShape | undefined {
  return window.__OPS_DASHBOARD_CONFIG__?.firebase;
}

const runtime = getRuntimeFirebaseConfig() || {};
const env = (import.meta as unknown as { env?: Record<string, unknown> }).env || {};

const firebaseConfig = {
  apiKey: runtime.apiKey || (typeof env.VITE_FIREBASE_API_KEY === "string" ? env.VITE_FIREBASE_API_KEY : undefined),
  authDomain:
    runtime.authDomain || (typeof env.VITE_FIREBASE_AUTH_DOMAIN === "string" ? env.VITE_FIREBASE_AUTH_DOMAIN : undefined),
  projectId:
    runtime.projectId || (typeof env.VITE_FIREBASE_PROJECT_ID === "string" ? env.VITE_FIREBASE_PROJECT_ID : undefined),
  storageBucket:
    runtime.storageBucket ||
    (typeof env.VITE_FIREBASE_STORAGE_BUCKET === "string" ? env.VITE_FIREBASE_STORAGE_BUCKET : undefined),
  messagingSenderId:
    runtime.messagingSenderId ||
    (typeof env.VITE_FIREBASE_MESSAGING_SENDER_ID === "string" ? env.VITE_FIREBASE_MESSAGING_SENDER_ID : undefined),
  appId: runtime.appId || (typeof env.VITE_FIREBASE_APP_ID === "string" ? env.VITE_FIREBASE_APP_ID : undefined),
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId && firebaseConfig.appId,
);

let app: FirebaseApp | null = null;
let db: Firestore | null = null;
let auth: Auth | null = null;
let functions: Functions | null = null;
let storage: FirebaseStorage | null = null;

if (isFirebaseConfigured) {
  app = getApps().length ? getApps()[0]! : initializeApp(firebaseConfig);
  db = getFirestore(app);
  auth = getAuth(app);
  functions = getFunctions(app);
  storage = getStorage(app);
}

let emulatorsConnected = false;
function connectEmulatorsIfEnabled(): void {
  if (!Boolean(env.DEV)) return;
  const rawUseEmulators =
    typeof env.VITE_USE_FIREBASE_EMULATORS === "string" ? env.VITE_USE_FIREBASE_EMULATORS : undefined;
  const useEmulators = String(rawUseEmulators ?? "true") !== "false";
  if (!useEmulators) return;
  if (emulatorsConnected) return;
  if (!app) return;

  emulatorsConnected = true;
  const cfg = getEmulatorConfig(env);
  if (db) connectFirestoreEmulator(db, cfg.firestore.host, cfg.firestore.port);
  if (auth) connectAuthEmulator(auth, cfg.authUrl, { disableWarnings: true });
  if (functions) connectFunctionsEmulator(functions, cfg.functions.host, cfg.functions.port);
  if (storage) connectStorageEmulator(storage, cfg.storage.host, cfg.storage.port);
}

connectEmulatorsIfEnabled();

export { app, db, auth, functions, storage };

