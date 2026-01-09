#!/usr/bin/env bash
set -euo pipefail

# Cloud Run audit helper (services + jobs).
#
# Usage:
#   ./scripts/audit_cloudrun.sh
#   PROJECT_ID="my-gcp-project" ./scripts/audit_cloudrun.sh
#   ./scripts/audit_cloudrun.sh "us-central1 us-east1"
#
# Output is intended to be human-readable and easy to paste into an incident report.
#
# Requirements:
# - gcloud installed and authenticated (or running in Cloud Shell / CI with ADC)
# - permissions: run.services.list + run.services.get (and run.jobs.* if you want jobs)

REGIONS="${1:-us-central1 us-east1}"
PROJECT_ID="${PROJECT_ID:-${GCP_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "ERROR: gcloud is not installed or not on PATH." >&2
  exit 2
fi

GCLOUD_PROJECT_ARGS=()
if [[ -n "${PROJECT_ID}" ]]; then
  GCLOUD_PROJECT_ARGS=(--project "${PROJECT_ID}")
fi

echo "Cloud Run audit"
echo "Project: ${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null || echo '(gcloud default not set)')}"
echo "Regions: ${REGIONS}"
echo

for region in ${REGIONS}; do
  echo "== Cloud Run services (${region}) =="
  services="$(
    gcloud run services list \
      --platform managed \
      --region "${region}" \
      "${GCLOUD_PROJECT_ARGS[@]}" \
      --format="value(metadata.name)" 2>/dev/null || true
  )"

  if [[ -z "${services}" ]]; then
    echo "(none)"
  else
    printf "%-44s  %-44s  %s\n" "SERVICE" "LATEST_READY_REVISION" "IMAGE"
    printf "%-44s  %-44s  %s\n" "------" "-------------------" "-----"
    while IFS= read -r svc; do
      [[ -z "${svc}" ]] && continue
      rev="$(
        gcloud run services describe "${svc}" \
          --platform managed \
          --region "${region}" \
          "${GCLOUD_PROJECT_ARGS[@]}" \
          --format="value(status.latestReadyRevisionName)" 2>/dev/null || echo "-"
      )"
      img="$(
        gcloud run services describe "${svc}" \
          --platform managed \
          --region "${region}" \
          "${GCLOUD_PROJECT_ARGS[@]}" \
          --format="value(spec.template.spec.containers[0].image)" 2>/dev/null || echo "-"
      )"
      printf "%-44s  %-44s  %s\n" "${svc}" "${rev:-"-"}" "${img:-"-"}"
    done <<<"${services}"
  fi
  echo

  echo "== Cloud Run jobs (${region}) =="
  jobs="$(
    gcloud run jobs list \
      --region "${region}" \
      "${GCLOUD_PROJECT_ARGS[@]}" \
      --format="value(metadata.name)" 2>/dev/null || true
  )"

  if [[ -z "${jobs}" ]]; then
    echo "(none)"
  else
    printf "%-44s  %s\n" "JOB" "IMAGE"
    printf "%-44s  %s\n" "---" "-----"
    while IFS= read -r job; do
      [[ -z "${job}" ]] && continue
      img="$(
        gcloud run jobs describe "${job}" \
          --region "${region}" \
          "${GCLOUD_PROJECT_ARGS[@]}" \
          --format="value(spec.template.template.spec.containers[0].image)" 2>/dev/null || echo "-"
      )"
      printf "%-44s  %s\n" "${job}" "${img:-"-"}"
    done <<<"${jobs}"
  fi
  echo
done

