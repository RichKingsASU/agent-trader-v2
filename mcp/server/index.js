/**
 * Minimal stdio MCP server for calling Vertex AI Gemini generateContent.
 *
 * Key behaviors requested:
 * - Use gemini-2.5-flash on the global endpoint by default
 * - Use the stable Vertex AI v1 generateContent path (discovery_url)
 * - Validate GOOGLE_APPLICATION_CREDENTIALS (absolute path, readable JSON key)
 * - Catch 404s and log a helpful message instead of crashing
 */
/* eslint-disable no-console */

let __didLogRuntimeFingerprint = false;
function logRuntimeFingerprintOnce() {
  if (__didLogRuntimeFingerprint) return;
  __didLogRuntimeFingerprint = true;

  const service = String(process.env.SERVICE_NAME || "vertex-mcp-server");
  const agentMode = String(process.env.AGENT_MODE || "unknown");
  const gitSha = String(process.env.GIT_SHA || "unknown");
  const imageTag = String(process.env.IMAGE_TAG || "unknown");

  console.log(
    [
      "RUNTIME_FINGERPRINT:",
      `  service=${service}`,
      `  agent_mode=${agentMode}`,
      "  execution_enabled=false",
      `  git_sha=${gitSha}`,
      `  image_tag=${imageTag}`
    ].join("\n")
  );
}
logRuntimeFingerprintOnce();

const crypto = require("node:crypto");
const fs = require("node:fs");
const { URLSearchParams } = require("node:url");

function truthy(v) {
  if (v === undefined || v === null) return false;
  const s = String(v).trim().toLowerCase();
  return s === "1" || s === "true" || s === "yes" || s === "on";
}

function getKillSwitchState() {
  // Standardized env var
  if (truthy(process.env.EXECUTION_HALTED)) {
    return { enabled: true, source: "env:EXECUTION_HALTED" };
  }
  // Back-compat (deprecated)
  if (truthy(process.env.EXEC_KILL_SWITCH)) {
    return { enabled: true, source: "env:EXEC_KILL_SWITCH" };
  }

  const filePath =
    (process.env.EXECUTION_HALTED_FILE || process.env.EXEC_KILL_SWITCH_FILE || "").trim();
  if (filePath) {
    try {
      if (fs.existsSync(filePath)) {
        const raw = fs.readFileSync(filePath, "utf8");
        const firstLine = (raw.split(/\r?\n/)[0] || "").trim();
        if (truthy(firstLine)) {
          return { enabled: true, source: `file:${filePath}` };
        }
      }
    } catch {
      // If unreadable, fail-open for this non-execution service.
    }
  }

  return { enabled: false, source: null };
}

function nowSeconds() {
  return Math.floor(Date.now() / 1000);
}

function base64UrlEncode(input) {
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(String(input));
  return buf
    .toString("base64")
    .replace(/=/g, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
}

function readServiceAccountKeyOrThrow() {
  const p = process.env.GOOGLE_APPLICATION_CREDENTIALS;
  if (!p) {
    throw new Error(
      "GOOGLE_APPLICATION_CREDENTIALS is not set. Set it to an absolute path to your refreshed service account key JSON."
    );
  }
  if (!p.startsWith("/")) {
    throw new Error(`GOOGLE_APPLICATION_CREDENTIALS must be an absolute path: ${p}`);
  }
  if (!fs.existsSync(p)) {
    throw new Error(`GOOGLE_APPLICATION_CREDENTIALS file not found: ${p}`);
  }
  const raw = fs.readFileSync(p, "utf8");
  let key;
  try {
    key = JSON.parse(raw);
  } catch (e) {
    throw new Error(`GOOGLE_APPLICATION_CREDENTIALS is not valid JSON: ${p} (${e?.message || e})`);
  }
  if (!key?.client_email || !key?.private_key) {
    throw new Error(
      `GOOGLE_APPLICATION_CREDENTIALS does not look like a service account key (missing client_email/private_key): ${p}`
    );
  }
  return key;
}

async function getAccessTokenFromServiceAccount() {
  const key = readServiceAccountKeyOrThrow();
  const tokenUri = key.token_uri || "https://oauth2.googleapis.com/token";

  const header = { alg: "RS256", typ: "JWT" };
  const iat = nowSeconds();
  const exp = iat + 3600;
  const claimSet = {
    iss: key.client_email,
    scope: "https://www.googleapis.com/auth/cloud-platform",
    aud: tokenUri,
    iat,
    exp
  };

  const unsignedJwt = `${base64UrlEncode(JSON.stringify(header))}.${base64UrlEncode(
    JSON.stringify(claimSet)
  )}`;
  const signer = crypto.createSign("RSA-SHA256");
  signer.update(unsignedJwt);
  signer.end();
  const signature = signer.sign(key.private_key);
  const assertion = `${unsignedJwt}.${base64UrlEncode(signature)}`;

  const body = new URLSearchParams({
    grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    assertion
  });

  const res = await fetch(tokenUri, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body
  });
  const text = await res.text();
  if (!res.ok) {
    throw new Error(`Failed to mint access token (${res.status}): ${text}`);
  }
  const json = JSON.parse(text);
  if (!json.access_token) {
    throw new Error(`Token response missing access_token: ${text}`);
  }
  return json.access_token;
}

function resolveDiscoveryUrl() {
  const projectId = process.env.PROJECT_ID || process.env.GOOGLE_CLOUD_PROJECT || "${PROJECT_ID}";
  const discoveryUrl =
    process.env.discovery_url ||
    `https://aiplatform.googleapis.com/v1/projects/${projectId}/locations/global/publishers/google/models/gemini-2.5-flash:generateContent`;

  // If the user kept the template value, interpolate it.
  return discoveryUrl.replace(/\$\{PROJECT_ID\}/g, projectId);
}

function logHelpful404(url, bodyText) {
  console.error("[mcp][vertex] 404 Not Found calling Vertex AI.");
  console.error(`[mcp][vertex] discovery_url: ${url}`);
  console.error(
    "[mcp][vertex] Expected format:\n" +
      "https://aiplatform.googleapis.com/v1/projects/${PROJECT_ID}/locations/global/publishers/google/models/gemini-2.5-flash:generateContent"
  );
  if (bodyText) {
    console.error("[mcp][vertex] response body:", bodyText.slice(0, 2000));
  }
}

async function callVertexGenerateContent({ prompt }) {
  const url = resolveDiscoveryUrl();
  const accessToken = await getAccessTokenFromServiceAccount();

  const res = await fetch(url, {
    method: "POST",
    headers: {
      authorization: `Bearer ${accessToken}`,
      "content-type": "application/json"
    },
    body: JSON.stringify({
      contents: [{ role: "user", parts: [{ text: String(prompt ?? "") }] }]
    })
  });

  const text = await res.text().catch(() => "");
  if (res.status === 404) {
    // Requested behavior: do NOT crash. Log a helpful message and return an MCP error result.
    logHelpful404(url, text);
    return { ok: false, error: `Vertex AI endpoint returned 404. Check discovery_url and PROJECT_ID.` };
  }
  if (!res.ok) {
    return { ok: false, error: `Vertex AI request failed (${res.status}): ${text}` };
  }

  try {
    return { ok: true, data: JSON.parse(text) };
  } catch {
    return { ok: true, data: text };
  }
}

function writeJson(obj) {
  process.stdout.write(`${JSON.stringify(obj)}\n`);
}

function mcpResultText(text) {
  return { content: [{ type: "text", text: String(text) }], isError: false };
}

function mcpResultError(text) {
  return { content: [{ type: "text", text: String(text) }], isError: true };
}

const tools = [
  {
    name: "vertex_generateContent",
    description: "Call Vertex AI Gemini generateContent (global, gemini-2.5-flash).",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      properties: {
        prompt: { type: "string", description: "User prompt text." }
      },
      required: ["prompt"]
    }
  }
];

async function handleRpc(msg) {
  if (!msg || msg.jsonrpc !== "2.0" || !msg.method) {
    return null;
  }

  // Notifications have no id; ignore.
  if (msg.id === undefined || msg.id === null) {
    return null;
  }

  try {
    if (msg.method === "initialize") {
      return {
        jsonrpc: "2.0",
        id: msg.id,
        result: {
          protocolVersion: "2024-11-05",
          serverInfo: { name: "vertex-gemini-global", version: "0.1.0" },
          capabilities: {}
        }
      };
    }

    if (msg.method === "tools/list") {
      return { jsonrpc: "2.0", id: msg.id, result: { tools } };
    }

    if (msg.method === "tools/call") {
      const params = msg.params || {};
      const toolName = params.name;
      const args = params.arguments || {};

      if (toolName !== "vertex_generateContent") {
        return {
          jsonrpc: "2.0",
          id: msg.id,
          result: mcpResultError(`Unknown tool: ${toolName}`)
        };
      }

      const out = await callVertexGenerateContent({ prompt: args.prompt });
      if (!out.ok) {
        return { jsonrpc: "2.0", id: msg.id, result: mcpResultError(out.error) };
      }
      return { jsonrpc: "2.0", id: msg.id, result: mcpResultText(JSON.stringify(out.data, null, 2)) };
    }

    return {
      jsonrpc: "2.0",
      id: msg.id,
      error: { code: -32601, message: `Method not found: ${msg.method}` }
    };
  } catch (e) {
    // Safety net: never crash the server on unexpected errors.
    console.error("[mcp] Unhandled error while processing request:", e);
    return {
      jsonrpc: "2.0",
      id: msg.id,
      result: mcpResultError(e?.message || String(e))
    };
  }
}

function start() {
  // Extra safety: prevent process termination on unhandled promise rejections.
  process.on("unhandledRejection", (e) => {
    console.error("[mcp] Unhandled promise rejection (kept alive):", e);
  });
  process.on("uncaughtException", (e) => {
    console.error("[mcp] Uncaught exception (kept alive):", e);
  });

  const ks = getKillSwitchState();
  if (ks.enabled) {
    // Non-execution agent: keep serving but make it visible.
    console.error(`[mcp] kill_switch_active enabled=true source=${ks.source}`);
  }

  let buffer = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", async (chunk) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      let msg;
      try {
        msg = JSON.parse(trimmed);
      } catch (e) {
        console.error("[mcp] Failed to parse JSON-RPC message:", e, "line:", trimmed);
        continue;
      }
      const resp = await handleRpc(msg);
      if (resp) writeJson(resp);
    }
  });
}

start();

