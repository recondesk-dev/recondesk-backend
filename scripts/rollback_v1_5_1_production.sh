#!/usr/bin/env bash
# ==============================================================================
# ReconDesk v1.5.1 — Emergency Rollback Script to v1.5.0
#
# Target Infrastructure: AWS EC2 (13.204.102.188)
# Rollback Image Web:    sha256:29659c8a357d62825845c4bf30149468efd27955758208aa4744836021845e29
# Rollback Image Worker: sha256:e6ba43a383607086f9326ac912e5c93bc463e9e940bd16f7dfe1fac07062cd39
# Previous Commit:       f7e77afcb8c4a3953de94586d13c734457894e7d
#
# CRITICAL SAFETY GUARANTEE:
# Uses --no-build with preserved images.
# Asserts running container image IDs match preserved image IDs.
# NEVER automatically downgrades the database or drops columns.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_SCRIPT="$SCRIPT_DIR/deploy_v1_5_1_production.sh"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    echo "Usage: $0 [--help]"
    echo ""
    echo "Initiates zero-rebuild rollback of web and worker containers on EC2 to v1.5.0 binaries."
    echo "Safety guarantee: Database columns are NEVER dropped or downgraded."
    exit 0
fi

if [ ! -f "$DEPLOY_SCRIPT" ]; then
    echo "ERROR: deploy_v1_5_1_production.sh not found at $DEPLOY_SCRIPT" >&2
    exit 1
fi

exec "$DEPLOY_SCRIPT" --rollback "$@"
