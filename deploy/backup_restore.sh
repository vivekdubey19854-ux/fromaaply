#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_CONTAINER:=formwise-postgres-1}"
: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$BACKUP_DIR/formwise-$STAMP.dump"
docker exec "$POSTGRES_CONTAINER" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$FILE"
pg_restore --list "$FILE" >/dev/null
find "$BACKUP_DIR" -type f -name '*.dump' -mtime +30 -delete
echo "Backup verified: $FILE"
# Restore drill (staging only): CREATE DATABASE restore_drill; pg_restore --clean --if-exists -d restore_drill FILE
