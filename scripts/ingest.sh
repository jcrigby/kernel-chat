#!/usr/bin/env bash
# Run the full ingestion pipeline: setup DB schema then load commits.
# Usage: ingest.sh [limit]
#   limit: max commits to ingest (default: all)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Setting up database schema..."
bash "$SCRIPT_DIR/setup_db.sh"

LIMIT="${1:-0}"
if [ "$LIMIT" -gt 0 ] 2>/dev/null; then
    echo "Ingesting up to $LIMIT commits..."
    python -m src.ingest.load "$LIMIT"
else
    echo "Ingesting all commits (this will take many hours)..."
    python -m src.ingest.load
fi
