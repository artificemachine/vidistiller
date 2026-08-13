#!/usr/bin/env bash
# Create a verified Vidistiller backup on a mounted NAS.
#
# Runtime configuration belongs in an EnvironmentFile (not this script):
#   VIDISTILLER_ROOT, BACKUP_ROOT, BACKUP_KEEP_DAYS, BACKUP_SIGNING_KEY,
#   BACKUP_SIGNING_PASSWORD_FILE

set -euo pipefail

: "${VIDISTILLER_ROOT:?VIDISTILLER_ROOT is required}"
: "${BACKUP_ROOT:?BACKUP_ROOT is required}"
: "${BACKUP_KEEP_DAYS:=7}"
: "${BACKUP_SIGNING_KEY:?BACKUP_SIGNING_KEY is required}"
: "${BACKUP_SIGNING_PASSWORD_FILE:?BACKUP_SIGNING_PASSWORD_FILE is required}"

readonly lock_file="${BACKUP_ROOT}/.backup.lock"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
readonly timestamp
readonly staging="${BACKUP_ROOT}/.incomplete-${timestamp}"
readonly final_bundle="${BACKUP_ROOT}/backup-${timestamp}"

require_nas_mount() {
  [[ "$(findmnt -T "${BACKUP_ROOT}" -n -o FSTYPE)" == nfs* ]] || {
    echo "BACKUP_ROOT is not on an NFS mount: ${BACKUP_ROOT}" >&2
    exit 1
  }
}

cleanup_incomplete() {
  [[ -d "${staging}" ]] && rm -rf -- "${staging}"
}

require_nas_mount
command -v cosign >/dev/null 2>&1 || {
  echo "cosign is required to sign backup manifests" >&2
  exit 1
}
[[ -r "${BACKUP_SIGNING_KEY}" && -r "${BACKUP_SIGNING_PASSWORD_FILE}" ]] || {
  echo "backup signing key or password file is unreadable" >&2
  exit 1
}
install -d -m 0750 "${BACKUP_ROOT}"
exec 9>"${lock_file}"
flock -n 9 || {
  echo "another backup is already running" >&2
  exit 0
}
trap cleanup_incomplete ERR INT TERM

mkdir -m 0750 "${staging}"
cd "${VIDISTILLER_ROOT}"

docker compose -f docker-compose.prod.yml exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > "${staging}/database.dump"

# App media consists mainly of small generated artifacts.  A tree copy to NFS
# is metadata-bound and makes the recovery point take hours to produce.  Keep
# the same complete payload in one archive so the offsite transfer is a single
# sequential write; the isolated drill extracts it to local storage.
# Hidden files are temporary encodes created by workers and never belong in a
# recoverable artifact set.
tar -C app-data --exclude='./.*' --exclude='*/.*' -cf "${staging}/app-data.tar" .

mkdir -p "${staging}/config"
for safe_config in docker-compose.prod.yml alembic.ini .env.example; do
  [[ -f "${safe_config}" ]] && cp -- "${safe_config}" "${staging}/config/"
done
if [[ -f config/llm_model_profiles.json ]]; then
  mkdir -p "${staging}/config/config"
  cp -- config/llm_model_profiles.json "${staging}/config/config/"
fi
cp -a migrations "${staging}/config/migrations"

(
  cd "${staging}"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum
) > "${staging}/SHA256SUMS"
(
  cd "${staging}"
  sha256sum -c SHA256SUMS >/dev/null
)
COSIGN_PASSWORD="$(<"${BACKUP_SIGNING_PASSWORD_FILE}")" \
  cosign sign-blob --yes --key "$BACKUP_SIGNING_KEY" \
  --output-signature "${staging}/SHA256SUMS.sig" "${staging}/SHA256SUMS"
touch "${staging}/.verified"

mv -- "${staging}" "${final_bundle}"
trap - ERR INT TERM

# Retention only applies to complete bundles with the dedicated prefix.
find "${BACKUP_ROOT}" -maxdepth 1 -mindepth 1 -type d -name 'backup-*' \
  -mtime "+${BACKUP_KEEP_DAYS}" -exec rm -rf -- {} +

echo "backup verified: ${final_bundle}"
