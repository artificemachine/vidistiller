#!/usr/bin/env bash
# Restore a verified Vidistiller bundle into an isolated temporary PostgreSQL.
# This drill restores the database in full and a representative job artifact
# locally.  It intentionally refuses an NFS work directory: copying a backup
# from an NFS share into another directory on that same share is not a recovery
# test and gives misleading timing.

set -euo pipefail

: "${BACKUP_BUNDLE:?Set BACKUP_BUNDLE to a verified backup directory}"
: "${APP_ROOT:?Set APP_ROOT to the Vidistiller application root}"
: "${BACKEND_IMAGE:?Set BACKEND_IMAGE to the backend image to validate}"
: "${COSIGN_BACKEND_IDENTITY:?Set COSIGN_BACKEND_IDENTITY to the trusted CI identity regex}"
: "${COSIGN_POSTGRES_IDENTITY:?Set COSIGN_POSTGRES_IDENTITY to the trusted PostgreSQL image identity regex}"
: "${BACKUP_SIGNING_PUBLIC_KEY:?Set BACKUP_SIGNING_PUBLIC_KEY to the trusted backup public key}"
COSIGN_OIDC_ISSUER="${COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"

DRILL_ROOT="${DRILL_ROOT:-/var/tmp/vidistiller-restore-drills}"
POSTGRES_IMAGE="${POSTGRES_IMAGE:?Set POSTGRES_IMAGE to a signed immutable digest}"
REPORT_DIR="${REPORT_DIR:-$(dirname "$(dirname "$BACKUP_BUNDLE")")/vidistiller-drills/reports}"
DATABASE_DUMP="${DATABASE_DUMP:-$BACKUP_BUNDLE/database.dump}"
started_epoch="$(date +%s)"
started_at="$(date -u +%FT%TZ)"

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "Required command is unavailable: $1" >&2
        exit 1
    }
}

require_command "cosign"
for command in docker findmnt sha256sum pg_restore python3; do
    require_command "$command"
done

verify_image() {
    local image="$1"
    local identity="$2"
    cosign verify --certificate-identity-regexp "$identity" \
        --certificate-oidc-issuer "$COSIGN_OIDC_ISSUER" "$image" >/dev/null
}

require_digest_reference() {
    case "$1" in
        *@sha256:*) ;;
        *)
            echo "Image reference must be immutable: $1" >&2
            exit 1
            ;;
    esac
}

# Verify both images before Docker is allowed to create an isolated database or
# execute migration code from an image. Trusted OIDC identities are
# operator-supplied configuration outside the repository.
require_digest_reference "$POSTGRES_IMAGE"
require_digest_reference "$BACKEND_IMAGE"
verify_image "$POSTGRES_IMAGE" "$COSIGN_POSTGRES_IDENTITY"
verify_image "$BACKEND_IMAGE" "$COSIGN_BACKEND_IDENTITY"

[[ -f "$BACKUP_BUNDLE/.verified" ]] || {
    echo "Backup has not been verified: $BACKUP_BUNDLE" >&2
    exit 1
}
[[ -f "$BACKUP_BUNDLE/SHA256SUMS" ]] || {
    echo "Missing checksum manifest: $BACKUP_BUNDLE/SHA256SUMS" >&2
    exit 1
}
[[ -f "$BACKUP_BUNDLE/SHA256SUMS.sig" ]] || {
    echo "Missing signed checksum manifest: $BACKUP_BUNDLE/SHA256SUMS.sig" >&2
    exit 1
}
[[ -f "$DATABASE_DUMP" ]] || {
    echo "Missing PostgreSQL dump" >&2
    exit 1
}

mkdir -p "$DRILL_ROOT" "$REPORT_DIR"
work_fstype="$(findmnt -no FSTYPE -T "$DRILL_ROOT")"
case "$work_fstype" in
    nfs|nfs4)
        echo "DRILL_ROOT must be local storage, not NFS: $DRILL_ROOT" >&2
        exit 1
        ;;
esac

work="$(mktemp -d "$DRILL_ROOT/drill.XXXXXX")"
drill_id="$(basename "$work")"
network="vidistiller-${drill_id}-net"
database="vidistiller-${drill_id}-postgres"
db_user="restore_drill"
db_name="restore_drill"
# Ephemeral database credential for the isolated container; it is generated only at
# runtime and never written to the bundle, report, or application logs.
drill_db_auth="$(openssl rand -hex 24)"

cleanup() {
    docker rm -f "$database" >/dev/null 2>&1 || true
    docker network rm "$network" >/dev/null 2>&1 || true
    rm -rf "$work"
}
trap cleanup EXIT

cosign verify-blob --key "$BACKUP_SIGNING_PUBLIC_KEY" \
    --signature "$BACKUP_BUNDLE/SHA256SUMS.sig" "$BACKUP_BUNDLE/SHA256SUMS" >/dev/null
(cd "$BACKUP_BUNDLE" && sha256sum -c SHA256SUMS --quiet)

docker network create --internal "$network" >/dev/null
docker run -d --name "$database" --network "$network" \
    -e "POSTGRES_USER=$db_user" \
    -e "POSTGRES_PASSWORD=$drill_db_auth" \
    -e "POSTGRES_DB=$db_name" \
    "$POSTGRES_IMAGE" >/dev/null

for attempt in $(seq 1 30); do
    if docker exec -e "PGPASSWORD=$drill_db_auth" "$database" \
        psql -U "$db_user" -d "$db_name" -c 'SELECT 1' >/dev/null 2>&1; then
        break
    fi
    [[ "$attempt" -lt 30 ]] || {
        echo "Temporary PostgreSQL did not become ready" >&2
        exit 1
    }
    sleep 1
done

docker exec -i -e "PGPASSWORD=$drill_db_auth" "$database" \
    pg_restore -U "$db_user" -d "$db_name" --exit-on-error --no-owner --no-privileges \
    < "$DATABASE_DUMP"

database_scheme="postgresql"
database_url="${database_scheme}://${db_user}:${drill_db_auth}@${database}:5432/${db_name}"
docker run --rm --network "$network" \
    -e "DATABASE_URL=$database_url" \
    -v "$APP_ROOT/migrations:/app/migrations:ro" \
    -v "$APP_ROOT/alembic.ini:/app/alembic.ini:ro" \
    "$BACKEND_IMAGE" sh -c 'cd /app && alembic upgrade head'

psql() {
    docker exec -e "PGPASSWORD=$drill_db_auth" "$database" \
        psql -U "$db_user" -d "$db_name" -At "$@"
}

users="$(psql -c 'SELECT count(*) FROM users')"
job_row="$(psql -F '|' -c "SELECT j.id, j.job_id FROM processing_jobs j WHERE j.status = 'completed' AND EXISTS (SELECT 1 FROM transcripts t WHERE t.job_id = j.id AND length(t.full_text) > 0) AND EXISTS (SELECT 1 FROM snapshots s WHERE s.job_id = j.id) ORDER BY j.id DESC LIMIT 1")"
[[ -n "$job_row" ]] || {
    echo "No completed job with transcript and snapshot in restored database" >&2
    exit 1
}
IFS='|' read -r job_pk job_id <<< "$job_row"

snapshot_path="$(psql -c "SELECT file_path FROM snapshots WHERE job_id = ${job_pk} AND file_path IS NOT NULL ORDER BY id LIMIT 1")"
case "$snapshot_path" in
    snapshots/*)
        backup_snapshot_path="$snapshot_path"
        ;;
    /data/snapshots/*)
        backup_snapshot_path="${snapshot_path#/data/}"
        ;;
    *)
        echo "Unexpected restored snapshot path: $snapshot_path" >&2
        exit 1
        ;;
esac

source_snapshot="$BACKUP_BUNDLE/app-data/$backup_snapshot_path"
restored_snapshot="$work/app-data/$backup_snapshot_path"
[[ -f "$source_snapshot" ]] || {
    echo "Snapshot referenced by restored database is absent from bundle" >&2
    exit 1
}
mkdir -p "$(dirname "$restored_snapshot")" "$work/exports"
cp "$source_snapshot" "$restored_snapshot"
cmp -s "$source_snapshot" "$restored_snapshot"

export_path="$work/exports/${job_id}.json"
psql -c "SELECT json_build_object('job_id', j.job_id, 'transcript', (SELECT t.full_text FROM transcripts t WHERE t.job_id = j.id ORDER BY t.id LIMIT 1), 'snapshot_count', (SELECT count(*) FROM snapshots s WHERE s.job_id = j.id), 'document_count', (SELECT count(*) FROM documents d WHERE d.job_id = j.id)) FROM processing_jobs j WHERE j.id = ${job_pk}" > "$export_path"
python3 -c 'import json,sys; payload=json.load(open(sys.argv[1])); assert payload["transcript"]; assert payload["snapshot_count"] > 0' "$export_path"

completed_jobs="$(psql -c "SELECT count(*) FROM processing_jobs WHERE status = 'completed'")"
transcripts="$(psql -c 'SELECT count(*) FROM transcripts')"
snapshots="$(psql -c 'SELECT count(*) FROM snapshots')"
documents="$(psql -c 'SELECT count(*) FROM documents')"
ended_epoch="$(date +%s)"
rpo_seconds="$((started_epoch - $(stat -c %Y "$BACKUP_BUNDLE")))"
rto_seconds="$((ended_epoch - started_epoch))"
report="$REPORT_DIR/restore-drill-$(date -u +%Y%m%dT%H%M%SZ).json"

python3 -c 'import json,sys; json.dump({"result":"passed","scope":"full_database_and_representative_artifacts","started_at":sys.argv[1],"rpo_seconds":int(sys.argv[2]),"rto_seconds":int(sys.argv[3]),"users":int(sys.argv[4]),"completed_jobs":int(sys.argv[5]),"transcripts":int(sys.argv[6]),"snapshots":int(sys.argv[7]),"documents":int(sys.argv[8]),"job_id":sys.argv[9],"restored_snapshot":sys.argv[10],"export_verified":True}, open(sys.argv[11], "w"), sort_keys=True)' "$started_at" "$rpo_seconds" "$rto_seconds" "$users" "$completed_jobs" "$transcripts" "$snapshots" "$documents" "$job_id" "$backup_snapshot_path" "$report"

echo "PASS report=$report"
