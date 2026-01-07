# Firebase Hosting + Auth (dev/staging/prod)

This repo is set up to deploy the React dashboard to **Firebase Hosting** with **Firebase Auth** (email/password) and an **operator-only allowlist**.

## What was added

- **Hosting config**: `firebase.json` (SPA rewrite to `index.html`, serves `frontend/dist`)
- **Env separation**: `.firebaserc` with `dev` / `staging` / `prod` project aliases
- **Auth guard**: operator-only route protection via `frontend/src/components/auth/RequireOperator.tsx`
- **Operator allowlist**: `VITE_OPERATOR_EMAILS` / `VITE_OPERATOR_DOMAINS` (see `frontend/.env.example`)

## 1) Create Firebase projects (dev / staging / prod)

In the Firebase console, create 3 projects (recommended):

- `agenttrader-dev`
- `agenttrader-staging`
- `agenttrader-prod`

If you use different project IDs, update `.firebaserc` accordingly.

## 2) Enable Firebase Auth providers

For each project:

1. Firebase Console → **Authentication** → **Get started**
2. **Sign-in method**
3. Enable:
   - **Email/Password**
   - (Optional) **Google** (the UI includes it; access is still allowlisted)

## 3) Create operator accounts

Because the dashboard is **operator-only**, you should provision operator users explicitly:

- Firebase Console → **Authentication** → **Users** → **Add user**
- Add users for each environment as needed

The frontend can optionally show a “Sign Up” tab, but it is **disabled by default**.

## 4) Configure frontend environment variables

The frontend is a Vite app. It reads Firebase web config at **build time**.

Copy and fill one of these patterns:

- Local dev: `frontend/.env.local`
- Staging build: `frontend/.env.staging`
- Prod build: `frontend/.env.production`

Start from `frontend/.env.example` and set:

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_APP_ID`
- (Optional) `VITE_FIREBASE_STORAGE_BUCKET`
- (Optional) `VITE_FIREBASE_MESSAGING_SENDER_ID`

Operator-only allowlist:

- `VITE_OPERATOR_EMAILS=alice@company.com,bob@company.com`
- `VITE_OPERATOR_DOMAINS=company.com`

Signup UI toggle (recommended `false`):

- `VITE_AUTH_ALLOW_SIGNUP=false`

## 5) Install and build the frontend

From repo root:

```bash
npm --prefix frontend install
```

Build per environment:

```bash
# staging
npm --prefix frontend run build:staging

# prod (default Vite production mode)
npm --prefix frontend run build
```

## 6) Deploy to Firebase Hosting

Install Firebase CLI (once) if you don’t already have it:

```bash
npm i -g firebase-tools
firebase login
```

Select the target environment and deploy hosting:

```bash
firebase use staging
firebase deploy --only hosting
```

For production:

```bash
firebase use prod
firebase deploy --only hosting
```

## Notes / constraints

- This setup **does not deploy Firestore rules** and **does not deploy Cloud Functions** (per constraints).
- Hosting uses an SPA rewrite, so deep links like `/ops/options` work.

