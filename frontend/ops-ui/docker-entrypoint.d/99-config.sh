#!/bin/sh
set -eu

BASE_URL="${VITE_OPS_DASHBOARD_MISSION_CONTROL_BASE_URL:-${VITE_MISSION_CONTROL_BASE_URL:-${MISSION_CONTROL_BASE_URL:-}}}"
BASE_PATH="${VITE_OPS_DASHBOARD_BASE_PATH:-${OPS_DASHBOARD_BASE_PATH:-}}"

FIREBASE_API_KEY="${VITE_FIREBASE_API_KEY:-${FIREBASE_API_KEY:-}}"
FIREBASE_AUTH_DOMAIN="${VITE_FIREBASE_AUTH_DOMAIN:-${FIREBASE_AUTH_DOMAIN:-}}"
FIREBASE_PROJECT_ID="${VITE_FIREBASE_PROJECT_ID:-${FIREBASE_PROJECT_ID:-}}"
FIREBASE_STORAGE_BUCKET="${VITE_FIREBASE_STORAGE_BUCKET:-${FIREBASE_STORAGE_BUCKET:-}}"
FIREBASE_MESSAGING_SENDER_ID="${VITE_FIREBASE_MESSAGING_SENDER_ID:-${FIREBASE_MESSAGING_SENDER_ID:-}}"
FIREBASE_APP_ID="${VITE_FIREBASE_APP_ID:-${FIREBASE_APP_ID:-}}"

cat > /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__ = window.__OPS_DASHBOARD_CONFIG__ || {};
// Back-compat alias (safe to remove after migration).
window.__OPS_UI_CONFIG__ = window.__OPS_UI_CONFIG__ || {};
window.__OPS_DASHBOARD_CONFIG__.firebase = window.__OPS_DASHBOARD_CONFIG__.firebase || {};
EOF

if [ -n "${BASE_URL}" ]; then
  ESCAPED_BASE_URL="$(printf "%s" "${BASE_URL}" | sed 's/\"/\\\\\"/g')"
  cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.missionControlBaseUrl = "${ESCAPED_BASE_URL}";
window.__OPS_UI_CONFIG__.missionControlBaseUrl = "${ESCAPED_BASE_URL}";
EOF
fi

if [ -n "${BASE_PATH}" ]; then
  ESCAPED_BASE_PATH="$(printf "%s" "${BASE_PATH}" | sed 's/\"/\\\\\"/g')"
  cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.basePath = "${ESCAPED_BASE_PATH}";
EOF
fi

if [ -n "${FIREBASE_API_KEY}${FIREBASE_AUTH_DOMAIN}${FIREBASE_PROJECT_ID}${FIREBASE_APP_ID}" ]; then
  if [ -n "${FIREBASE_API_KEY}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_API_KEY}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.apiKey = "${ESCAPED}";
EOF
  fi
  if [ -n "${FIREBASE_AUTH_DOMAIN}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_AUTH_DOMAIN}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.authDomain = "${ESCAPED}";
EOF
  fi
  if [ -n "${FIREBASE_PROJECT_ID}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_PROJECT_ID}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.projectId = "${ESCAPED}";
EOF
  fi
  if [ -n "${FIREBASE_STORAGE_BUCKET}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_STORAGE_BUCKET}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.storageBucket = "${ESCAPED}";
EOF
  fi
  if [ -n "${FIREBASE_MESSAGING_SENDER_ID}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_MESSAGING_SENDER_ID}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.messagingSenderId = "${ESCAPED}";
EOF
  fi
  if [ -n "${FIREBASE_APP_ID}" ]; then
    ESCAPED="$(printf "%s" "${FIREBASE_APP_ID}" | sed 's/\"/\\\\\"/g')"
    cat >> /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__.firebase.appId = "${ESCAPED}";
EOF
  fi
fi

