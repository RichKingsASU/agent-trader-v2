/* eslint-disable no-console */

const functions = require("firebase-functions");
const admin = require("firebase-admin");
const Alpaca = require("@alpacahq/alpaca-trade-api");

// Initialize Firebase Admin once.
try {
  admin.initializeApp();
} catch (e) {
  // Ignore "already exists" in warm runtimes.
}

function asFloat(v) {
  if (v === null || v === undefined) return 0.0;
  if (typeof v === "number") return v;
  if (typeof v === "string") {
    const s = v.trim();
    if (!s) return 0.0;
    const n = Number.parseFloat(s);
    if (Number.isNaN(n)) {
      throw new Error(`Expected numeric string, got ${JSON.stringify(v)}`);
    }
    return n;
  }
  throw new Error(`Expected number-like value, got ${typeof v}`);
}

function utcNowIso() {
  return new Date().toISOString();
}

function getEnv(name, { required = false, defaultValue = undefined } = {}) {
  const v = process.env[name];
  if (v !== undefined && v !== null && String(v) !== "") return String(v);
  if (required) throw new Error(`Missing required env var: ${name}`);
  return defaultValue;
}

function resolveBaseUrl() {
  const raw = (getEnv("APCA_API_BASE_URL", { required: true }) || "").trim();
  return raw.endsWith("/") ? raw.slice(0, -1) : raw;
}

async function syncAlpacaAccountImpl({ tenantIdOverride } = {}) {
  const tenantId = (tenantIdOverride || getEnv("TENANT_ID", { required: false }) || "local").trim() || "local";

  const keyId = (getEnv("APCA_API_KEY_ID", { required: true }) || "").trim();
  const secretKey = (getEnv("APCA_API_SECRET_KEY", { required: true }) || "").trim();
  const baseUrl = resolveBaseUrl();
  const alpaca = new Alpaca({
    keyId,
    secretKey,
    baseUrl
  });

  // Equivalent to GET {trading_host}/v2/account.
  const acct = await alpaca.getAccount();

  const payload = {
    broker: "alpaca",
    external_account_id: acct?.id ?? null,
    status: acct?.status ?? null,
    equity: asFloat(acct?.equity),
    buying_power: asFloat(acct?.buying_power),
    cash: asFloat(acct?.cash),
    updated_at: admin.firestore.FieldValue.serverTimestamp(),
    updated_at_iso: utcNowIso(),
    // Keep raw payload for debugging; do not include secrets.
    raw: acct ?? {}
  };

  const db = admin.firestore();

  // tenants/{tenant_id}/accounts/primary
  await db
    .collection("tenants")
    .doc(tenantId)
    .collection("accounts")
    .doc("primary")
    .set(payload, { merge: true });

  // Warm-cache doc: alpacaAccounts/snapshot
  await db
    .collection("alpacaAccounts")
    .doc("snapshot")
    .set({ ...payload, tenant_id: tenantId }, { merge: true });

  return payload;
}

/**
 * HTTP-triggered function to sync the Alpaca account snapshot into Firestore.
 *
 * Auth / tenancy:
 * - Uses TENANT_ID from env by default (or "local").
 * - Optionally supports `?tenant_id=<id>` for manual runs.
 *
 * Required env vars:
 * - APCA_API_KEY_ID
 * - APCA_API_SECRET_KEY
 * - APCA_API_BASE_URL
 *
 * Optional env vars:
 * - TENANT_ID (default: local)
 */
exports.syncAlpacaAccount = functions.https.onRequest(async (req, res) => {
  try {
    const tenantIdOverride = String(req.query.tenant_id || "").trim() || undefined;
    const out = await syncAlpacaAccountImpl({ tenantIdOverride });
    res.status(200).json({ ok: true, data: out });
  } catch (e) {
    console.error("[syncAlpacaAccount] error:", e);
    res.status(500).json({ ok: false, error: e?.message || String(e) });
  }
});

