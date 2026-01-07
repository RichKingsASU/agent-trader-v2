# Runbook — Cloud Build failure triage

## Safety posture

- Treat CI/CD failures as **production-impacting** if they block deploy/rollback.
- Prefer diagnosing via logs and build metadata; do not rerun builds until you understand the failure mode.

## Prereqs

```bash
export PROJECT_ID="<your-gcp-project-id>"
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
```

## Find the failing build

```bash
# Most recent builds
gcloud builds list --limit=20 --format="table(id,status,createTime,triggerId,logUrl)"

# Only failures
gcloud builds list --filter='status=FAILURE OR status=INTERNAL_ERROR OR status=TIMEOUT' --limit=20 --format="table(id,status,createTime,triggerId,logUrl)"
```

### What “good” looks like

```text
ID                                    STATUS   CREATE_TIME                TRIGGER_ID  LOG_URL
6f3b0f6c-1e2a-4b9c-b7c3-1e0a0a0a0a0a   SUCCESS  2026-01-07T14:02:31+00:00  1234567890  https://console.cloud.google.com/cloud-build/builds/...
```

## Inspect build details (fast)

```bash
export BUILD_ID="<build-id>"

# Key fields: status, timing, images, service account, substitutions, log URL
gcloud builds describe "$BUILD_ID" --format="yaml(status,createTime,finishTime,logUrl,serviceAccount,images,substitutions,source)"
```

### What “good” looks like

`status: SUCCESS` and a populated `logUrl`:

```yaml
status: SUCCESS
logUrl: https://console.cloud.google.com/cloud-build/builds/6f3b0f6c-...
images:
- us-docker.pkg.dev/<project>/<repo>/<image>:<tag>
```

## Pull logs and identify the failing step

```bash
# Full build logs
gcloud builds log "$BUILD_ID"
```

In the logs, find:
- The **first** failing command
- The step name (e.g., `Step #3 - "docker"`)
- The exact error (permission, not found, test failure, syntax error, etc.)

### What “good” looks like

```text
DONE
--------------------------------------------------------------------- [SUCCESS]
```

## If the build is trigger-based

```bash
export TRIGGER_ID="<trigger-id>"
gcloud builds triggers describe "$TRIGGER_ID" --format="yaml(id,name,filename,github,substitutions,disabled,serviceAccount)"
```

What “good” looks like: trigger is not disabled and references the expected `cloudbuild*.yaml`:

```yaml
disabled: false
filename: cloudbuild.yaml
```

## Common failures → exact checks

### 1) Permission denied pushing/pulling images (Artifact Registry)

Symptoms in logs:
- `denied: Permission "artifactregistry.repositories.uploadArtifacts" denied`
- `unauthorized: authentication required`

Checks:

```bash
# Build service account (from gcloud builds describe)
gcloud builds describe "$BUILD_ID" --format="value(serviceAccount)"

# Confirm Artifact Registry repo exists (adjust region/repo as needed)
export AR_LOCATION="<artifact-registry-location>"   # e.g. us-central1
gcloud artifacts repositories list --location="$AR_LOCATION" --format="table(name,format,createTime)"
```

What “good” looks like: repo listed and build service account has writer access (validate in IAM policy as per your org process).

### 2) Secret access failures (Secret Manager)

Symptoms in logs:
- `PermissionDenied: secretmanager.versions.access`
- `NOT_FOUND: Secret ... not found`

Checks:

```bash
export SECRET_NAME="<secret-name>"
gcloud secrets describe "$SECRET_NAME" --format="yaml(name,replication,createTime)"
gcloud secrets versions list "$SECRET_NAME" --limit=5 --format="table(name,state,createTime)"
```

What “good” looks like: at least one `ENABLED` version exists.

### 3) Substitution/variable mismatch (wrong tag/cluster/env)

Symptoms in logs:
- incorrect image tag deployed
- config references `${_SOME_VAR}` but it is empty

Checks:

```bash
# Show substitutions passed to the build
gcloud builds describe "$BUILD_ID" --format="yaml(substitutions)"

# If trigger-based, show trigger substitutions
gcloud builds triggers describe "$TRIGGER_ID" --format="yaml(substitutions,filename)"
```

What “good” looks like: required `_VARS` are present and non-empty in substitutions.

### 4) Docker build failures (Dockerfile / context / cache)

Symptoms in logs:
- `COPY failed: file not found in build context`
- `failed to solve: ...`

Checks (from your workstation/CI agent if needed):

```bash
# Re-run locally (only if you have the repo checked out and policy permits)
gcloud builds submit --config cloudbuild.yaml .
```

What “good” looks like: local submit reproduces the same failure (actionable) or succeeds (indicating env/IAM difference).

### 5) Tests/lint failing in build step

Symptoms in logs:
- `pytest`/`npm test`/`ruff` etc. exit non-zero

Checks:

```bash
# Use the failing command exactly as shown in Cloud Build logs, locally.
# Example patterns (replace with the real command from logs):
pytest -q
npm test
```

What “good” looks like: tests pass locally and in CI after fix; build returns `SUCCESS`.

## Done criteria

- You can point to the **failing step** and the **root cause class** (IAM / missing secret / bad substitution / Docker context / failing tests)
- The next action is unambiguous (fix permissions, restore secret, correct substitution, fix code, or roll back)

