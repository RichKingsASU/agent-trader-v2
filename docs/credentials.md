## Credentials (Firestore / Firebase Admin)

This repo intentionally **does not** include `service-account-key.json` (it is ignored by `.gitignore`).

### Recommended: Application Default Credentials (ADC)

For local development, prefer Google ADC:

```bash
gcloud auth application-default login
```

This avoids managing JSON key files and works with `firebase-admin` / `google-cloud-firestore`.

### Alternative: Service account JSON key (local-only)

1) Download a service account key JSON from GCP (do **not** commit it).
2) Store it somewhere outside the repo, for example:

```bash
mkdir -p "$HOME/secrets"
mv "/path/to/downloaded-key.json" "$HOME/secrets/service-account-key.json"
```

3) Export `GOOGLE_APPLICATION_CREDENTIALS`:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/secrets/service-account-key.json"
test -f "$GOOGLE_APPLICATION_CREDENTIALS" && echo "OK" || echo "MISSING"
```

To make this persistent across shells:

```bash
echo 'export GOOGLE_APPLICATION_CREDENTIALS="$HOME/secrets/service-account-key.json"' >> ~/.bashrc
```

### Production

On Cloud Functions / Cloud Run, prefer **Workload Identity / default service accounts** instead of JSON keys.

