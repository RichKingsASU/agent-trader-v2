# Firebase Hosting — Ops Dashboard (Ops UI)

This repo includes an Ops Dashboard UI in `frontend/ops-ui/` (Vite SPA). Firebase Hosting is configured to serve the built static site from `frontend/ops-ui/dist` (see `firebase.json`).

## One-time Firebase setup

1) Install the Firebase CLI:

```bash
npm i -g firebase-tools
firebase --version
```

2) Authenticate and select the Firebase project:

```bash
firebase login
firebase use agenttrader-prod
```

Notes:
- The default project is already set in `.firebaserc` (`agenttrader-prod`).
- If you want to deploy to a different Firebase project, run `firebase use --add` and update `.firebaserc` locally.

3) Enable Firebase Hosting for the project (Firebase Console) and (optionally) create a dedicated Hosting site.

If you use multiple Hosting sites in one Firebase project, add a `site` or `target` to `firebase.json`:
- `site`: hard-code a site ID, or
- `target`: map a friendly name to a site ID via `firebase target:apply hosting ...` (stored in `.firebaserc`)

## Build + deploy (local)

Firebase Hosting deploys whatever is in the configured `public` directory (`frontend/ops-ui/dist`). Ensure you build the Ops UI before deploying:

```bash
# Example (if your repo includes the Node workspace config):
#   cd frontend
#   npm ci
#   npm -w ops-ui run build
#
# Then, from repo root:
firebase deploy --only hosting
```

If you want to verify locally before deploying:

```bash
firebase emulators:start --only hosting
```

## Runtime configuration (`/config.js`)

Ops UI reads optional runtime config from `/config.js` (see `frontend/ops-ui/public/config.js`). On Firebase Hosting this file is **static**; update it before deploy if you need to set `missionControlBaseUrl`.

`firebase.json` also sets `Cache-Control: no-store` for `/config.js` so config changes take effect immediately for users.

## Optional: GitHub Actions deploy

If you enable the workflow in `.github/workflows/firebase_ops_dashboard_deploy.yml`, it deploys **only when manually triggered** and is **locked down** so production deploys cannot happen without:
- running from the `main` branch, and
- explicit GitHub Environment approval (see checklist below).

Required GitHub secret (repo settings → Secrets and variables → Actions):
- `FIREBASE_SERVICE_ACCOUNT_AGENTTRADER_PROD`: a Firebase service account JSON with permission to deploy Hosting for `agenttrader-prod`

### Required GitHub settings checklist (after merge)

These are repo settings you must apply in GitHub (they are not fully enforceable via git alone):

1) **Create GitHub Environment**: `production`
   - **Required reviewers**: add the approver group/users who must approve every prod deploy
   - **Deployment branches**: restrict to **selected branches** → `main` only

2) **Protect `main` branch** (Settings → Branches)
   - Require pull request reviews before merging (so workflow changes can’t be merged unreviewed)
   - Disallow direct pushes to `main` (recommended)

