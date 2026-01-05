import { collection, doc, type Firestore } from "firebase/firestore";

export function tenantCollection(db: Firestore, tenantId: string, ...segments: string[]) {
  return collection(db, "tenants", tenantId, ...segments);
}

export function tenantDoc(db: Firestore, tenantId: string, ...segments: string[]) {
  return doc(db, "tenants", tenantId, ...segments);
}

