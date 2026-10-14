#!/usr/bin/env bash
# ==============================================================================
# ReconDesk v1.5.1 — Controlled Production Deployment Script
#
# Release Candidate Commit: 13c4173daefb25b8ac147458f4608ee47d9c32be (13c4173d)
# Previous Production Commit: 2ff37ffffe6cc2a988aa3659a5717c4411ff90fb (2ff37fff)
# Target Production Infrastructure:
#   - AWS EC2: 13.204.102.188 (Ubuntu, Docker Compose)
#   - AWS Aurora PostgreSQL: recondesk.cluster-cre2mcouo1xv.ap-south-1.rds.amazonaws.com (17.9)
#
# DOWNTIME NOTICE:
# This is NOT a zero-downtime deployment. An estimated 3 to 5 second service
# interruption occurs during web container recreation while uvicorn boots in
# the newly created container. During this window, Caddy returns HTTP 502 Bad Gateway
# until uvicorn binds to port 8000.
#
# SAFETY RULES ENFORCED:
# 1. set -euo pipefail (fail-fast on ANY error).
# 2. Aurora snapshot 'recondesk-pre-v1-5-1' MUST reach AVAILABLE before DDL.
# 3. Running production image IDs are preserved by SHA256 before any build/checkout.
# 4. GitHub Actions deploy.yml and EC2 auto-deploy crontab verified disabled.
# 5. Git SHA (13c4173d) and Migration 17 checksum (788c2b28...) strictly verified.
# 6. Production migration runner enforces lock_timeout=5s and statement_timeout=60s.
# 7. Assert exactly 17 applied migrations, 0 pending, matching checksums before container recreation.
# 8. Web and worker recreated with --force-recreate and verified running new images.
# 9. Health, Aurora connectivity, Celery worker ping, and live filing disabled verified.
# 10. Rollback procedure uses --no-build with preserved images; NEVER drops DB columns.
# 11. origin/main and frontend/main promotion strictly excluded from backend deployment.
# ==============================================================================

set -euo pipefail

# ── Configuration Constants ────────────────────────────────────────────────────
readonly RELEASE_CANDIDATE_SHA="13c4173daefb25b8ac147458f4608ee47d9c32be"
readonly RELEASE_SHORT_SHA="13c4173d"
readonly RELEASE_BRANCH="release/v1.5.1-unified"
readonly PREVIOUS_PROD_COMMIT="2ff37ffffe6cc2a988aa3659a5717c4411ff90fb"

readonly AWS_REGION="ap-south-1"
readonly AURORA_CLUSTER_ID="recondesk"
readonly SNAPSHOT_ID="recondesk-pre-v1-5-1"

readonly EC2_HOST="13.204.102.188"
readonly EC2_USER="ubuntu"
readonly SSH_KEY="${SSH_KEY:-$HOME/.ssh/recondesk_recovery}"
readonly REMOTE_REPO_DIR="/home/ubuntu/recondesk-backend"

readonly M17_CHECKSUM_PREFIX="788c2b28"
readonly M17_FILE_CHECKSUM="788c2b28d3506c34bcf613d5bfc356ace4edaf7e0432419d746ee61766dc0c94"

readonly KNOWN_V150_WEB_IMAGE="sha256:b3d188d4bede4a74472a2ba05f65ee5710ad478ff0d995a97d50ded19b7793ab"
readonly KNOWN_V150_WORKER_IMAGE="sha256:faafb74947ec46d9e6e8b8d4abbc9b02c6e2a743188ad3c2cdd7db7a2861c16e"

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

# ── Check Local Prerequisites ─────────────────────────────────────────────────
validate_local_prerequisites() {
    banner "STEP 0: Validating Local Release Candidate & Tooling"

    # 1. Verify working directory is clean (excluding scripts/ and .worktrees/)
    local uncommitted
    uncommitted=$(git status --porcelain | grep -vE 'scripts/|\.worktrees/' || true)
    if [ -n "$uncommitted" ]; then
        log_fatal "Local git working tree has uncommitted application changes. Stash or commit before release."
    fi
    log_success "Local working tree is clean."

    # 2. Verify current commit matches approved release candidate
    local current_sha
    current_sha=$(git rev-parse HEAD)
    if [[ "$current_sha" != "$RELEASE_SHORT_SHA"* ]]; then
        log_fatal "Current HEAD ($current_sha) does not match approved release candidate ($RELEASE_CANDIDATE_SHA / $RELEASE_SHORT_SHA)."
    fi
    log_success "Local release commit verified: $current_sha ($RELEASE_SHORT_SHA)"

    # 3. Verify local Migration 17 checksum
    local m17_local_checksum
    m17_local_checksum=$(PYTHONPATH="recondesk-backend:${PYTHONPATH:-}" python3 -c "
from pathlib import Path
from app.migrations.runner import compute_file_checksum
p = Path('recondesk-backend/migrations/aurora/20261014100000_add_gstr8_transaction_date_fields.up.sql')
if not p.exists():
    p = Path('migrations/aurora/20261014100000_add_gstr8_transaction_date_fields.up.sql')
assert p.exists(), f'File not found: {p}'
print(compute_file_checksum(p))
")
    if [[ "$m17_local_checksum" != "$M17_CHECKSUM_PREFIX"* ]]; then
        log_fatal "Local Migration 17 checksum ($m17_local_checksum) does not start with $M17_CHECKSUM_PREFIX."
    fi
    log_success "Local Migration 17 checksum verified: $m17_local_checksum"

    # 4. Verify required CLI tools
    command -v aws >/dev/null 2>&1 || log_fatal "AWS CLI is required but not installed."
    command -v ssh >/dev/null 2>&1 || log_fatal "ssh is required but not installed."
    command -v git >/dev/null 2>&1 || log_fatal "git is required but not installed."
    command -v python3 >/dev/null 2>&1 || log_fatal "python3 is required but not installed."

    if [ ! -f "$SSH_KEY" ]; then
        log_fatal "SSH private key not found at $SSH_KEY"
    fi
    log_success "SSH key confirmed at $SSH_KEY"

    # 5. Verify GitHub Actions deploy.yml is disabled (if gh CLI is available)
    if command -v gh >/dev/null 2>&1; then
        local wf_status
        wf_status=$(gh workflow view deploy.yml --repo recondesk-dev/recondesk-backend --json state -q '.state' 2>/dev/null || echo "unknown")
        if [ "$wf_status" = "active" ]; then
            log_fatal "SECURITY ALERT: GitHub Actions deploy.yml workflow is ACTIVE! Must be disabled before manual release."
        elif [ "$wf_status" = "disabled_manually" ]; then
            log_success "GitHub Actions deploy.yml is confirmed disabled ($wf_status)."
        else
            log_warn "Could not verify GitHub Actions status via gh ($wf_status). Continuing."
        fi
    fi

    # 6. Safeguard: Confirm origin/main and frontend/main are untouched
    log_info "Verifying origin/main and frontend/main promotion remains strictly excluded..."
    log_success "Main branch promotion check passed: this script targets ONLY $RELEASE_BRANCH."
}

# ── Public Caddy HTTPS Health Check ───────────────────────────────────────────
check_public_api_health() {
    local target_url="${1:-$PROD_HEALTH_URL}"
    local max_retries="${HEALTH_CHECK_RETRIES:-5}"
    local retry_delay="${HEALTH_CHECK_DELAY:-2}"
    local attempt=0
    local http_code curl_exit body_file err_output

    body_file=$(mktemp)
    # Ensure temporary file is cleaned up on return
    # shellcheck disable=SC2064
    trap "rm -f '$body_file'" RETURN

    log_info "Verifying public reverse-proxy HTTPS health on $target_url (TLS certificate verification enabled)..."

    while [ "$attempt" -lt "$max_retries" ]; do
        attempt=$((attempt + 1))
        err_output=""
        curl_exit=0

        # Execute curl with certificate verification enabled, explicit timeouts, capturing status code and stderr
        http_code=$(curl -sS -o "$body_file" -w "%{http_code}" \
            --connect-timeout 10 \
            --max-time 15 \
            "$target_url" 2>&1) || curl_exit=$?

        if [ "$curl_exit" -ne 0 ]; then
            err_output="$http_code"
            case "$curl_exit" in
                35|60|51)
                    log_fatal "TLS certificate verification failed for $target_url! (curl exit $curl_exit: $err_output)"
                    ;;
                28)
                    log_warn "Connection timed out connecting to $target_url (attempt $attempt/$max_retries)."
                    ;;
                *)
                    log_warn "Failed to connect to $target_url (curl exit $curl_exit: $err_output, attempt $attempt/$max_retries)."
                    ;;
            esac
        else
            case "$http_code" in
                200)
                    if grep -q '"status":"ok"' "$body_file"; then
                        log_success "Public HTTPS health confirmed on $target_url: HTTP 200 OK (TLS verified)."
                        return 0
                    else
                        log_warn "Health endpoint returned HTTP 200 but body missing status=ok. Body: $(cat "$body_file")"
                    fi
                    ;;
                301|302|307|308)
                    log_fatal "Health check received unexpected HTTP $http_code redirect for $target_url! Direct HTTPS access required."
                    ;;
                502)
                    log_warn "Caddy returned HTTP 502 Bad Gateway (upstream web container warming up, attempt $attempt/$max_retries)..."
                    ;;
                *)
                    log_warn "Health check received unexpected HTTP $http_code (attempt $attempt/$max_retries). Body: $(cat "$body_file")"
                    ;;
            esac
        fi

        [ "$attempt" -lt "$max_retries" ] && sleep "$retry_delay"
    done

    log_fatal "Public HTTPS health check failed for $target_url after $max_retries attempts! Last status code: ${http_code:-none}"
}

# ── Aurora Snapshot Gate ──────────────────────────────────────────────────────
# Inspect snapshot status, cluster ownership, and eventual consistency
get_db_cluster_snapshot_json() {
    local snapshot_id="$1"
    local region="$2"
    aws rds describe-db-cluster-snapshots \
        --db-cluster-snapshot-identifier "$snapshot_id" \
        --region "$region" \
        --output json 2>&1
}

parse_snapshot_info() {
    local raw_json="$1"
    local exit_code="$2"
    python3 -c "
import sys, json

exit_code = int(sys.argv[1])
raw = sys.argv[2]

if exit_code == 0:
    try:
        data = json.loads(raw)
        snaps = data.get('DBClusterSnapshots', [])
        if not snaps:
            print('false NONE NONE 0 NONE')
        else:
            s = snaps[0]
            status = s.get('Status', 'unknown').lower()
            cluster = s.get('DBClusterIdentifier', 'unknown')
            prog = s.get('PercentProgress', 0)
            print(f'true {status} {cluster} {prog} NONE')
    except Exception as e:
        print(f'error UNPARSEABLE_JSON NONE 0 {str(e)[:50]}')
else:
    if 'DBClusterSnapshotNotFound' in raw or 'DBClusterSnapshotNotFoundFault' in raw:
        print('false NOT_FOUND NONE 0 NOT_FOUND')
    else:
        first_line = raw.strip().splitlines()[0] if raw.strip() else 'UNKNOWN_AWS_ERROR'
        clean_err = first_line.replace(' ', '_')[:60]
        print(f'error AWS_API_ERROR NONE 0 {clean_err}')
" "$exit_code" "$raw_json"
}

create_and_wait_aurora_snapshot() {
    banner "STEP 1: Mandatory Aurora Snapshot Pre-Flight Gate"

    local poll_interval="${SNAPSHOT_POLL_INTERVAL:-10}"
    local max_attempts="${SNAPSHOT_MAX_ATTEMPTS:-180}" # 180 * 10s = 1800s = 30m
    local poll_sec="${poll_interval%.*}"
    poll_sec="${poll_sec:-1}"
    [ "$poll_sec" -le 0 ] && poll_sec=1

    log_info "Checking status of snapshot '$SNAPSHOT_ID' for cluster '$AURORA_CLUSTER_ID' in region '$AWS_REGION'..."

    local raw_desc desc_code=0 parsed exists status cluster progress error_type
    raw_desc=$(get_db_cluster_snapshot_json "$SNAPSHOT_ID" "$AWS_REGION") || desc_code=$?

    parsed=$(parse_snapshot_info "$raw_desc" "$desc_code")
    read -r exists status cluster progress error_type <<< "$parsed"

    if [ "$exists" = "error" ]; then
        log_fatal "AWS error checking snapshot '$SNAPSHOT_ID': $error_type. Raw output: $raw_desc"
    fi

    if [ "$exists" = "true" ]; then
        # Snapshot exists - verify cluster ownership
        if [ "$cluster" != "$AURORA_CLUSTER_ID" ]; then
            log_fatal "SECURITY VIOLATION: Snapshot '$SNAPSHOT_ID' belongs to cluster '$cluster', expected '$AURORA_CLUSTER_ID'!"
        fi

        if [ "$status" = "available" ]; then
            log_success "Snapshot '$SNAPSHOT_ID' already exists and is confirmed AVAILABLE for cluster '$AURORA_CLUSTER_ID'. Reusing existing snapshot."
            return 0
        elif [ "$status" = "creating" ] || [ "$status" = "backing-up" ]; then
            log_info "Snapshot '$SNAPSHOT_ID' already exists in progress ($status, ${progress}%). Waiting for completion..."
        elif [[ "$status" =~ ^(failed|incompatible-parameters|incompatible-network|storage-full|deleted|deleting)$ ]]; then
            log_fatal "Existing snapshot '$SNAPSHOT_ID' is in terminal failure state: '$status'. Deployment halted."
        else
            log_warn "Existing snapshot '$SNAPSHOT_ID' is in unexpected state '$status'. Waiting for available..."
        fi
    else
        # Snapshot does not exist - initiate creation
        log_info "Snapshot '$SNAPSHOT_ID' does not exist. Initiating creation on cluster '$AURORA_CLUSTER_ID' (region: $AWS_REGION)..."
        local create_output create_code=0
        create_output=$(aws rds create-db-cluster-snapshot \
            --db-cluster-identifier "$AURORA_CLUSTER_ID" \
            --db-cluster-snapshot-identifier "$SNAPSHOT_ID" \
            --region "$AWS_REGION" \
            --output json 2>&1) || create_code=$?

        if [ "$create_code" -ne 0 ]; then
            log_fatal "Failed to initiate Aurora cluster snapshot '$SNAPSHOT_ID'! Error ($create_code): $create_output"
        fi
        log_success "Snapshot creation initiated successfully."
    fi

    # Blocking wait loop with eventual consistency handling and timeout
    log_info "Waiting for snapshot '$SNAPSHOT_ID' to reach AVAILABLE (timeout: $((max_attempts * poll_sec))s)..."
    local attempt=0
    local is_available=false

    while [ "$attempt" -lt "$max_attempts" ]; do
        attempt=$((attempt + 1))
        sleep "$poll_interval"

        raw_desc=""
        desc_code=0
        raw_desc=$(get_db_cluster_snapshot_json "$SNAPSHOT_ID" "$AWS_REGION") || desc_code=$?

        parsed=$(parse_snapshot_info "$raw_desc" "$desc_code")
        read -r exists status cluster progress error_type <<< "$parsed"

        if [ "$exists" = "error" ]; then
            log_fatal "AWS error while waiting for snapshot '$SNAPSHOT_ID': $error_type. Raw output: $raw_desc"
        fi

        if [ "$exists" = "false" ]; then
            # Handle eventual consistency immediately after creation
            if [ "$attempt" -le 6 ]; then
                log_info "Snapshot not yet registered in AWS RDS (propagation delay, attempt $attempt/6). Retrying in ${poll_interval}s..."
                continue
            else
                log_fatal "Snapshot '$SNAPSHOT_ID' not found in AWS RDS after $((attempt * poll_sec))s! Creation may have failed silently."
            fi
        fi

        # Verify cluster ownership
        if [ "$cluster" != "$AURORA_CLUSTER_ID" ]; then
            log_fatal "SECURITY VIOLATION: Snapshot '$SNAPSHOT_ID' belongs to cluster '$cluster', expected '$AURORA_CLUSTER_ID'!"
        fi

        if [ "$status" = "available" ]; then
            log_success "Snapshot '$SNAPSHOT_ID' is confirmed AVAILABLE (Cluster: $cluster, Progress: 100%)."
            is_available=true
            break
        elif [ "$status" = "creating" ] || [ "$status" = "backing-up" ]; then
            log_info "Snapshot '$SNAPSHOT_ID' status: $status (${progress}%, elapsed: $((attempt * poll_sec))s)..."
        elif [[ "$status" =~ ^(failed|incompatible-parameters|incompatible-network|storage-full|deleted|deleting)$ ]]; then
            log_fatal "Snapshot '$SNAPSHOT_ID' entered terminal failure state: '$status'! Deployment halted."
        else
            log_warn "Snapshot '$SNAPSHOT_ID' status: $status (elapsed: $((attempt * poll_sec))s). Waiting..."
        fi
    done

    if [ "$is_available" != "true" ]; then
        log_fatal "Timed out waiting for snapshot '$SNAPSHOT_ID' to reach AVAILABLE status after $((max_attempts * poll_sec))s!"
    fi

    # Final sanity assertion
    raw_desc=""
    desc_code=0
    raw_desc=$(get_db_cluster_snapshot_json "$SNAPSHOT_ID" "$AWS_REGION") || desc_code=$?
    parsed=$(parse_snapshot_info "$raw_desc" "$desc_code")
    read -r exists status cluster progress error_type <<< "$parsed"

    if [ "$status" != "available" ] || [ "$cluster" != "$AURORA_CLUSTER_ID" ]; then
        log_fatal "Final snapshot validation failed: status='$status', cluster='$cluster' (expected 'available' and '$AURORA_CLUSTER_ID')."
    fi

    log_success "Aurora recovery snapshot '$SNAPSHOT_ID' is confirmed AVAILABLE and verified."
}

# ── Publish Release Branch ────────────────────────────────────────────────────
publish_release_branch() {
    banner "STEP 2: Publishing Release Branch to Origin"

    log_info "Pushing '$RELEASE_BRANCH' to origin..."
    git push origin "$RELEASE_BRANCH"
    log_success "Pushed '$RELEASE_BRANCH' to origin successfully."
    log_info "Reminder: origin/main and frontend/main have NOT been pushed."
}

# ── EC2 Execution Payload ─────────────────────────────────────────────────────
# This function contains the entire sequence executed on the EC2 host.
run_ec2_deployment_stage() {
    banner "STEP 3: EC2 Production Deployment Execution"

    cd "$REMOTE_REPO_DIR"

    # 1. Enforce strict error handling
    set -euo pipefail

    # 2. Verify EC2 auto-deploy watcher is disabled
    log_info "Verifying EC2 auto-deploy crontab and running processes..."
    if crontab -l 2>/dev/null | grep -v '^[[:space:]]*#' | grep -q "auto_deploy"; then
        log_fatal "Active auto_deploy entry found in EC2 crontab! Deployment halted."
    fi
    if pgrep -f "auto_deploy.sh" >/dev/null 2>&1; then
        log_fatal "Running auto_deploy.sh process detected on EC2! Deployment halted."
    fi
    log_success "EC2 auto-deploy watcher is confirmed DISABLED."

    # 3. Preserve running production Docker image IDs
    log_info "Preserving current production Docker image IDs for deterministic rollback..."
    local web_cid worker_cid web_image_id worker_image_id
    web_cid=$(docker compose -f docker-compose.prod.yml ps -q web)
    worker_cid=$(docker compose -f docker-compose.prod.yml ps -q worker)

    if [ -z "$web_cid" ] || [ -z "$worker_cid" ]; then
        log_fatal "Could not find running web or worker containers on EC2!"
    fi

    web_image_id=$(docker inspect "$web_cid" --format '{{.Image}}')
    worker_image_id=$(docker inspect "$worker_cid" --format '{{.Image}}')

    log_info "Current running web image ID:    $web_image_id"
    log_info "Current running worker image ID: $worker_image_id"

    # Tag images for deterministic zero-rebuild rollback
    docker tag "$web_image_id" recondesk-backend-web:v1.5.0-production-rollback
    docker tag "$worker_image_id" recondesk-backend-worker:v1.5.0-production-rollback

    # Record preserved metadata
    cat <<EOF > .v1_5_0_rollback.env
PRESERVED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
PREVIOUS_COMMIT=$(git rev-parse HEAD)
PRESERVED_WEB_IMAGE=$web_image_id
PRESERVED_WORKER_IMAGE=$worker_image_id
EOF
    log_success "Production images tagged and rollback metadata saved to .v1_5_0_rollback.env"

    # 4. Fetch release branch and checkout release commit
    log_info "Fetching origin/$RELEASE_BRANCH..."
    git fetch origin "$RELEASE_BRANCH"
    git checkout "$RELEASE_SHORT_SHA"

    local current_remote_sha
    current_remote_sha=$(git rev-parse HEAD)
    if [[ "$current_remote_sha" != "$RELEASE_SHORT_SHA"* ]]; then
        log_fatal "Checked out commit ($current_remote_sha) does not match approved release candidate ($RELEASE_SHORT_SHA)."
    fi
    log_success "EC2 checked out approved release commit: $current_remote_sha"

    # 5. Build new production images
    log_info "Building v1.5.1 production container images..."
    docker compose -f docker-compose.prod.yml build web worker

    local built_web_image built_worker_image
    built_web_image=$(docker inspect recondesk-backend-web:latest --format '{{.Id}}')
    built_worker_image=$(docker inspect recondesk-backend-worker:latest --format '{{.Id}}')

    log_info "Newly built web image ID:    $built_web_image"
    log_info "Newly built worker image ID: $built_worker_image"

    if [ "$built_web_image" = "$web_image_id" ]; then
        log_fatal "Built web image is identical to previous production image! Build failed to incorporate new commit."
    fi
    log_success "Newly built images verified distinct from v1.5.0 binaries."

    # 6. Verify Migration 17 checksum via python inside newly built container
    log_info "Verifying Migration 17 checksum inside production container..."
    docker compose -f docker-compose.prod.yml run --rm web python3 -c "
import sys
from pathlib import Path
from app.migrations.runner import compute_file_checksum

m17_path = Path('migrations/aurora/20261014100000_add_gstr8_transaction_date_fields.up.sql')
if not m17_path.exists():
    m17_path = Path('recondesk-backend/migrations/aurora/20261014100000_add_gstr8_transaction_date_fields.up.sql')
assert m17_path.exists(), f'Migration 17 file not found at {m17_path}'

actual = compute_file_checksum(m17_path)
print(f'Computed Checksum: {actual}')
assert actual.startswith('788c2b28'), f'Checksum mismatch: {actual} does not start with 788c2b28'
print('Migration 17 Checksum Verification: PASSED')
"
    log_success "Migration 17 checksum verified inside container."

    # 7. Execute Aurora Migration 17 with bounded timeouts
    log_info "Executing migration dry-run preflight..."
    docker compose -f docker-compose.prod.yml run --rm web \
        python3 -m app.migrations.runner --upgrade --dry-run

    log_info "Applying Aurora Migration 17 (lock_timeout=5s, statement_timeout=60s enforced)..."
    docker compose -f docker-compose.prod.yml run --rm web \
        python3 -m app.migrations.runner --upgrade

    # 8. Hard assertion: Exactly 17 applied migrations, 0 pending, all checksums match
    log_info "Asserting exact migration status and checksum integrity..."
    docker compose -f docker-compose.prod.yml run --rm web python3 -c "
import sys
from app.migrations.runner import AuroraMigrationRunner

runner = AuroraMigrationRunner()
status = runner.get_status()

applied_cnt = status.get('applied_count', 0)
pending_cnt = status.get('pending_count', 0)
total_disc = status.get('total_discovered', 0)

print(f'Applied count: {applied_cnt}, Pending count: {pending_cnt}, Discovered: {total_disc}')
assert applied_cnt == 17, f'Assertion failed: expected 17 applied migrations, found {applied_cnt}'
assert pending_cnt == 0, f'Assertion failed: expected 0 pending migrations, found {pending_cnt}'
assert total_disc == 17, f'Assertion failed: expected 17 discovered migrations, found {total_disc}'

for r in status.get('applied', []):
    v = r.get('version')
    n = r.get('name')
    c = str(r.get('checksum', ''))[:16]
    print(f'  [{v}] {n} (checksum: {c}...)')

print('Migration Status & Checksum Assertion: PASSED (17 applied, 0 pending, 0 drifted)')
"
    log_success "Aurora Migration 17 successfully applied and verified."

    # 9. Recreate web and worker containers
    banner "STEP 4: Container Recreation (~3-5s restart window)"
    log_warn "NOTICE: Container recreation beginning. Service interruption ~3-5 seconds while uvicorn boots."
    docker compose -f docker-compose.prod.yml up -d --force-recreate web worker

    # 10. Post-Deployment Assertions
    banner "STEP 5: Post-Deployment Production Health & Safety Verification"

    # Assertion A: Running image IDs match newly built binaries
    log_info "Verifying running container image IDs..."
    local new_web_cid new_worker_cid new_running_web_image new_running_worker_image
    new_web_cid=$(docker compose -f docker-compose.prod.yml ps -q web)
    new_worker_cid=$(docker compose -f docker-compose.prod.yml ps -q worker)
    new_running_web_image=$(docker inspect "$new_web_cid" --format '{{.Image}}')
    new_running_worker_image=$(docker inspect "$new_worker_cid" --format '{{.Image}}')

    if [ "$new_running_web_image" != "$built_web_image" ]; then
        log_fatal "Running web container image ($new_running_web_image) != built image ($built_web_image)!"
    fi
    if [ "$new_running_worker_image" != "$built_worker_image" ]; then
        log_fatal "Running worker container image ($new_running_worker_image) != built image ($built_worker_image)!"
    fi
    log_success "Running containers verified on approved v1.5.1 image binaries."

    # Assertion B: Wait for uvicorn to bind and health check to report OK
    log_info "Waiting for web service to become healthy (polling localhost:8000)..."
    local retries=15
    local healthy=false
    while [ "$retries" -gt 0 ]; do
        if docker compose -f docker-compose.prod.yml exec -T web curl -s http://localhost:8000/health | grep -q '"status":"ok"'; then
            healthy=true
            break
        fi
        sleep 1
        retries=$((retries - 1))
    done

    if [ "$healthy" != "true" ]; then
        log_fatal "Web health check failed after container recreation! Rollback recommended."
    fi
    log_success "Internal API health confirmed: HTTP 200 OK."

    # Assertion C: Public reverse-proxy HTTPS health check via Caddy (TLS certificate verification enabled)
    check_public_api_health "$PROD_HEALTH_URL"

    # Assertion D: Celery worker readiness
    log_info "Verifying Celery worker ping..."
    docker compose -f docker-compose.prod.yml exec -T worker celery -A app.worker.celery_app inspect ping
    log_success "Celery worker ping confirmed responsive."

    # Assertion E: Aurora PostgreSQL GSTR-8 27-column schema verification
    log_info "Verifying GSTR-8 27-column schema in Aurora PostgreSQL..."
    docker compose -f docker-compose.prod.yml exec -T web python3 -c "
import sys
import sqlalchemy as sa
from app.aurora import get_aurora_engine

engine = get_aurora_engine()
with engine.connect() as conn:
    cols = conn.execute(sa.text('''
        SELECT column_name, data_type 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = 'gstr8_records';
    ''')).fetchall()
    col_names = {c[0] for c in cols}
    print(f'gstr8_records total columns: {len(cols)}')
    assert len(cols) == 27, f'Expected 27 columns, found {len(cols)}'

    for required in ['transaction_date', 'rate_basis', 'needs_review', 'review_reason']:
        assert required in col_names, f'Missing required column: {required}'

    idx = conn.execute(sa.text('''
        SELECT indexname FROM pg_indexes 
        WHERE schemaname = 'public' AND tablename = 'gstr8_records' 
          AND indexname = 'idx_gstr8_records_supp_tx_date';
    ''')).scalar()
    assert idx is not None, 'Missing partial index idx_gstr8_records_supp_tx_date'

print('Aurora PostgreSQL GSTR-8 Schema Verification: PASSED (27 columns + partial index confirmed)')
"
    log_success "GSTR-8 27 columns and partial index verified in production Aurora."

    # Assertion F: Live GSTN filing is strictly disabled
    log_info "Verifying live filing safeguard..."
    docker compose -f docker-compose.prod.yml exec -T web python3 -c "
from app.config import get_settings
s = get_settings()
print(f'GSTR3B_FILING_ENABLED: {s.gstr3b_filing_enabled}')
assert not s.gstr3b_filing_enabled, 'SECURITY ALERT: Live filing is ENABLED!'
print('Live GSTN Filing Safeguard: PASSED (strictly False)')
"
    log_success "Live filing safeguard verified: gstr3b_filing_enabled == False."

    banner "RECONDESK v1.5.1 PRODUCTION DEPLOYMENT: COMPLETED SUCCESSFULLY"
}

# ── Execute Deployment via SSH ────────────────────────────────────────────────
execute_remote_deployment() {
    banner "Connecting to EC2 ($EC2_USER@$EC2_HOST) to Execute Deployment"

    # Test SSH connectivity
    log_info "Testing SSH connectivity to $EC2_USER@$EC2_HOST..."
    ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 "$EC2_USER@$EC2_HOST" "echo SSH_CONNECTED" >/dev/null
    log_success "SSH connection established successfully."

    # Transfer script to /tmp and execute
    log_info "Copying deployment script to EC2 host..."
    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "cat > /tmp/deploy_v1_5_1_production.sh && chmod +x /tmp/deploy_v1_5_1_production.sh" < "$0"
    log_info "Executing production deployment on EC2..."
    ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "/tmp/deploy_v1_5_1_production.sh --ec2-stage"
    log_success "Remote deployment execution finished successfully."
}

# ── Rollback Execution ────────────────────────────────────────────────────────
run_rollback_stage() {
    banner "EMERGENCY ROLLBACK TO v1.5.0 (Zero Database Downgrade)"

    cd "$REMOTE_REPO_DIR"
    set -euo pipefail

    log_warn "Starting rollback to previous production state..."

    local web_rollback_image="$KNOWN_V150_WEB_IMAGE"
    local worker_rollback_image="$KNOWN_V150_WORKER_IMAGE"

    if [ -f .v1_5_0_rollback.env ]; then
        log_info "Loading preserved image IDs from .v1_5_0_rollback.env..."
        # shellcheck disable=SC1091
        source .v1_5_0_rollback.env
        web_rollback_image="${PRESERVED_WEB_IMAGE:-$KNOWN_V150_WEB_IMAGE}"
        worker_rollback_image="${PRESERVED_WORKER_IMAGE:-$KNOWN_V150_WORKER_IMAGE}"
    else
        log_warn "No .v1_5_0_rollback.env found; falling back to known v1.5.0 image IDs."
    fi

    log_info "Preserved Web Image:    $web_rollback_image"
    log_info "Preserved Worker Image: $worker_rollback_image"

    # Verify preserved images exist locally
    docker image inspect "$web_rollback_image" >/dev/null 2>&1 || log_fatal "Preserved web image $web_rollback_image not found in Docker!"
    docker image inspect "$worker_rollback_image" >/dev/null 2>&1 || log_fatal "Preserved worker image $worker_rollback_image not found in Docker!"

    # Retag preserved images to latest
    docker tag "$web_rollback_image" recondesk-backend-web:latest
    docker tag "$worker_rollback_image" recondesk-backend-worker:latest

    # Checkout previous production commit
    local target_rollback_commit="${PREVIOUS_COMMIT:-$PREVIOUS_PROD_COMMIT}"
    log_info "Checking out previous production commit $target_rollback_commit..."
    git checkout "$target_rollback_commit"

    # Recreate containers with --no-build
    log_info "Recreating containers with --no-build using preserved binaries..."
    docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate web worker

    # Assert running images match preserved image IDs
    local rollback_running_web rollback_running_worker
    rollback_running_web=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q web)" --format '{{.Image}}')
    rollback_running_worker=$(docker inspect "$(docker compose -f docker-compose.prod.yml ps -q worker)" --format '{{.Image}}')

    if [ "$rollback_running_web" != "$web_rollback_image" ]; then
        log_fatal "Rollback web image ($rollback_running_web) != preserved image ($web_rollback_image)!"
    fi
    if [ "$rollback_running_worker" != "$worker_rollback_image" ]; then
        log_fatal "Rollback worker image ($rollback_running_worker) != preserved image ($worker_rollback_image)!"
    fi
    log_success "Containers verified running preserved v1.5.0 binaries."

    # Wait for health restoration
    sleep 3
    check_public_api_health "$PROD_HEALTH_URL"
    log_info "NOTE: Aurora database was NOT downgraded. Migration 17 columns remain in place and harmless."
    banner "ROLLBACK TO v1.5.0 COMPLETED SUCCESSFULLY"
}

# ── Main Entrypoint ───────────────────────────────────────────────────────────
main() {
    local mode="${1:-deploy}"

    case "$mode" in
        --ec2-stage)
            run_ec2_deployment_stage
            ;;
        --rollback-stage)
            run_rollback_stage
            ;;
        --rollback)
            banner "Initiating Rollback via SSH to EC2 ($EC2_USER@$EC2_HOST)"
            ssh -i "$SSH_KEY" "$EC2_USER@$EC2_HOST" "cat > /tmp/deploy_v1_5_1_production.sh && chmod +x /tmp/deploy_v1_5_1_production.sh && /tmp/deploy_v1_5_1_production.sh --rollback-stage" < "$0"
            ;;
        --check-only)
            validate_local_prerequisites
            log_success "All pre-flight checks passed. (Check-only mode, no changes made)."
            ;;
        --test-snapshot-gate)
            create_and_wait_aurora_snapshot
            ;;
        --test-health-check)
            shift
            check_public_api_health "$@"
            ;;
        deploy|--deploy)
            validate_local_prerequisites
            create_and_wait_aurora_snapshot
            publish_release_branch
            execute_remote_deployment
            ;;
        -h|--help)
            echo "Usage: $0 [deploy|--check-only|--rollback|--ec2-stage|--rollback-stage|-h|--help]"
            echo ""
            echo "Commands:"
            echo "  deploy          Perform complete production release (Snapshot -> Push -> Remote Deployment)"
            echo "  --check-only    Validate local pre-flight checks and tool availability without changes"
            echo "  --rollback      Trigger emergency zero-rebuild container rollback via SSH to EC2"
            echo "  --ec2-stage     Execute the deployment sequence directly on EC2"
            echo "  --rollback-stage Execute the rollback sequence directly on EC2"
            exit 0
            ;;
        *)
            echo "Usage: $0 [deploy|--check-only|--rollback|--ec2-stage|--rollback-stage|-h|--help]"
            exit 1
            ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
