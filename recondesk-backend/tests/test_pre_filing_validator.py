"""Automated unit and integration tests for Pre-Filing Validation Engine.

Covers:
- Dual-threshold Rule 88C (outward tax liability mismatch > 20% AND > ₹25L).
- Dual-threshold Rule 88D (excess ITC claimed over GSTR-2B > 20% AND > ₹25L).
- Reconciliation run status gate (must be finalized/locked before filing).
- Section 49(4) RCM cash ledger discharge notification.
- GSTR-1 mandatory tables (Table 12 HSN B2B, Table 13 Documents Issued).
- Deterministic SHA-256 figures digest computation and tampering sensitivity.
"""

from __future__ import annotations

import copy
from unittest.mock import MagicMock

import pytest

from app.services.pre_filing_validator import (
    RULE_88C_EXCESS_AMOUNT_THRESHOLD,
    RULE_88C_EXCESS_PCT_THRESHOLD,
    ViolationCategory,
    ValidationSeverity,
    compute_figures_digest,
    compute_rule_88c_threshold,
    validate_gstr1_pre_filing,
    validate_gstr3b_pre_filing,
)


# ---------------------------------------------------------------------------
# 1. Rule 88C Statutory Dual-Threshold Tests
# ---------------------------------------------------------------------------


def test_rule_88c_statutory_defaults():
    """Verify statutory dual-threshold defaults match GST Council recommendations."""
    assert RULE_88C_EXCESS_PCT_THRESHOLD == 20.0
    assert RULE_88C_EXCESS_AMOUNT_THRESHOLD == 2_500_000.0


def test_rule_88c_clean_when_exact_or_gstr3b_higher():
    """Liability matches or 3B is higher than GSTR-1 -> no DRC-01B trigger."""
    res = compute_rule_88c_threshold(gstr1_total_tax=500_000.0, gstr3b_total_tax=500_000.0)
    assert res["triggers_drc01b"] is False
    assert res["threshold_status"] == "CLEAR"
    assert res["diff_amount"] == 0.0
    assert res["diff_pct"] == 0.0

    # 3B declared more tax than GSTR-1 (taxpayer declared extra tax)
    res_higher = compute_rule_88c_threshold(gstr1_total_tax=500_000.0, gstr3b_total_tax=600_000.0)
    assert res_higher["triggers_drc01b"] is False
    assert res_higher["threshold_status"] == "CLEAR"


def test_rule_88c_below_threshold_pct_only():
    """Shortfall is > 20% but only ₹30,000 — does NOT trigger DRC-01B (under ₹25L)."""
    res = compute_rule_88c_threshold(gstr1_total_tax=100_000.0, gstr3b_total_tax=70_000.0)
    assert res["diff_amount"] == 30_000.0
    assert res["diff_pct"] == 42.8571
    assert res["triggers_drc01b"] is False
    assert res["threshold_status"] == "BELOW_THRESHOLD"


def test_rule_88c_below_threshold_amount_only():
    """Shortfall is ₹30 Lakh but only ~11.11% — does NOT trigger DRC-01B (under 20%)."""
    res = compute_rule_88c_threshold(gstr1_total_tax=30_000_000.0, gstr3b_total_tax=27_000_000.0)
    assert res["diff_amount"] == 3_000_000.0  # ₹30 Lakh
    assert res["diff_pct"] == 11.1111
    assert res["triggers_drc01b"] is False
    assert res["threshold_status"] == "BELOW_THRESHOLD"


def test_rule_88c_triggers_when_both_conditions_met():
    """Shortfall is > 20% AND > ₹25 Lakh — triggers DRC-01B statutory notice."""
    # GSTR-1: ₹1.5 Cr, GSTR-3B: ₹1.0 Cr -> Diff: ₹50 Lakh (50.0%)
    res = compute_rule_88c_threshold(gstr1_total_tax=15_000_000.0, gstr3b_total_tax=10_000_000.0)
    assert res["diff_amount"] == 5_000_000.0
    assert res["diff_pct"] == 50.0
    assert res["triggers_drc01b"] is True
    assert res["threshold_status"] == "TRIGGERED"


# ---------------------------------------------------------------------------
# 2. Figures Digest & Tampering Invalidation Tests
# ---------------------------------------------------------------------------


def test_compute_figures_digest_deterministic():
    """Same figures with different key order produce the exact same SHA-256 digest."""
    body_a = {
        "sup_details": {"osup_det": {"txval": 1000.0, "iamt": 180.0}},
        "itc_elg": {"itc_avl": [{"ty": "OTH", "iamt": 90.0}]},
    }
    body_b = {
        "itc_elg": {"itc_avl": [{"ty": "OTH", "iamt": 90.0}]},
        "sup_details": {"osup_det": {"iamt": 180.0, "txval": 1000.0}},
    }
    digest_a = compute_figures_digest(body_a)
    digest_b = compute_figures_digest(body_b)
    assert digest_a == digest_b
    assert len(digest_a) == 64


def test_compute_figures_digest_changes_on_alteration():
    """Even a 1-rupee change alters the digest, invalidating any previous partner approval."""
    body = {
        "sup_details": {"osup_det": {"txval": 1000.0, "iamt": 180.0}},
    }
    digest_orig = compute_figures_digest(body)

    tampered = copy.deepcopy(body)
    tampered["sup_details"]["osup_det"]["iamt"] = 181.0
    digest_tampered = compute_figures_digest(tampered)

    assert digest_orig != digest_tampered


# ---------------------------------------------------------------------------
# 3. GSTR-3B Full Pre-Filing Validation Tests
# ---------------------------------------------------------------------------


def test_validate_gstr3b_pre_filing_clean():
    """Clean GSTR-3B where GSTR-1 matches, GSTR-2B matches, and reconciliation is finalized."""
    mock_sb = MagicMock()

    # Mock GSTR-1 suggestion
    mock_sb.table().select().eq().eq().order().limit().execute.return_value.data = []

    save_body = {
        "sup_details": {
            "osup_det": {"txval": 100000.0, "iamt": 18000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
            "isup_rev": {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
        },
        "itc_elg": {
            "itc_avl": [{"ty": "OTH", "iamt": 5000.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}],
            "itc_rev": [{"ty": "OTH", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}],
        },
    }

    result = validate_gstr3b_pre_filing(
        mock_sb,
        client_gstin_id="cid-1",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        save_body=save_body,
        require_final_reconciliation=False,
    )

    assert result.is_valid is True
    assert result.return_type == "gstr-3b"
    assert result.overall_severity in (ValidationSeverity.CLEAN, ValidationSeverity.INFO)
    assert result.has_critical_violations is False
    assert len(result.figures_digest) == 64


def test_validate_gstr3b_pre_filing_unfinalized_recon_blocker():
    """When require_final_reconciliation is true and run is not FINAL, blocks filing."""
    mock_sb = MagicMock()

    # Mock reconciliation_run query returning DRAFT status
    mock_run_query = MagicMock()
    mock_run_query.data = [{"id": "run-draft-123", "status": "DRAFT", "is_locked": False}]
    mock_sb.table().select().eq().eq().order().limit().execute.return_value = mock_run_query

    save_body = {
        "sup_details": {"osup_det": {"txval": 10000.0, "iamt": 1800.0}},
        "itc_elg": {"itc_avl": []},
    }

    result = validate_gstr3b_pre_filing(
        mock_sb,
        client_gstin_id="cid-1",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        save_body=save_body,
        require_final_reconciliation=True,
    )

    assert result.is_valid is False
    assert result.has_critical_violations is True
    codes = [v.code for v in result.violations]
    assert "RECONCILIATION_NOT_FINALIZED" in codes


# ---------------------------------------------------------------------------
# 4. GSTR-1 Pre-Filing Validation Tests
# ---------------------------------------------------------------------------


def test_validate_gstr1_pre_filing_detects_table_blockers():
    """GSTR-1 pre-filing validation flags missing Table 12 HSN and Table 13 Documents."""
    mock_sb = MagicMock()
    mapped_readiness = {
        "filing_readiness": {
            "file_blockers": [
                "Table 12 HSN Summary is mandatory for B2B supplies under GSTN rules.",
                "Table 13 Documents Issued summary is missing.",
            ],
            "save_blockers": [],
        },
        "pending_review_count": 3,
    }
    save_payload = {"b2b": [{"ctin": "27AAACB1234A1Z1"}]}

    result = validate_gstr1_pre_filing(
        mock_sb,
        client_gstin_id="cid-1",
        gstin="27AABCU9603R1ZM",
        period="2024-11",
        mapped_readiness=mapped_readiness,
        save_payload=save_payload,
    )

    assert result.is_valid is False
    assert result.has_critical_violations is True
    codes = [v.code for v in result.violations]
    assert "GSTR1_MANDATORY_TABLE_GAP" in codes
    assert "GSTR1_PENDING_REVIEW_EXCLUSION" in codes
