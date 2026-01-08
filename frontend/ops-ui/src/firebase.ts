import { initializeApp, type FirebaseApp, getApps } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";
import { getFirestore, type Firestore } from "firebase/firestore";

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
const env = (import.meta as unknown as { env?: Record<string, string> }).env || {};

const firebaseConfig = {
  apiKey: runtime.apiKey || env.VITE_FIREBASE_API_KEY,
  authDomain: runtime.authDomain || env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: runtime.projectId || env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: runtime.storageBucket || env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: runtime.messagingSenderId || env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: runtime.appId || env.VITE_FIREBASE_APP_ID,
};

export const isFirebaseConfigured = Boolean(
  firebaseConfig.apiKey && firebaseConfig.authDomain && firebaseConfig.projectId && firebaseConfig.appId,
);

let app: FirebaseApp | null = null;
let db: Firestore | null = null;
let auth: Auth | null = null;

if (isFirebaseConfigured) {
  app = getApps().length ? getApps()[0]! : initializeApp(firebaseConfig);
  db = getFirestore(app);
  auth = getAuth(app);
}

export { app, db, auth };

