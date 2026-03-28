#!/usr/bin/env bash
# Setup the kernelchat database schema.
# Run from inside the app container (or anywhere with psql access).
set -euo pipefail

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-kernelchat}"
DB_USER="${DB_USER:-kernelchat}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEMA_FILE="${SCRIPT_DIR}/../src/db/schema.sql"

echo "Applying schema to ${DB_NAME}@${DB_HOST}:${DB_PORT}..."
PGPASSWORD="${DB_PASSWORD:-kernelchat}" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -f "$SCHEMA_FILE" \
    -v ON_ERROR_STOP=1

echo "Schema applied successfully."
