# Frontend (Vite + React)

This folder contains the Vite + React frontend for the prop desk dashboard.

## Current Status: Pre-Firebase Stabilization

- The frontend is being stabilized and sanitized prior to any Firebase migration work.
- **Firebase is optional**: the UI runs in **local mode by default** (no external SaaS required).

## Local development

### Prereqs

- Node.js (>= 20) + npm

### Run

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

### Build

```bash
cd frontend
npm run build
```

## Environment variables

See `.env.example`. By default, Firebase env vars are empty and the app runs without Firebase.

### Firebase emulator safety (dev)

When running the Vite dev server, Firebase clients (Firestore/Auth/Functions/Storage) will **connect to local emulators by default**.
To intentionally disable emulators and allow the dev server to talk to real Firebase, set:

```bash
VITE_USE_FIREBASE_EMULATORS=false
```

You can also override emulator host/ports via `VITE_FIREBASE_EMULATOR_HOSTS` (see `.env.example`).

