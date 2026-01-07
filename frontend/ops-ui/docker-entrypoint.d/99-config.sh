#!/bin/sh
set -eu

BASE_URL="${VITE_MISSION_CONTROL_BASE_URL:-${MISSION_CONTROL_BASE_URL:-}}"

if [ -n "${BASE_URL}" ]; then
  cat > /usr/share/nginx/html/config.js <<EOF
window.__OPS_UI_CONFIG__ = window.__OPS_UI_CONFIG__ || {};
window.__OPS_UI_CONFIG__.missionControlBaseUrl = "$(printf "%s" "${BASE_URL}" | sed 's/\"/\\\\\"/g')";
EOF
fi

