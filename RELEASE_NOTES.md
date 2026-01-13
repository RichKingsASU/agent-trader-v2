# Release Notes — `v0.9.0-paper-lock`

**Release tag**: `v0.9.0-paper-lock`  
**Release commit**: `148e21146f33dba744c2a9c8a7cd475456783461`  
**Release date (UTC)**: 2026-01-13  
**Previous tag**: `poisoned-pre-cleanup`  
**Commit range**: `poisoned-pre-cleanup..v0.9.0-paper-lock`

## Summary

This release focuses on **production hardening** and **non-negotiable paper-trading safeguards**. The key theme is “fail closed”: misconfiguration and unsafe execution paths now hard-fail early and loudly.

## Highlights

- **Paper-only Alpaca safety boundary**
  - Runtime validation explicitly **refuses live Alpaca trading hosts** and requires `https://paper-api.alpaca.markets` as the base host (with optional path).
  - Alpaca env usage is standardized around **official `APCA_*` variables**, with documented/normalized legacy aliases where applicable.

- **Execution engine: stronger “should never happen” invariant checks**
  - Internal risk/capital metadata invariants are enforced and raise an `InvariantViolation` (logged at `CRITICAL`) rather than being silently corrected.
  - Execution-capable code paths are guarded so that paper trading is the only allowed exception where explicitly configured.

- **Firebase Admin init is ADC-safe and emulator-safe**
  - Firebase Admin initialization is now explicit about:
    - **Emulator mode**: uses anonymous credentials and does not require ADC.
    - **Non-emulator mode**: requires ADC and fails fast with actionable error messages when unavailable.

- **Ops UI dev/build hardening**
  - Ops UI local-dev connectivity is standardized around a same-origin proxy (`/mission-control`), avoiding browser CORS requirements.
  - Firebase Hosting deploy workflow builds `frontend/ops-ui` deterministically (`npm ci`, workspace build).

## Behavior / contract changes (fail-closed)

- **Alpaca base URL must be paper**
  - The code now hard-fails if `APCA_API_BASE_URL` points to the live host (`api.alpaca.markets`) or uses an unsafe URL shape (non-https, wrong host, port specified, credentials, query/fragment).
  - Local “smoke test” order placement is refused by default unless explicitly enabled *and* paper mode is configured.

- **Firebase project id resolution is stricter**
  - Outside emulator mode, Firebase Admin init will fail fast if ADC is missing or a project id cannot be resolved (prefer `FIREBASE_PROJECT_ID`, with back-compat fallbacks).

## Documentation

- Added: `docs/CANONICAL_ENV_VAR_CONTRACT.md` (authoritative env var contract and gap analysis)
- Added: `docs/ops/local_dev_connectivity_standard.md` (canonical Ops UI ↔ Mission Control local-dev contract)
- Updated: `docs/ops/ops_ui.md`

## CI / deployment

- Updated: `.github/workflows/firebase_ops_dashboard_deploy.yml` to build and deploy Ops UI deterministically from `frontend/ops-ui`.
- Repo hygiene updates (e.g., `.gitignore`) to avoid tracking generated artifacts.

## Full commit list (range: `poisoned-pre-cleanup..v0.9.0-paper-lock`)

- `feat(release): production readiness & paper-trading safeguards`
- `Merge remote-tracking branch 'origin/cursor/local-dev-connectivity-contract-8fd6'`
- `Merge branch 'origin/cursor/canonical-env-var-contract-cb66' into main`
- `Merge remote-tracking branch 'origin/cursor/alpaca-paper-only'`
- `Merge remote-tracking branch 'origin/cursor/firebase-admin-usage-audit-deb0'`
- `Merge remote-tracking branch 'origin/cursor/repo-hygiene'`
- `Enforce paper-only Alpaca trading base URL`
- `chore(repo): ignore genkit/venvs/dist and log artifacts`
- `chore(repo): stop tracking venv/genkit/dist/log artifacts`
- `docs(config): add missing runtime env vars to contract`
- `docs(config): publish canonical env var contract`
- `chore(ops-ui): fix Vite build PostCSS dependencies`
- `docs(ops): standardize local Ops UI ↔ Mission Control connectivity`
- `Make Firebase init emulator/ADC safe`
- `Stabilize frontend ops-ui structure and dev scripts`

