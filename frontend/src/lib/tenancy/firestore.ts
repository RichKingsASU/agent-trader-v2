import { collection, doc, type Firestore } from "firebase/firestore";

export function tenantCollection(db: Firestore, tenantId: string, ...segments: string[]) {
  return collection(db, "tenants", tenantId, ...segments);
}

export function tenantDoc(db: Firestore, tenantId: string, ...segments: string[]) {
  return doc(db, "tenants", tenantId, ...segments);
}

// Legacy/global path helpers.
// These centralize Firestore path construction so UI components do not call
// `collection(db, ...)` / `doc(db, ...)` directly (guardrail enforced in tests).
export function systemDoc(db: Firestore, ...segments: string[]) {
  return doc(db, "systemStatus", ...segments);
}

export function marketDataCollection(db: Firestore, ...segments: string[]) {
  return collection(db, "marketData", ...segments);
}

export function shadowTradeHistoryCollection(db: Firestore) {
  return collection(db, "shadowTradeHistory");
}

export function userDoc(db: Firestore, uid: string, ...segments: string[]) {
  return doc(db, "users", uid, ...segments);
}

export function userCollection(db: Firestore, uid: string, ...segments: string[]) {
  return collection(db, "users", uid, ...segments);
}

export function userSettingsDoc(db: Firestore, uid: string, ...segments: string[]) {
  return doc(db, "userSettings", uid, ...segments);
}

export function userSettingsCollection(db: Firestore, uid: string, ...segments: string[]) {
  return collection(db, "userSettings", uid, ...segments);
}

