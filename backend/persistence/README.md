## Firebase persistence (Firestore) — production notes

This backend uses the **Firebase Admin SDK** with **Application Default Credentials (ADC) only**.

### Required environment variable names

- `FIREBASE_PROJECT_ID`

### Local development (ADC)

Authenticate ADC locally:

```bash
gcloud auth application-default login
```

### Production (Cloud Run / GCE)

Run with a service account that has Firestore permissions (ADC is provided by the platform).

