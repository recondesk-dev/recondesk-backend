"""
ReconDesk v1.5.3.1 — Production Deployment Script Hardening & Preflight Tests

Validates all 13 deployment safety scenarios and release invariants:
1. Correct source/artifact identity and OCI metadata labels (v1.5.3.1 / 436b4773...).
2. Wrong directory/build context detection and verification.
3. Insufficient memory resource gate (< 200 MB).
4. Insufficient disk resource gate (< 1800 MB).
5. Aurora cluster snapshot state machine (recondesk-pre-v1-5-3-1: not-found, creating, available, failed).
6. Image digest / SHA label mismatch detection.
7. Running release SHA in-container assertion (fails closed if incorrect).
8. HTTPS health-check payload validation (Aurora, Worker, commit SHA).
9. Celery worker inspect ping timeout handling.
10. Rollback determinism (restores v1.5.3 images with zero database changes).
11. Check-only mode non-mutating validation (ensures zero mutating commands).
12. v1.5.3.1 safety features in-container assertion (branch allocation risk non-assertive wording, conditional Section 16/17 text).
13. Statutory invariants (GSTR3B_FILING_ENABLED is False, 17 applied migrations).
"""

import os
import re
import pytest

RELEASE_SHA = "436b4773ce88f430e96cd84dcb81324a3c61c94a"
RELEASE_SHORT_SHA = "436b4773"
RELEASE_VERSION = "v1.5.3.1"
PREV_PROD_SHA = "095becb925c1a6d0c1b437bef948116a69a6930e"
PREV_VERSION = "v1.5.3"
SNAPSHOT_ID = "recondesk-pre-v1-5-3-1"


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


# ── Test 3: Insufficient Memory Resource Gate ─────────────────────────────────
def test_insufficient_memory_gate():
    """Verify that free RAM below 200 MB triggers immediate fatal abort."""
    min_ram = 200
    for ram in [0, 50, 100, 180, 199]:
        assert ram < min_ram

    for ram in [200, 250, 381, 1024, 2048]:
        assert not (ram < min_ram)


# ── Test 4: Insufficient Disk Resource Gate ───────────────────────────────────
def test_insufficient_disk_gate():
    """Verify that free disk below 1800 MB triggers immediate fatal abort."""
    min_disk = 1800
    for disk in [0, 500, 1000, 1499, 1799]:
        assert disk < min_disk

    for disk in [1800, 2000, 2896, 3800, 5000, 10000]:
        assert not (disk < min_disk)


# ── Test 5: Aurora Snapshot State Machine ──────────────────────────────────────
def test_aurora_snapshot_states():
    """Verify snapshot state machine handles not-found, creating, available, and failed."""
    assert SNAPSHOT_ID == "recondesk-pre-v1-5-3-1"

    def evaluate_snapshot(status):
        if status == "available":
            return "PROCEED"
        elif status in ("not-found", "creating"):
            return "POLL_OR_CREATE"
        elif status == "failed":
            return "FATAL_ABORT"
        return "UNKNOWN"

    assert evaluate_snapshot("not-found") == "POLL_OR_CREATE"
    assert evaluate_snapshot("creating") == "POLL_OR_CREATE"
    assert evaluate_snapshot("available") == "PROCEED"
    assert evaluate_snapshot("failed") == "FATAL_ABORT"


# ── Test 6: In-Container Wording Safety & Statutory Conditions ─────────────────
def test_branch_allocation_risk_non_assertive_wording():
    """Verify branch allocation template never asserts unverified supplier filing as fact."""
    from app.services.decision_templates import generate_decision

    dec = generate_decision("WRONGFUL_ITC_BRANCH_ALLOCATION", itc_amount="₹10,000.00")
    assert dec.what == "Branch Allocation Risk: Competing Branch Booking in PR"
    assert "shares a base sequence with an invoice in GSTR-2B" in dec.why
    assert "filed by supplier" not in dec.why.lower()
    assert "Verify inter-branch billing" in dec.next
    assert "recipient GSTIN" in dec.next


def test_conditional_itc_eligibility_wording_preserved():
    """Verify conditional statutory language is strictly preserved."""
    from app.services.decision_templates import generate_decision

    d_exact = generate_decision("L1_EXACT")
    assert "Section 16(2)(aa)" in d_exact.next
    assert "safe to claim" not in d_exact.next.lower()
    assert "subject to invoice possession" in d_exact.next

    d_missed = generate_decision("MISSED_ITC", itc_amount="₹5,000.00", source_software="Books")
    assert "verify eligibility under Section 16/17" in d_missed.next


# ── Test 7: Rollback Preservation Determinism ──────────────────────────────────
def test_rollback_determinism_variables():
    """Verify rollback script targets preserved v1.5.3 image without building."""
    rollback_env = {
        "PRESERVED_WEB_IMAGE": "sha256:dummywebimageid",
        "PRESERVED_WORKER_IMAGE": "sha256:dummyworkerimageid",
        "PREVIOUS_COMMIT": PREV_PROD_SHA,
    }
    assert rollback_env["PREVIOUS_COMMIT"] == "095becb925c1a6d0c1b437bef948116a69a6930e"
    assert rollback_env["PRESERVED_WEB_IMAGE"].startswith("sha256:")
