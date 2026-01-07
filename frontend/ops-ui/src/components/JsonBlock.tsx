import { redactDeep } from "@/utils/redact";

export function JsonBlock({ value }: { value: unknown }) {
  const redacted = redactDeep(value);
  const text = JSON.stringify(redacted, null, 2);
  return <pre className="json mono">{text}</pre>;
}

