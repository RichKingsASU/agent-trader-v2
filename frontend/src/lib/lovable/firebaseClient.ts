import { initializeApp, type FirebaseApp } from "firebase/app";
import { getFirestore, type Firestore } from "firebase/firestore";

let cachedApp: FirebaseApp | null = null;
let cachedDb: Firestore | null = null;

function env(name: string): string | undefined {
  const v = (import.meta as any).env?.[name];
  return typeof v === "string" && v.trim() ? v : undefined;
}

export type FirebaseWebConfig = {
  apiKey: string;
  authDomain: string;
  projectId: string;
  appId: string;
  storageBucket?: string;
  messagingSenderId?: string;
};

export function getFirebaseConfig(): FirebaseWebConfig | null {
  const apiKey = env("VITE_FIREBASE_API_KEY");
  const authDomain = env("VITE_FIREBASE_AUTH_DOMAIN");
  const projectId = env("VITE_FIREBASE_PROJECT_ID");
  const appId = env("VITE_FIREBASE_APP_ID");

  if (!apiKey || !authDomain || !projectId || !appId) return null;

  return {
    apiKey,
    authDomain,
    projectId,
    appId,
    storageBucket: env("VITE_FIREBASE_STORAGE_BUCKET"),
    messagingSenderId: env("VITE_FIREBASE_MESSAGING_SENDER_ID"),
  };
}

export function getFirebaseApp(): FirebaseApp | null {
  const cfg = getFirebaseConfig();
  if (!cfg) return null;
  if (cachedApp) return cachedApp;
  cachedApp = initializeApp(cfg);
  return cachedApp;
}

export function getFirestoreDb(): Firestore | null {
  const app = getFirebaseApp();
  if (!app) return null;
  if (cachedDb) return cachedDb;
  cachedDb = getFirestore(app);
  return cachedDb;
}

