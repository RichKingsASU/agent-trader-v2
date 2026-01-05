# UI Setup (Firebase)

To run the AgentTrader dashboard (Vite + React) against Firebase, set the following environment variables for your frontend deployment:

- `VITE_FIREBASE_API_KEY`
- `VITE_FIREBASE_AUTH_DOMAIN`
- `VITE_FIREBASE_PROJECT_ID`
- `VITE_FIREBASE_APP_ID`
- (optional) `VITE_FIREBASE_STORAGE_BUCKET`
- (optional) `VITE_FIREBASE_MESSAGING_SENDER_ID`

These variables are used by the Firebase web client initializer. Without these, the dashboard will still render, but will show offline/placeholder states.

Once configured, the dashboard will display:
- A "System Health" banner indicating the status of the ingestion loop and Alpaca paper trading authentication.
- A live ticker driven by your streamer endpoint (`VITE_STREAMER_URL`).

