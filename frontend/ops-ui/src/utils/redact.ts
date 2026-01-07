const SENSITIVE_KEY_RE = /(secret|token|api[_-]?key|password|private[_-]?key|authorization)/i;

export function redactDeep(value: unknown): unknown {
  if (value == null) return value;
  if (Array.isArray(value)) return value.map(redactDeep);
  if (typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      if (SENSITIVE_KEY_RE.test(k)) {
        out[k] = "[REDACTED]";
      } else {
        out[k] = redactDeep(v);
      }
    }
    return out;
  }
  return value;
}

