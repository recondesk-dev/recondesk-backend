#!/usr/bin/env bash
# Supabase Project Migration Wrapper Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "Running Supabase Project Migration Tool..."
python3 "$SCRIPT_DIR/migrate_supabase.py" "$@"
