# Tenancy Model (Firebase Auth + Firestore)

## Goals

- **Every user belongs to exactly one tenant** (org/workspace).
- **All tenant-owned data lives under** `tenants/{tenant_id}/...`.
- **Client access is tenant-scoped**: no reads/writes outside the caller’s tenant are possible.

## Firestore data model

### Core collections

```
tenants/{tenant_id}
tenants/{tenant_id}/users/{uid}
```

### Recommended tenant subcollections (examples)

All application data that is owned by a tenant should be stored under the tenant:

```
tenants/{tenant_id}/profiles/{uid}
tenants/{tenant_id}/broker_accounts/{broker_account_id}
tenants/{tenant_id}/strategies/{strategy_id}
tenants/{tenant_id}/paper_orders/{order_id}
tenants/{tenant_id}/risk_limits/{limit_id}
tenants/{tenant_id}/system/{doc_id}
tenants/{tenant_id}/system_logs/{log_id}
tenants/{tenant_id}/system_commands/{command_id}
...
```

### Membership document shape (example)

`tenants/{tenant_id}/users/{uid}`

```json
{
  "role": "member",
  "created_at": "<server timestamp>"
}
```

Notes:
- Client writes to membership docs are blocked in rules to prevent privilege escalation.
- Tenant creation / membership management should be done by trusted backend code (Admin SDK).

## Identity & tenant resolution

### Source of truth

- **Firebase Auth** is the identity source (`uid`).
- **Tenant id is carried via Firebase custom claims** on the ID token:
  - `tenant_id` (preferred)
  - `tenantId` (accepted as back-compat)

This enables both:
- Fast client-side access to `tenant_id` after login (via `getIdTokenResult()`).
- Rules-level enforcement that the user is operating inside their tenant.

### How the tenant claim is set

Setting custom claims must be done server-side (Admin SDK), for example:

```ts
// Pseudocode (Admin SDK)
await auth.setCustomUserClaims(uid, { tenant_id: "t_demo" });
```

You should also create the membership doc:

```
tenants/t_demo/users/{uid}
```

## Firestore security rules

Rules live in `firestore.rules` and enforce:
- Default deny for all non-tenant paths
- Allow read/write only under `tenants/{tenant_id}/...` when:
  - request is authenticated
  - `request.auth.token.tenant_id` matches `{tenant_id}`
  - membership doc exists at `tenants/{tenant_id}/users/{uid}`

## Backend access pattern (FastAPI)

Backend code verifies the Firebase ID token and extracts:
- `uid`
- `tenant_id` (from custom claims)

It then **always reads/writes tenant-owned data using tenant-scoped paths**, e.g.:

```
tenants/{tenant_id}/strategies/{strategy_id}
```

Even though Admin SDK bypasses rules, we still enforce tenancy in application code as
defense-in-depth and to avoid accidentally writing cross-tenant data.

## Frontend access pattern (React)

After login:
- `tenantId` is loaded from ID token custom claims and stored in auth context.
- All Firestore queries go through helpers that prefix paths with:
  - `tenants/{tenantId}/...`

## Sequence diagrams

### Login + tenant context hydration

```
User -> Firebase Auth: sign-in
Firebase Auth -> Client: ID token (includes tenant_id claim)
Client -> AuthContext: tenantId = getIdTokenResult().claims.tenant_id
Client -> Firestore: reads tenants/{tenantId}/... (rules enforce tenant isolation)
```

### Tenant-scoped read/write

```
Client -> Firestore: tenants/{tenantId}/strategies query
Firestore Rules: verify auth + tenant claim + membership doc exists
Firestore -> Client: results (only within tenant)
```

