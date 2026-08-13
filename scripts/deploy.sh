#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${SCRIPT_DIR}/../docker-compose.prod.yml}"
DRY_RUN=false

: "${VIDISTILLER_BACKEND_IMAGE_REF:?Set VIDISTILLER_BACKEND_IMAGE_REF to a signed immutable backend digest}"
: "${VIDISTILLER_FRONTEND_IMAGE_REF:?Set VIDISTILLER_FRONTEND_IMAGE_REF to a signed immutable frontend digest}"
: "${COSIGN_CERTIFICATE_IDENTITY_REGEXP:?Set COSIGN_CERTIFICATE_IDENTITY_REGEXP to the trusted CI workflow identity}"
COSIGN_OIDC_ISSUER="${COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

usage() {
  echo "Usage: $(basename "$0") [--dry-run]" >&2
  echo "  --dry-run  Print what would happen without making any changes" >&2
  exit 1
}

require_digest_reference() {
  case "$1" in
    *@sha256:*) ;;
    *)
      echo "[deploy] image reference must be immutable: $1" >&2
      exit 1
      ;;
  esac
}

verify_release_images() {
  require_digest_reference "$VIDISTILLER_BACKEND_IMAGE_REF"
  require_digest_reference "$VIDISTILLER_FRONTEND_IMAGE_REF"
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] cosign verify backend and frontend image digests"
    return
  fi
  command -v cosign >/dev/null 2>&1 || {
    echo "[deploy] cosign is required to verify release images" >&2
    exit 1
  }
  for image in "$VIDISTILLER_BACKEND_IMAGE_REF" "$VIDISTILLER_FRONTEND_IMAGE_REF"; do
    cosign verify \
      --certificate-identity-regexp "$COSIGN_CERTIFICATE_IDENTITY_REGEXP" \
      --certificate-oidc-issuer "$COSIGN_OIDC_ISSUER" \
      "$image" >/dev/null
  done
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
done

force_remove_project_containers() {
  local -a name_arr
  mapfile -t name_arr < <(docker container ls -a --no-trunc --format '{{.Names}}' 2>/dev/null | grep '^tutorial_' || true)

  if [[ ${#name_arr[@]} -eq 0 ]]; then
    echo "[deploy] No tutorial_ containers found — skipping force-remove"
    return
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] docker rm -f ${name_arr[*]}"
  else
    docker rm -f "${name_arr[@]}"
  fi
}

compose_pull() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] docker compose -f $COMPOSE_FILE pull"
  else
    docker compose -f "$COMPOSE_FILE" pull
  fi
}

compose_up() {
  if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY-RUN] docker compose -f $COMPOSE_FILE up -d"
  else
    docker compose -f "$COMPOSE_FILE" up -d
  fi
}

echo "[deploy] Verifying signed immutable release images"
verify_release_images

echo "[deploy] Step 1: force-remove project containers by name (any status)"
force_remove_project_containers

echo "[deploy] Step 2: pull latest images"
compose_pull

echo "[deploy] Step 3: bring stack up"
compose_up

echo "[deploy] Done"
