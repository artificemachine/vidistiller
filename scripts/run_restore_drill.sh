#!/usr/bin/env bash
# Run an isolated restore drill against the newest complete NAS bundle.
#
# Runtime configuration belongs in /etc/vidistiller/restore-drill.conf:
# APP_ROOT, BACKUP_ROOT, POSTGRES_IMAGE, COSIGN_BACKEND_IDENTITY,
# COSIGN_POSTGRES_IDENTITY and BACKUP_SIGNING_PUBLIC_KEY.

set -euo pipefail

: "${APP_ROOT:?APP_ROOT is required}"
: "${BACKUP_ROOT:?BACKUP_ROOT is required}"
: "${POSTGRES_IMAGE:?POSTGRES_IMAGE is required}"
: "${COSIGN_BACKEND_IDENTITY:?COSIGN_BACKEND_IDENTITY is required}"
: "${COSIGN_POSTGRES_IDENTITY:?COSIGN_POSTGRES_IDENTITY is required}"
: "${BACKUP_SIGNING_PUBLIC_KEY:?BACKUP_SIGNING_PUBLIC_KEY is required}"

backend_ref="$(awk -F= '$1 == "VIDISTILLER_BACKEND_IMAGE_REF" { value = substr($0, index($0, "=") + 1) } END { print value }' "$APP_ROOT/.env")"
readonly backend_ref
case "$backend_ref" in
  *@sha256:*) ;;
  *)
    echo "VIDISTILLER_BACKEND_IMAGE_REF must be an immutable digest" >&2
    exit 1
    ;;
esac

BACKUP_BUNDLE="$(find "$BACKUP_ROOT" -maxdepth 1 -mindepth 1 -type d -name 'backup-*' -print | sort | tail -n 1)"
readonly BACKUP_BUNDLE
[[ -n "$BACKUP_BUNDLE" && -f "$BACKUP_BUNDLE/.verified" ]] || {
  echo "No verified backup bundle is available" >&2
  exit 1
}

exec env \
  BACKUP_BUNDLE="$BACKUP_BUNDLE" \
  APP_ROOT="$APP_ROOT" \
  BACKEND_IMAGE="$backend_ref" \
  POSTGRES_IMAGE="$POSTGRES_IMAGE" \
  COSIGN_BACKEND_IDENTITY="$COSIGN_BACKEND_IDENTITY" \
  COSIGN_POSTGRES_IDENTITY="$COSIGN_POSTGRES_IDENTITY" \
  BACKUP_SIGNING_PUBLIC_KEY="$BACKUP_SIGNING_PUBLIC_KEY" \
  /usr/local/sbin/vidistiller-restore-drill
