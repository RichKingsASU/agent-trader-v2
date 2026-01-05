## Repo guardrails (hard rules)

- **Banned vendor**: This repo must never contain any reference to the banned backend vendor or its ecosystem.
  - This includes code, docs, examples, env var names, dependencies, and migration/schema artifacts.
  - CI treats these strings as blockers (case-insensitive): `supa[b]ase`, `SUPA[B]ASE_`, `VITE_SUPA[B]ASE`, `@supa[b]ase`, `postg[re]st`, `go[tr]ue`.

- **No secrets committed**: Only templates like `.env.example` are allowed.
  - CI blocks common credential material, including private key blocks and GCP service account JSON markers.

- **Never track generated artifacts**:
  - `node_modules/` must never be tracked.
  - Build outputs like `dist/` and `build/` must never be tracked.
  - Logs (`*.log`, `firebase-debug.log`) must never be tracked.

## CI enforcement

- **Banned vendor scan**: CI scans all tracked files and fails if any banned vendor reference is found.
- **Secret scan**: CI scans all tracked files and fails if it detects:
  - A private key PEM block header (patterned like `-----BEGIN ... PRIVATE KEY-----`)
  - GCP service account JSON markers (keys like `"type": "service[_]account"`, `"client[_]email"`, `"private[_]key"`, `"private[_]key[_]id"`)

## Local preflight

Run:

```bash
./scripts/preflight.sh
```

This runs the same guardrail scans locally before compiling/building.

