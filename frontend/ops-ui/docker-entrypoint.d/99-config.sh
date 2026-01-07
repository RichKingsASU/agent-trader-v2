#!/bin/sh
set -eu

BASE_URL="${VITE_OPS_DASHBOARD_MISSION_CONTROL_BASE_URL:-${VITE_MISSION_CONTROL_BASE_URL:-${MISSION_CONTROL_BASE_URL:-}}}"
BASE_PATH="${VITE_OPS_DASHBOARD_BASE_PATH:-${OPS_DASHBOARD_BASE_PATH:-}}"

cat > /usr/share/nginx/html/config.js <<EOF
window.__OPS_DASHBOARD_CONFIG__ = window.__OPS_DASHBOARD_CONFIG__ || {};
// Back-compat alias (safe to remove after migration).
window.__OPS_UI_CONFIG__ = window.__OPS_UI_CONFIG__ || {};
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

