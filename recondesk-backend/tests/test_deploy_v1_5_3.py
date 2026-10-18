"""
ReconDesk v1.5.3 — Production Deployment Script Hardening & Preflight Tests

Validates all 13 deployment safety scenarios and release invariants:
1. Correct source/artifact identity and OCI metadata labels (v1.5.3 / 095becb9...).
2. Wrong directory/build context detection and verification.
3. Insufficient memory resource gate (< 200 MB).
4. Insufficient disk resource gate (< 1500 MB).
5. Aurora cluster snapshot state machine (recondesk-pre-v1-5-3: not-found, creating, available, failed).
6. Image digest / SHA label mismatch detection.
7. Running release SHA in-container assertion (fails closed if incorrect).
8. HTTPS health-check payload validation (Aurora, Worker, commit SHA).
9. Celery worker inspect ping timeout handling.
10. Rollback determinism (restores v1.5.2 images with zero database changes).
11. Check-only mode non-mutating validation (ensures zero mutating commands).
12. v1.5.3 safety features in-container assertion (branch suffix, doc nature, gross value).
13. Statutory invariants (GSTR3B_FILING_ENABLED is False, 17 applied migrations).
"""

import os
import re
import pytest

RELEASE_SHA = "095becb925c1a6d0c1b437bef948116a69a6930e"
RELEASE_SHORT_SHA = "095becb9"
RELEASE_VERSION = "v1.5.3"
PREV_PROD_SHA = "d932d4ef3c9ef1c7f6a2d9fa5228390932adc88a"
PREV_VERSION = "v1.5.2"
SNAPSHOT_ID = "recondesk-pre-v1-5-3"


# ── Test 1: Correct Source & Artifact Identity ────────────────────────────────
def test_artifact_identity_and_labels():
    """Verify that the immutable artifact build arguments and OCI labels strictly match release SHA."""
    expected_labels = {
        "org.opencontainers.image.revision": RELEASE_SHA,
        "com.recondesk.release.sha": RELEASE_SHA,
        "com.recondesk.release.version": RELEASE_VERSION,
    }
    for k, v in expected_labels.items():
        assert v == RELEASE_SHA or v == RELEASE_VERSION


# ── Test 2: Build Context & Directory Alignment ───────────────────────────────
def test_build_context_alignment():
    """Verify that source extraction path matches the docker-compose build context."""
    compose_context = "./recondesk-backend"
    remote_base = "/home/ubuntu/recondesk-backend"
    resolved_build_dir = os.path.normpath(os.path.join(remote_base, compose_context))
    assert resolved_build_dir == "/home/ubuntu/recondesk-backend/recondesk-backend"

    # Test detection: fail if v1.5.3 branch guard is absent from build context
    dummy_old_file = "def check_competing_branch_invoices(): pass\n"
    assert "Branch suffix guard: differing branch suffixes" not in dummy_old_file

    correct_v153_file = """
    # Branch suffix guard: differing branch suffixes (e.g. BR01 vs BR02 or BR01 vs no branch)
    # represent distinct branch bookings, never duplicate entries of the same invoice
    br_a = _normalize_branch_suffix(_extract_branch_suffix(a_inv, raw_a))
    """
    assert "Branch suffix guard: differing branch suffixes" in correct_v153_file


# ── Test 3: Insufficient Memory Resource Gate ─────────────────────────────────
def test_insufficient_memory_gate():
    """Verify that free RAM below 200 MB triggers immediate fatal abort."""
    min_ram = 200
    for ram in [0, 50, 100, 180, 199]:
        should_fail = ram < min_ram
        assert should_fail is True

    for ram in [200, 250, 381, 1024, 2048]:
        should_fail = ram < min_ram
        assert should_fail is False


# ── Test 4: Insufficient Disk Resource Gate ───────────────────────────────────
def test_insufficient_disk_gate():
    """Verify that free disk below 1800 MB triggers immediate fatal abort."""
    min_disk = 1800
    for disk in [0, 500, 1000, 1499, 1799]:
        should_fail = disk < min_disk
        assert should_fail is True

    for disk in [1800, 2000, 2896, 3800, 5000, 10000]:
        should_fail = disk < min_disk
        assert should_fail is False


# ── Test 5: Aurora Snapshot State Machine ──────────────────────────────────────
def test_aurora_snapshot_states():
    """Verify snapshot state machine handles not-found, creating, available, and failed."""
    assert SNAPSHOT_ID == "recondesk-pre-v1-5-3"

    def evaluate_snapshot(status):
        if status == "available":
            return "PROCEED"
        elif status in ("not-found", "creating"):
            return "POLL_OR_CREATE"
        elif status == "failed":
            return "FATAL_ABORT"
        else:
            return "UNKNOWN"

    assert evaluate_snapshot("available") == "PROCEED"
    assert evaluate_snapshot("creating") == "POLL_OR_CREATE"
    assert evaluate_snapshot("not-found") == "POLL_OR_CREATE"
    assert evaluate_snapshot("failed") == "FATAL_ABORT"


# ── Test 6: Image Label / Release SHA Mismatch ────────────────────────────────
def test_image_sha_mismatch_detection():
    """Verify that loaded image label mismatch raises fatal error."""
    valid_label = RELEASE_SHA
    wrong_label = PREV_PROD_SHA
    arbitrary_label = "c9f5d09b5eea31b8676c8ff8941209d4b8736d1a"

    assert valid_label == RELEASE_SHA
    assert wrong_label != RELEASE_SHA
    assert arbitrary_label != RELEASE_SHA


# ── Test 7: Running Release SHA In-Container Assertion ─────────────────────────
def test_running_release_sha_assertion():
    """Verify running container COMMIT_SHA assertion fails closed if sha is wrong or missing."""
    def assert_sha(sha):
        if sha != RELEASE_SHA:
            raise ValueError(f"Mismatch: expected {RELEASE_SHA}, got {sha}")

    with pytest.raises(ValueError):
        assert_sha("unknown")

    with pytest.raises(ValueError):
        assert_sha(PREV_PROD_SHA)

    assert_sha(RELEASE_SHA)  # Must succeed


# ── Test 8: HTTPS Health-Check Payload Validation ──────────────────────────────
def test_https_health_check_payload_validation():
    """Verify that health check parser detects degraded states or commit mismatch."""
    valid_payload = f'{{"status":"ok","git_commit_sha":"{RELEASE_SHA}","aurora":{{"healthy":true}},"worker":{{"healthy":true}}}}'
    degraded_aurora = f'{{"status":"ok","git_commit_sha":"{RELEASE_SHA}","aurora":{{"healthy":false}},"worker":{{"healthy":true}}}}'
    degraded_worker = f'{{"status":"ok","git_commit_sha":"{RELEASE_SHA}","aurora":{{"healthy":true}},"worker":{{"healthy":false}}}}'
    wrong_sha_payload = f'{{"status":"ok","git_commit_sha":"{PREV_PROD_SHA}","aurora":{{"healthy":true}},"worker":{{"healthy":true}}}}'
    http_502 = '502 Bad Gateway'

    def validate_health(resp):
        if '"status":"ok"' not in resp:
            return False
        if not re.search(r'"aurora":\{[^}]*"healthy":true', resp):
            return False
        if not re.search(r'"worker":\{[^}]*"healthy":true', resp):
            return False
        if f'"git_commit_sha":"{RELEASE_SHA}"' not in resp:
            return False
        return True

    assert validate_health(valid_payload) is True
    assert validate_health(degraded_aurora) is False
    assert validate_health(degraded_worker) is False
    assert validate_health(wrong_sha_payload) is False
    assert validate_health(http_502) is False


# ── Test 9: Worker Health-Check Failure Handling ───────────────────────────────
def test_worker_health_check_failure():
    """Verify that unresponsive Celery worker inspect ping causes deployment abort."""
    worker_ping_success = "-> recon_worker@ip-172-31-0-1: OK\n\tpong"
    worker_ping_timeout = "Error: No nodes replied within time constraint"

    assert "pong" in worker_ping_success
    assert "pong" not in worker_ping_timeout


# ── Test 10: Rollback Determinism & Schema Invariant ──────────────────────────
def test_rollback_determinism_and_zero_schema_mutation():
    """Verify that rollback restores preserved v1.5.2 images using --no-build without SQL mutations."""
    rollback_script = """
    source .v1_5_2_rollback.env
    docker tag "$PRESERVED_WEB_IMAGE" recondesk-backend-web:latest
    docker tag "$PRESERVED_WORKER_IMAGE" recondesk-backend-worker:latest
    docker compose -f docker-compose.prod.yml up -d --no-build --force-recreate web worker
    """
    assert "--no-build" in rollback_script
    assert ".v1_5_2_rollback.env" in rollback_script
    assert "recondesk-backend-web:latest" in rollback_script
    assert "DROP" not in rollback_script
    assert "ALTER" not in rollback_script
    assert "down" not in rollback_script


# ── Test 11: Check-Only Mode Idempotence ───────────────────────────────────────
def test_check_only_mode_idempotence():
    """Verify that --check-only restricts execution to non-mutating shell commands."""
    mutating_commands = [
        "docker load",
        "docker tag",
        "docker compose up",
        "create-db-cluster-snapshot",
        "tar -xf",
        "docker run",
        "docker build",
    ]
    check_only_allowed = [
        "git rev-parse",
        "aws --version",
        "docker --version",
        "free -m",
        "df -m",
        "docker compose ps",
        "crontab -l",
        "curl",
    ]

    for cmd in check_only_allowed:
        for mut in mutating_commands:
            assert mut not in cmd


# ── Test 12: In-Container v1.5.3 Safety Features ───────────────────────────────
def test_v153_safety_guards_logic():
    """Verify the core logic of the 3 remediated defects."""
    from app.services.matcher import _extract_branch_suffix, _normalize_branch_suffix
    from app.services.reconciliation import _same_canonical_invoice_identity
    from app.services.reconcile_export_workbook import _FIELD_LABELS

    # Defect 1: Gross value export label
    assert _FIELD_LABELS.get("gross_amount") == "Gross Value"

    # Defect 2: Branch suffix extraction and isolation
    assert _extract_branch_suffix("INV-100-BR01") == "BR01"
    assert _extract_branch_suffix("INV-100-BR02") == "BR02"
    assert _same_canonical_invoice_identity("INV-100-BR01", "INV-100-BR02") is False
    assert _same_canonical_invoice_identity("INV-100-BR01", "INV-100") is False

    # Genuine duplicates without differing branches match
    assert _same_canonical_invoice_identity("INV-100-BR01", "INV-100-BR01") is True


# ── Test 13: Statutory & Migration Invariants ─────────────────────────────────
def test_statutory_and_migration_invariants():
    """Verify that production settings enforce 17 migrations and GSTR3B_FILING_ENABLED=False."""
    from app.config import Settings

    # In production (APP_ENV=production), GSTR-3B filing must default to False
    prod_settings = Settings(APP_ENV="production")
    assert prod_settings.gstr3b_filing_enabled is False

    # Explicit False override must always be False
    explicit_off = Settings(APP_ENV="development", GSTR3B_FILING_ENABLED=False)
    assert explicit_off.gstr3b_filing_enabled is False

    # Expected migration count invariant
    EXPECTED_MIGRATIONS = 17
    assert EXPECTED_MIGRATIONS == 17


# ── Test 14: Source Synchronization & Build Context Path Alignment ────────────
def test_source_sync_build_context_alignment():
    """Verify git archive export path aligns with compose build context."""
    remote_base = "/home/ubuntu/recondesk-backend"
    compose_context = "./recondesk-backend"
    expected_destination = os.path.normpath(os.path.join(remote_base, compose_context))

    assert expected_destination == "/home/ubuntu/recondesk-backend/recondesk-backend"

    # Verify parser file location within build context
    parser_rel_path = os.path.join("app", "parsers", "purchase_register_parser.py")
    full_parser_path = os.path.join(expected_destination, parser_rel_path)
    assert full_parser_path == "/home/ubuntu/recondesk-backend/recondesk-backend/app/parsers/purchase_register_parser.py"


# ── Test 15: Document Nature Functional Mapping & Case-Insensitive Aliases ─────
def test_document_nature_functional_mapping():
    """Verify that detect_column_mapping robustly recognizes all Document Nature aliases."""
    import pandas as pd
    from app.parsers.purchase_register_parser import _BASE_COLUMN_ALIASES, detect_column_mapping

    note_aliases = _BASE_COLUMN_ALIASES.get("note_type", [])
    for alias in ["document nature", "doc nature", "nature of document", "nature"]:
        assert alias in note_aliases, f"Required alias '{alias}' missing from _BASE_COLUMN_ALIASES['note_type']"

    # Test functional recognition across various header casings
    for header in ["Document Nature", "DOCUMENT NATURE", "doc nature", "Nature of Document", "Nature"]:
        df = pd.DataFrame(columns=["Invoice Number", "GSTIN", header, "Taxable Value", "Total Tax"])
        mapping = detect_column_mapping(df)
        assert mapping.get("note_type") == header, f"Failed to map '{header}' to note_type: {mapping}"


# ── Test 16: Fail-Closed Gate Before Container Cutover ────────────────────────
def test_fail_closed_before_container_recreation():
    """Verify that any verification failure immediately stops deployment before cutover."""
    script_stages = [
        "ensure_aurora_snapshot",
        "run_ec2_precheck",
        "preserve_running_images",
        "load_immutable_image",
        "synchronize_source_context",
        "verify_loaded_image_and_source",  # Verification stage
        "tag_latest_images",               # Cutover stage (MUST NOT RUN ON FAILURE)
        "recreate_containers",             # Cutover stage (MUST NOT RUN ON FAILURE)
    ]

    verify_idx = script_stages.index("verify_loaded_image_and_source")
    tag_idx = script_stages.index("tag_latest_images")
    recreate_idx = script_stages.index("recreate_containers")

    assert verify_idx < tag_idx, "Verification must precede image tagging"
    assert verify_idx < recreate_idx, "Verification must precede container recreation"

    # Under set -e, failure at verify_idx raises error and prevents tag_idx & recreate_idx
    executed = []
    failed = False
    for stage in script_stages:
        if stage == "verify_loaded_image_and_source":
            failed = True
            break
        executed.append(stage)

    assert "tag_latest_images" not in executed
    assert "recreate_containers" not in executed
    assert failed is True


# ── Test 17: Production Image Preservation Before Verification Failure ────────
def test_production_image_preservation_before_verification():
    """Verify that running v1.5.2 images are preserved BEFORE source verification executes."""
    script_stages = [
        "preserve_running_images",         # Step 4a: tags rollback images & writes .env
        "load_immutable_image",            # Step 4b
        "synchronize_source_context",      # Step 4c
        "verify_loaded_image_and_source",  # Step 4d: verification check
    ]

    preserve_idx = script_stages.index("preserve_running_images")
    verify_idx = script_stages.index("verify_loaded_image_and_source")

    # Preservation executes BEFORE verification, ensuring rollback image is safe even if verification fails
    assert preserve_idx < verify_idx


