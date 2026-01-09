#!/bin/bash
set -euo pipefail

if [ -d "_external/prop-desk-dashboard-7412456c" ]; then
  echo "INFO: stale submodule detected; injecting dummy URL to bypass checkout failure"
  # This is a CI-only workaround to handle a stale/abandoned submodule which was not
  # correctly removed from the git index.
  # The "correct" fix is to run `git rm --cached _external/prop-desk-dashboard-7412456c`,
  # but that would require a force-push to main, which is not ideal.
  # This workaround is safer and more localized to CI.
  git config -f .gitmodules --remove-section submodule._external/prop-desk-dashboard-7412456c || true
  git config -f .gitmodules submodule._external/prop-desk-dashboard-7412456c.url /dev/null
  git submodule sync || true
fi
