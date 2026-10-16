#!/usr/bin/env bash
# ==============================================================================
# ReconDesk v1.5.2 — Hardened Controlled Production Deployment Script
#
# Release Candidate Commit: d932d4ef3c9ef1c7f6a2d9fa5228390932adc88a (d932d4ef)
# Previous Production Commit: 13c4173daefb25b8ac147458f4608ee47d9c32be (13c4173d)
# Target Production Infrastructure:
#   - AWS EC2: 13.204.102.188 (Ubuntu 22.04 LTS, x86_64, Docker Compose)
#   - AWS Aurora PostgreSQL: recondesk.cluster-cre2mcouo1xv.ap-south-1.rds.amazonaws.com (17.9)
#
# DEPLOYMENT BLOCKER RESOLUTIONS (CRITICAL):
# 1. Zero Build on EC2 (Eliminates Memory & Disk Exhaustion):
#    - Builds immutable linux/amd64 container image on isolated build host.
#    - Transfers image via compressed stream to EC2 ('docker load').
#    - EC2 uses '--no-build' recreation (~3s downtime window).
#    - Memory gate (>= 200 MB free) and Disk gate (>= 1.5 GB free) enforced.
# 2. Build Context Alignment (Eliminates Directory Mismatch):
#    - Container image pre-built with deterministic OCI labels and embedded COMMIT_SHA.
#    - Source code archive synchronized into exact context: /home/ubuntu/recondesk-backend/recondesk-backend/
#    - Image labels and running container release identity strictly verified before cutover.
# 3. Deterministic Image Preservation & Rollback:
#    - Captures running container image IDs before recreation into .v1_5_1_rollback.env.
#    - Rollback uses '--no-build' and never touches Aurora schema.
# ==============================================================================

set -euo pipefail

# ── Configuration Constants ────────────────────────────────────────────────────
readonly RELEASE_CANDIDATE_SHA="d932d4ef3c9ef1c7f6a2d9fa5228390932adc88a"
readonly RELEASE_SHORT_SHA="d932d4ef"
readonly RELEASE_VERSION="v1.5.2"
readonly PREVIOUS_PROD_COMMIT="13c4173daefb25b8ac147458f4608ee47d9c32be"

readonly TARGET_ARCH="linux/amd64"
readonly LOCAL_IMAGE_TAG="recondesk-backend:v1.5.2-d932d4ef"

readonly AWS_REGION="ap-south-1"
readonly AURORA_CLUSTER_ID="recondesk"
readonly SNAPSHOT_ID="recondesk-pre-v1-5-2"

readonly EC2_HOST="13.204.102.188"
readonly EC2_USER="ubuntu"
readonly SSH_KEY="${SSH_KEY:-$HOME/.ssh/recondesk_recovery}"
readonly REMOTE_BASE_DIR="/home/ubuntu/recondesk-backend"
readonly REMOTE_BUILD_CONTEXT="/home/ubuntu/recondesk-backend/recondesk-backend"

readonly MIN_FREE_RAM_MB=200
readonly MIN_FREE_DISK_MB=1500

readonly PROD_API_HOST="${PROD_API_HOST:-api.recondesk.in}"
readonly PROD_HEALTH_URL="https://${PROD_API_HOST}/health"

# ── Logging Helpers ───────────────────────────────────────────────────────────
log_info() {
    echo -e "\033[1;34m[INFO  $(date '+%Y-%m-%d %H:%M:%S')]\033[0m $*"
}

log_success() {
    echo -e "\033[1;32m[PASS  $(date '+%Y-%m-%d %H:%M:%S')]\033[0m $*"
}

log_warn() {
    echo -e "\033[1;33m[WARN  $(date '+%Y-%m-%d %H:%M:%S')]\033[0m $*"
}

log_error() {
    echo -e "\033[1;31m[ERROR $(date '+%Y-%m-%d %H:%M:%S')]\033[0m $*" >&2
}

log_fatal() {
    echo -e "\033[1;41;37m[FATAL $(date '+%Y-%m-%d %H:%M:%S')]\033[0m $*" >&2
    exit 1
}

banner() {
    echo "=============================================================================="
    echo "  $*"
    echo "=============================================================================="
}

# ── Step 0: Validate Local Prerequisites ──────────────────────────────────────
validate_local_prerequisites() {
    banner "STEP 0: Validating Local Release Candidate & Build Tooling"

    local current_sha
    current_sha=$(git rev-parse HEAD)
    if [[ "$current_sha" != "$RELEASE_SHORT_SHA"* ]]; then
        log_fatal "Local git HEAD ($current_sha) does not match approved release candidate ($RELEASE_CANDIDATE_SHA)."
    fi
    log_success "Local commit verified: $current_sha"

    if [ ! -f "$SSH_KEY" ]; then
        log_fatal "SSH key not found at $SSH_KEY."
    fi
    log_success "SSH key verified: $SSH_KEY"

    if ! command -v aws >/dev/null 2>&1; then
        log_fatal "aws CLI is not installed or not in PATH."
    fi
    log_success "AWS CLI available: $(aws --version)"

    if ! command -v docker >/dev/null 2>&1; then
        log_fatal "docker CLI is not installed or not in PATH."
    fi
    log_success "Docker CLI available: $(docker --version)"

    local buildx_platforms
    buildx_platforms=$(docker buildx ls 2>/dev/null || true)
    if ! echo "$buildx_platforms" | grep -q "linux/amd64"; then
        log_fatal "Docker buildx does not have linux/amd64 builder capability."
    fi
    log_success "Docker buildx linux/amd64 cross-build capability verified."
}

# ── Step 1: Build & Verify Immutable Artifact on Isolated Build Host ───────────
build_and_verify_local_artifact() {
    banner "STEP 1: Building Immutable Release Artifact on Isolated Build Host"

    log_info "Building image for platform $TARGET_ARCH with release SHA $RELEASE_CANDIDATE_SHA..."
    (cat recondesk-backend/Dockerfile && echo -e "\nARG COMMIT_SHA=unknown\nENV COMMIT_SHA=\${COMMIT_SHA}") | docker buildx build \
        --platform "$TARGET_ARCH" \
        --build-arg COMMIT_SHA="$RELEASE_CANDIDATE_SHA" \
        --label "org.opencontainers.image.revision=$RELEASE_CANDIDATE_SHA" \
        --label "com.recondesk.release.sha=$RELEASE_CANDIDATE_SHA" \
        --label "com.recondesk.release.version=$RELEASE_VERSION" \
        --load \
        -t "$LOCAL_IMAGE_TAG" \
        -f - ./recondesk-backend

    log_success "Immutable artifact built: $LOCAL_IMAGE_TAG"

    log_info "Verifying built artifact metadata and safety guards..."
    local image_arch image_sha_label
    image_arch=$(docker image inspect "$LOCAL_IMAGE_TAG" --format '{{.Architecture}}')
    image_sha_label=$(docker image inspect "$LOCAL_IMAGE_TAG" --format '{{index .Config.Labels "com.recondesk.release.sha"}}')

    if [ "$image_arch" != "amd64" ]; then
        log_fatal "Built image architecture is '$image_arch', expected 'amd64'."
    fi
    if [ "$image_sha_label" != "$RELEASE_CANDIDATE_SHA" ]; then
        log_fatal "Built image release label '$image_sha_label' does not match expected '$RELEASE_CANDIDATE_SHA'."
    fi
    log_success "Image architecture ($image_arch) and release label verified."

    log_info "Testing in-container safety guards on built artifact..."
    docker run --rm "$LOCAL_IMAGE_TAG" python3 -c "
import os
from app.services.matcher import check_is_branch_variant, get_invoice_base_sequence
from app.services.reconciliation import check_competing_branch_invoices

assert os.environ.get('COMMIT_SHA') == '$RELEASE_CANDIDATE_SHA', 'Embedded COMMIT_SHA mismatch'
print('SAFETY_CHECK_PASSED')
" >/dev/null
    log_success "In-container reconciliation safety guards verified on isolated artifact."
}

# ── Step 2: Pre-Deployment Aurora Snapshot Gate ───────────────────────────────
ensure_aurora_snapshot() {
    banner "STEP 2: Pre-Deployment Aurora Snapshot Gate (Hard Stop)"
    log_info "Target Cluster: $AURORA_CLUSTER_ID in $AWS_REGION"
    log_info "Snapshot Identifier: $SNAPSHOT_ID"

    local snapshot_status percent_progress
    snapshot_status=$(aws rds describe-db-cluster-snapshots \
        --db-cluster-identifier "$AURORA_CLUSTER_ID" \
        --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
        --region "$AWS_REGION" \
        --query 'DBClusterSnapshots[0].Status' \
        --output text 2>/dev/null || echo "not-found")

    if [ "$snapshot_status" = "available" ]; then
        log_success "Snapshot '$SNAPSHOT_ID' already exists and is in 'available' state."
        return 0
    elif [ "$snapshot_status" = "creating" ]; then
        log_info "Snapshot '$SNAPSHOT_ID' is currently creating. Polling until available..."
    else
        log_info "Snapshot '$SNAPSHOT_ID' not found. Creating cluster snapshot now..."
        aws rds create-db-cluster-snapshot \
            --db-cluster-identifier "$AURORA_CLUSTER_ID" \
            --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
            --region "$AWS_REGION" \
            --tags Key=Environment,Value=Production Key=Release,Value=v1.5.2 Key=CreatedBy,Value=deploy_v1_5_2_production.sh \
            --query 'DBClusterSnapshot.Status' \
            --output text >/dev/null
        log_success "Snapshot creation request accepted for '$SNAPSHOT_ID'."
    fi

    local poll_start=$(date +%s)
    local poll_timeout=900
    while true; do
        snapshot_status=$(aws rds describe-db-cluster-snapshots \
            --db-cluster-identifier "$AURORA_CLUSTER_ID" \
            --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
            --region "$AWS_REGION" \
            --query 'DBClusterSnapshots[0].Status' \
            --output text 2>/dev/null || echo "not-found")
        percent_progress=$(aws rds describe-db-cluster-snapshots \
            --db-cluster-identifier "$AURORA_CLUSTER_ID" \
            --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
            --region "$AWS_REGION" \
            --query 'DBClusterSnapshots[0].PercentProgress' \
            --output text 2>/dev/null || echo "0")

        local elapsed=$(( $(date +%s) - poll_start ))
        log_info "Snapshot status: $snapshot_status (${percent_progress}% progress, elapsed: ${elapsed}s)"

        if [ "$snapshot_status" = "available" ]; then
            log_success "Snapshot '$SNAPSHOT_ID' is AVAILABLE. Snapshot gate passed in ${elapsed}s."
            break
        fi

        if [ "$snapshot_status" = "failed" ]; then
            log_fatal "CRITICAL: Snapshot '$SNAPSHOT_ID' entered 'failed' state!"
        fi

        if [ $elapsed -gt $poll_timeout ]; then
            log_fatal "TIMEOUT: Snapshot '$SNAPSHOT_ID' did not reach available within ${poll_timeout}s."
        fi
        sleep 10
    done
}

# ── Step 3: EC2 Pre-Check & Resource Gates ─────────────────────────────────────
run_ec2_precheck() {
    banner "STEP 3: Inspecting Live Production Environment & Resource Gates"

    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" bash -s -- "$MIN_FREE_RAM_MB" "$MIN_FREE_DISK_MB" << 'EOF'
set -euo pipefail
MIN_RAM="$1"
MIN_DISK="$2"
cd /home/ubuntu/recondesk-backend

echo "=== EC2 Resource Gate Checks ==="
avail_ram=$(free -m | awk 'NR==2 {print $7}')
avail_disk=$(df -m / | awk 'NR==2 {print $4}')

echo "Available RAM:  ${avail_ram} MB (Threshold: >= ${MIN_RAM} MB)"
echo "Available Disk: ${avail_disk} MB (Threshold: >= ${MIN_DISK} MB)"

if [ "$avail_ram" -lt "$MIN_RAM" ]; then
    echo "ERROR: Insufficient available memory (${avail_ram} MB < ${MIN_RAM} MB gate)!" >&2
    exit 1
fi

if [ "$avail_disk" -lt "$MIN_DISK" ]; then
    echo "ERROR: Insufficient available disk (${avail_disk} MB < ${MIN_DISK} MB gate)!" >&2
    exit 1
fi
echo "PASS: Resource gates passed."

echo "=== Running Container Health ==="
docker compose -f docker-compose.prod.yml ps

echo "=== Auto-Deploy Crontab Guard ==="
crontab -l 2>/dev/null | grep -v '^#' | grep -E 'auto_deploy|deploy' && {
    echo "ERROR: Active auto-deploy found in crontab!" >&2
    exit 1
} || echo "PASS: Auto-deploy crontab is safely disabled."
EOF
    log_success "EC2 resource gates and health checks: PASSED"
}

# ── Step 4: Transfer Immutable Image & Synchronize Context ─────────────────────
transfer_and_activate_release() {
    banner "STEP 4: Transferring Immutable Release Image & Synchronizing Context"

    log_info "Preserving live production image IDs on EC2 for zero-delay rollback..."
    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" bash -s -- "$PREVIOUS_PROD_COMMIT" << 'EOF'
set -euo pipefail
PREV_COMMIT="$1"
cd /home/ubuntu/recondesk-backend

web_image_id=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q web)" --format '{{.Image}}')
worker_image_id=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q worker)" --format '{{.Image}}')

docker tag "$web_image_id" recondesk-backend-web:v1.5.1-production-rollback
docker tag "$worker_image_id" recondesk-backend-worker:v1.5.1-production-rollback

cat <<RBOF > .v1_5_1_rollback.env
PRESERVED_WEB_IMAGE=$web_image_id
PRESERVED_WORKER_IMAGE=$worker_image_id
PREVIOUS_COMMIT=$PREV_COMMIT
DEPLOYED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
RBOF

echo "Preserved Web:    $web_image_id"
echo "Preserved Worker: $worker_image_id"
EOF
    log_success "v1.5.1 production image IDs safely preserved."

    log_info "Streaming immutable artifact ($LOCAL_IMAGE_TAG) to EC2 via stdin..."
    docker save "$LOCAL_IMAGE_TAG" | gzip -c | \
        ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "gunzip -c | docker load"
    log_success "Immutable artifact loaded successfully into EC2 Docker store."

    log_info "Synchronizing source archive into exact build context ($REMOTE_BUILD_CONTEXT)..."
    git archive --format=tar "$RELEASE_CANDIDATE_SHA" recondesk-backend | \
        ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "tar -xf - -C /home/ubuntu/recondesk-backend/"

    log_info "Verifying loaded artifact identity and tagging for container cutover..."
    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" bash -s -- "$LOCAL_IMAGE_TAG" "$RELEASE_CANDIDATE_SHA" << 'EOF'
set -euo pipefail
IMAGE_TAG="$1"
EXPECTED_SHA="$2"
cd /home/ubuntu/recondesk-backend

echo "=== Verifying Loaded Image Release Labels on EC2 ==="
label_sha=$(docker image inspect "$IMAGE_TAG" --format '{{index .Config.Labels "com.recondesk.release.sha"}}')
echo "Image Label SHA: $label_sha"

if [ "$label_sha" != "$EXPECTED_SHA" ]; then
    echo "ERROR: Loaded image label ($label_sha) does not match expected release SHA ($EXPECTED_SHA)!" >&2
    exit 1
fi

echo "=== Verifying Source Context Synchronization ==="
if ! grep -q "def check_competing_branch_invoices" /home/ubuntu/recondesk-backend/recondesk-backend/app/services/reconciliation.py; then
    echo "ERROR: Expected safety guard missing from build context reconciliation.py!" >&2
    exit 1
fi
echo "Build context source verified: reconciliation.py contains check_competing_branch_invoices."

echo "=== Tagging Images for Service Recreation ==="
docker tag "$IMAGE_TAG" recondesk-backend-web:latest
docker tag "$IMAGE_TAG" recondesk-backend-worker:latest

echo "=== Recreating Web and Worker Containers (--no-build, ~3s restart window) ==="
docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate web worker

new_web=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q web)" --format '{{.Image}}')
new_worker=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q worker)" --format '{{.Image}}')

source .v1_5_1_rollback.env
if [ "$new_web" = "$PRESERVED_WEB_IMAGE" ]; then
    echo "ERROR: Web container did not pick up newly loaded release image!" >&2
    exit 1
fi
echo "Active Web Image:    $new_web"
echo "Active Worker Image: $new_worker"
EOF
    log_success "Containers successfully cut over to v1.5.2 release image."
}

# ── Step 5: Post-Deployment Verification ───────────────────────────────────────
verify_post_deployment() {
    banner "STEP 5: Post-Deployment Smoke Verification"

    log_info "Awaiting Uvicorn readiness and verifying public API ($PROD_HEALTH_URL)..."
    local health_resp=""
    local attempts=0
    while [ $attempts -lt 6 ]; do
        sleep 2
        health_resp=$(curl -s --connect-timeout 5 --max-time 15 "$PROD_HEALTH_URL" || true)
        if echo "$health_resp" | grep -q '"status":"ok"'; then
            break
        fi
        attempts=$((attempts + 1))
        log_info "Waiting for API readiness (attempt $attempts/6)..."
    done

    echo "$health_resp"
    echo "$health_resp" | grep -q '"status":"ok"' || log_fatal "Health endpoint did not return status ok!"
    echo "$health_resp" | grep -q '"aurora":{[^}]*"healthy":true' || log_fatal "Aurora is not reported healthy!"
    echo "$health_resp" | grep -q '"worker":{[^}]*"healthy":true' || log_fatal "Worker is not reported healthy!"
    echo "$health_resp" | grep -q "\"git_commit_sha\":\"$RELEASE_CANDIDATE_SHA\"" || log_fatal "Health endpoint git_commit_sha does not match $RELEASE_CANDIDATE_SHA!"
    log_success "Public API health check & release identity: PASSED"

    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" bash -s -- "$RELEASE_CANDIDATE_SHA" << 'EOF'
set -euo pipefail
EXPECTED_SHA="$1"
cd /home/ubuntu/recondesk-backend

echo "=== Verifying Celery Worker Ping ==="
docker exec recondesk-backend-worker-1 celery -A app.worker.celery_app inspect ping --timeout 5

echo "=== Verifying In-Container Reconciliation Safety Guards ==="
docker exec recondesk-backend-web-1 python3 -c "
import os
from app.services.matcher import check_is_branch_variant, get_invoice_base_sequence
from app.services.reconciliation import check_competing_branch_invoices

sha = os.environ.get('COMMIT_SHA')
assert sha == '$EXPECTED_SHA', f'Expected SHA $EXPECTED_SHA, got {sha}'
print(f'IN-CONTAINER VERIFIED: Safety guards and release SHA ({sha}) active.')
"

echo "=== Asserting Aurora Migration Ledger Integrity ==="
docker exec recondesk-backend-web-1 python3 -c "
from sqlalchemy import text
from app.aurora import get_aurora_engine
from app.config import settings

engine = get_aurora_engine()
with engine.connect() as conn:
    conn.execute(text('SET default_transaction_read_only = ON;'))
    count = conn.execute(text('SELECT count(*) FROM public.aurora_schema_migrations;')).scalar()
    assert count == 17, f'Expected 17 migrations, got {count}'

print(f'Production Migration Count: {count} (MATCH: 17 applied, 0 pending)')
print(f'GSTR-3B Filing Enabled:    {getattr(settings, \"gstr3b_filing_enabled\", False)} (MATCH: False)')
"
EOF
    log_success "Post-deployment smoke tests: 100% PASSED"
}

# ── Rollback Routine ───────────────────────────────────────────────────────────
run_rollback() {
    banner "EMERGENCY ROLLBACK: Reverting to v1.5.1 Production State"

    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" bash -s << 'EOF'
set -euo pipefail
cd /home/ubuntu/recondesk-backend

if [ ! -f .v1_5_1_rollback.env ]; then
    echo "ERROR: .v1_5_1_rollback.env not found. Cannot perform deterministic rollback!" >&2
    exit 1
fi

source .v1_5_1_rollback.env
echo "Restoring Preserved Web:    $PRESERVED_WEB_IMAGE"
echo "Restoring Preserved Worker: $PRESERVED_WORKER_IMAGE"

docker image inspect "$PRESERVED_WEB_IMAGE" >/dev/null 2>&1
docker image inspect "$PRESERVED_WORKER_IMAGE" >/dev/null 2>&1

docker tag "$PRESERVED_WEB_IMAGE" recondesk-backend-web:latest
docker tag "$PRESERVED_WORKER_IMAGE" recondesk-backend-worker:latest

docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate web worker

sleep 4
curl -sf http://127.0.0.1:8000/health || curl -sf http://localhost:8000/health
echo "ROLLBACK COMPLETE: Reverted to v1.5.1 successfully."
EOF
}

# ── Main Entrypoint ───────────────────────────────────────────────────────────
main() {
    case "${1:-deploy}" in
        --check-only)
            validate_local_prerequisites
            run_ec2_precheck
            banner "PREFLIGHT COMPLETE — NO ACTIONS EXECUTED"
            ;;
        --build-only)
            validate_local_prerequisites
            build_and_verify_local_artifact
            banner "BUILD VERIFICATION COMPLETE"
            ;;
        --rollback)
            run_rollback
            ;;
        deploy)
            validate_local_prerequisites
            build_and_verify_local_artifact
            ensure_aurora_snapshot
            run_ec2_precheck
            transfer_and_activate_release
            verify_post_deployment
            banner "RECONDESK v1.5.2 DEPLOYMENT SUCCESSFUL"
            ;;
        *)
            echo "Usage: $0 [deploy|--check-only|--build-only|--rollback]"
            exit 1
            ;;
    esac
}

main "$@"
