# Config + Secrets Discipline

This repo follows a **single config system** implemented in `backend/common/config.py`.

## Principles

- **Fail-fast**: services validate required env vars at startup and exit with a single-line `CONFIG_FAIL ...` error if misconfigured.
- **Safe defaults**: non-sensitive, operational knobs may have defaults; **secrets never do**.
- **No secret values in logs**: validation checks presence only; do not print secret contents.
- **Prefer Secret Manager**: do not commit secret files and do not bake secrets into container images.

## How validation works

- **Central registry**: `backend/common/config.py` defines required/optional env var sets per service (e.g. `cloudrun-ingestor`, `cloudrun-consumer`, `strategy-engine`, `stream-bridge`).
- **Startup enforcement**: entrypoints call `validate_or_exit("<service>")` early. If required vars are missing, the process exits immediately.

Example error shape (single line):

`CONFIG_FAIL service=cloudrun-ingestor missing=GCP_PROJECT,SYSTEM_EVENTS_TOPIC action="Set missing env vars (Cloud Run: --set-env-vars/--set-secrets). See docs/DEPLOY_GCP.md#secrets-recommended-secret-manager and docs/CONFIG_SECRETS.md"`

## Secret Manager usage (Cloud Run)

Recommended pattern:

- Put sensitive values (API keys, tokens) in **Secret Manager**
- Map secrets into env vars at deploy time using Cloud Run `--set-secrets`
- Grant your runtime service account: `roles/secretmanager.secretAccessor`

See the deploy doc for concrete commands and the `SECRETS='ENV_VAR=secret-name:version,...'` pattern:

- `docs/DEPLOY_GCP.md` (section “Secrets (recommended: Secret Manager)”)

## Rotation expectations

Important operational behavior:

- **Cloud Run resolves Secret Manager values at container startup.**
- If you create a new secret version (rotation), **existing running revisions will not automatically pick it up**.

Recommended rotation workflow:

- **Create a new secret version** (do not overwrite old versions).
- **Redeploy** the Cloud Run service/job (or roll a new revision) so new instances start with the new secret value.
- Keep at least one prior version available until the new revision is confirmed healthy, then disable/destroy older versions per your retention policy.

Notes:

- Using `:latest` in `--set-secrets` is convenient, but still requires a **redeploy** to take effect.
- For tighter control, pin a specific version (`:5`) and update the pinned version during rotation (still redeploy).

