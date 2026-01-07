function parseCsv(value: string | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

export type OperatorAccessPolicy = {
  enabled: boolean;
  emails: string[];
  domains: string[];
};

export function getOperatorAccessPolicy(): OperatorAccessPolicy {
  const emails = parseCsv(import.meta.env.VITE_OPERATOR_EMAILS as string | undefined);
  const domains = parseCsv(import.meta.env.VITE_OPERATOR_DOMAINS as string | undefined).map((d) =>
    d.startsWith("@") ? d.slice(1) : d,
  );
  const enabled = emails.length > 0 || domains.length > 0;
  return { enabled, emails, domains };
}

export function isOperatorEmail(email: string | null | undefined): boolean {
  const e = (email ?? "").trim().toLowerCase();
  if (!e) return false;

  const { enabled, emails, domains } = getOperatorAccessPolicy();
  if (!enabled) return true; // no policy configured => allow all (useful for local dev)

  if (emails.includes(e)) return true;

  const at = e.lastIndexOf("@");
  if (at === -1) return false;
  const domain = e.slice(at + 1);
  if (!domain) return false;

  return domains.includes(domain);
}

export function allowSignup(): boolean {
  const raw = (import.meta.env.VITE_AUTH_ALLOW_SIGNUP as string | undefined) ?? "false";
  return raw.trim().toLowerCase() === "true";
}

