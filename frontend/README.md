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

