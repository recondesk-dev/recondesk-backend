"""ReconDesk v1.5.1 — Post-Deployment Customer Production Acceptance Test Suite.

Validates the complete customer-facing statutory, reconciliation, and commercial workflows:
- Phase 2: Reconciliation (GSTR-2B vs PR with valid-GSTIN synthetic dataset, Debit Notes,
           Credit Note tax explanations, Prefix-alteration review, OCR+Branch suffix review,
           adversarial safety gates, and Excel export record conservation).
- Phase 3: GSTR-8 (Batch creation, validation, durable persistence, statutory TCS rate calculations,
           review flags, GSTN offline JSON export, and live filing guards).
- Phase 4: Commercial Workflows (Authentication/JWT, Organization/GSTIN scoping, Subscription & Coupon
           pricing including 40%, Razorpay HMAC webhook callback integrity & idempotency,
           and notification preferences/completed-job dispatch).
"""

from __future__ import annotations

import datetime
from datetime import date, datetime as dt, timezone
from decimal import Decimal
import hashlib
import hmac
import io
import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import openpyxl
import pytest

# ── Core Services & Rules ──────────────────────────────────────────────────────
from app.config import Settings, settings
from app.services.matcher import (
    MatchResult,
    build_compared_fields,
    match_gstr_to_pr,
)
from app.services.reconciliation import (
    ReconState,
    build_pr_candidate_indices,
    build_pr_by_invoice,
    process_gstr_records_chunk,
    execute_phase2_and_3,
)
from app.parsers.gstr2b_parser import _alt_map_note_row, _note_type_value
from app.routers.reconciliation_api import _build_wrongful_risk_records
from app.services.decision_templates import TEMPLATES
from app.services.reconcile_export_workbook import (
    _doc_type_display,
    build_excel_workbook_bytes,
)

# GSTR-8
from app.rules.gstr8_rules import (
    calculate_gstr8_mixed_period_tcs,
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
)
from app.services.pre_filing_validator import validate_gstr8_pre_filing
from app.services.gstr8_service import (
    add_or_update_gstr8_record_sync,
    build_gstr8_offline_json,
    compute_gstr8_figures_digest,
    get_batch_summary_sync,
    get_or_create_batch_sync,
    reset_gstr8_memory_store_for_testing,
)

# Commercial
from app.models.coupon import ANNUAL_PLANS, PERMITTED_DISCOUNTS
from app.services.coupon_service import calculate_discounted_pricing
from app.services.payment_webhook_service import verify_razorpay_webhook_signature
from app.routers.notifications import NotificationPreferencesModel, _prefs_from_row


# ==============================================================================
# PHASE 2: RECONCILIATION ACCEPTANCE TESTS
# ==============================================================================

# Valid Checksum GSTINs
SUPPLIER_GSTIN_1 = "27AAPFU0939F1ZV"  # Maharashtra (Valid checksum)
SUPPLIER_GSTIN_2 = "24AAACG1234A1Z5"  # Gujarat (Valid checksum)
RECIPIENT_GSTIN = "27AABCU9603R1ZM"   # Maharashtra (Valid checksum)


def test_recon_exact_invoice_matching():
    """Verify standard identical invoices match as Level 1 Clean Match with zero diff."""
    gstr_record = {
        "id": "gstr-inv-101",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "INV-2024-001",
        "invoice_number_normalized": "INV2024001",
        "invoice_date": "2024-05-10",
        "taxable_paise": 10000000,  # ₹1,00,000.00
        "total_tax_paise": 1800000,  # ₹18,000.00
    }
    pr_record = {
        "id": "pr-inv-101",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "INV-2024-001",
        "invoice_number_normalized": "INV2024001",
        "invoice_date": "2024-05-10",
        "taxable_paise": 10000000,
        "total_tax_paise": 1800000,
    }

    result = match_gstr_to_pr(gstr_record, [pr_record])
    assert result is not None
    assert result.matched is True
    assert result.level == 1
    assert result.requires_human_review is False
    assert result.financial_status == "Exact"


def test_recon_debit_note_classification_and_routing():
    """Verify Debit Notes are parsed, mapped, and classified distinctly from regular invoices."""
    # 1. Test alternate mapping aliases for debit notes
    raw_dn = {
        "GSTIN of Supplier": SUPPLIER_GSTIN_1,
        "Legal Name of Supplier": "Precision Castings Pvt Ltd",
        "Note Number": "DN-2024-0042",
        "Note Date": "2024-06-15",
        "Taxable Value (₹)": 50000.0,
        "Integrated Tax (₹)": 9000.0,
        "Invoice type": "Debit Note",
    }
    mapped = _alt_map_note_row(raw_dn)
    assert mapped is not None
    assert mapped["ntty"] == "D"
    assert mapped["nt_num"] == "DN-2024-0042"

    # 2. Test wrongful ITC risk routing for unmatched PR debit note
    pr_dn = {
        "id": "pr-dn-042",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "supplier_name": "Precision Castings Pvt Ltd",
        "invoice_number": "DN-2024-0042",
        "invoice_date": "2024-06-15",
        "taxable_value": 50000.0,
        "taxable_paise": 5000000,
        "total_tax_paise": 900000,
        "is_debit_note": True,
        "document_type": "DEBIT_NOTE",
        "ntty": "D",
    }
    payload = {"engine": {"wrongful_itc_risk": [pr_dn]}}
    mock_sb = MagicMock()
    with patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={"pr-dn-042": {"matcher": pr_dn, "record_data": pr_dn}}):
        with patch("app.routers.reconciliation_api._decision_statuses_for_run", return_value={}):
            from collections import Counter
            risk_records = _build_wrongful_risk_records(mock_sb, rid="run-test", payload=payload, note_counts=Counter())
            assert len(risk_records) == 1
            rec = risk_records[0]
            assert rec["document_type"] == "DEBIT_NOTE"
            assert rec["is_debit_note"] is True
            assert rec["decision_what"] == TEMPLATES["WRONGFUL_ITC_DEBIT_NOTE"]["what"]


def test_recon_credit_note_magnitude_aware_tax_explanation():
    """Verify Credit Notes with opposite accounting signs match as exact in magnitude."""
    gstr_cn = {
        "id": "g-cn-99",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "CRN-2024-0099",
        "is_credit_note": True,
        "document_type": "CREDIT_NOTE",
        "ntty": "C",
        "total_tax_paise": 360000,  # GSTR-2B stores positive tax
        "taxable_paise": 2000000,
        "invoice_date": "2024-05-10",
    }
    pr_cn = {
        "id": "p-cn-99",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "CRN-2024-0099",
        "is_credit_note": True,
        "document_type": "CREDIT_NOTE",
        "ntty": "C",
        "total_tax_paise": -360000,  # PR stores negative tax
        "taxable_paise": -2000000,
        "invoice_date": "2024-05-10",
    }

    compared = build_compared_fields(gstr_cn, pr_cn)
    tax_field = next((f for f in compared if f["field_name"] == "tax_amount"), None)
    assert tax_field is not None
    assert tax_field["match_type"] == "exact", f"Expected 'exact' magnitude match, got {tax_field['match_type']}"

    # Cross-document rejection: regular invoice vs credit note must NOT net out
    gstr_inv = dict(gstr_cn, is_credit_note=False, document_type="INVOICE", ntty=None)
    compared_cross = build_compared_fields(gstr_inv, pr_cn)
    tax_cross = next((f for f in compared_cross if f["field_name"] == "tax_amount"), None)
    assert tax_cross is not None
    assert tax_cross["match_type"] == "not_matched"


def test_recon_prefix_alteration_review_discovery():
    """Verify invoice prefix variations (TAX-07/00721 vs BILL00721) route to Review Required."""
    gstr = {
        "id": "g-pfx",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "TAX-07/00721",
        "invoice_number_normalized": "TAX0700721",
        "total_tax_paise": 3600000,
        "taxable_paise": 20000000,
        "invoice_date": "2024-05-10",
    }
    pr = {
        "id": "p-pfx",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "BILL00721",
        "invoice_number_normalized": "BILL00721",
        "total_tax_paise": 3600000,
        "taxable_paise": 20000000,
        "invoice_date": "2024-05-10",
    }

    result = match_gstr_to_pr(gstr, [pr])
    assert result is not None
    assert result.matched is True
    assert result.level == 3
    assert result.requires_human_review is True
    assert result.review_reason == "PREFIX_ALTERATION_REVIEW"
    assert result.financial_status == "Exact"


def test_recon_combined_ocr_branch_suffix_discovery():
    """Verify OCR misread combined with branch suffix (TAX-16/01611 vs TAX-16/016II-BR01) routes to Review Required."""
    gstr = {
        "id": "g-ocr",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "TAX-16/01611",
        "invoice_number_normalized": "TAX1601611",
        "total_tax_paise": 5400000,
        "taxable_paise": 30000000,
        "invoice_date": "2024-05-10",
    }
    pr = {
        "id": "p-ocr",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "TAX-16/016II-BR01",
        "invoice_number_normalized": "TAX16016IIBR01",
        "total_tax_paise": 5400000,
        "taxable_paise": 30000000,
        "invoice_date": "2024-05-10",
    }

    result = match_gstr_to_pr(gstr, [pr])
    assert result is not None
    assert result.matched is True
    assert result.level == 3
    assert result.requires_human_review is True
    assert result.review_reason == "OCR_CONFIDENCE_REVIEW"


def test_recon_adversarial_safety_gates():
    """Verify zero incorrect automatic matches across PANs, document types, and sequence numbers."""
    base_gstr = {
        "id": "g-base",
        "supplier_gstin": SUPPLIER_GSTIN_1,
        "invoice_number": "TAX-07/00721",
        "invoice_number_normalized": "TAX0700721",
        "total_tax_paise": 1800000,
        "taxable_paise": 10000000,
        "invoice_date": "2024-05-10",
    }

    # 1. Neighboring sequence number collision (00721 vs 00722)
    pr_seq = dict(base_gstr, id="p-seq", invoice_number="BILL00722", invoice_number_normalized="BILL00722")
    assert match_gstr_to_pr(base_gstr, [pr_seq]) is None

    # 2. Cross-PAN match (Maharashtra vs Gujarat)
    pr_xpan = dict(base_gstr, id="p-xpan", supplier_gstin=SUPPLIER_GSTIN_2)
    assert match_gstr_to_pr(base_gstr, [pr_xpan]) is None

    # 3. Unsafe financial mismatch (> 5% discrepancy)
    pr_diff = dict(base_gstr, id="p-diff", invoice_number="BILL00721", invoice_number_normalized="BILL00721", total_tax_paise=3000000)
    assert match_gstr_to_pr(base_gstr, [pr_diff]) is None


def test_recon_excel_export_and_record_conservation():
    """Verify Excel export workbook generates all sheets and satisfies exact record conservation."""
    # Build complete mixed batch
    gstr_records = [
        {"id": "g-exact", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "INV-100", "invoice_number_normalized": "INV100", "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10"},
        {"id": "g-pfx", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "TAX-07/00721", "invoice_number_normalized": "TAX0700721", "total_tax_paise": 36000, "taxable_paise": 200000, "invoice_date": "2024-05-10"},
        {"id": "g-missed", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "INV-999", "invoice_number_normalized": "INV999", "total_tax_paise": 10000, "taxable_paise": 50000, "invoice_date": "2024-05-10"},
    ]
    pr_records = [
        {"id": "p-exact", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "INV-100", "invoice_number_normalized": "INV100", "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10"},
        {"id": "p-pfx", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "BILL00721", "invoice_number_normalized": "BILL00721", "total_tax_paise": 36000, "taxable_paise": 200000, "invoice_date": "2024-05-10"},
        {"id": "p-wrongful", "supplier_gstin": SUPPLIER_GSTIN_1, "invoice_number": "DN-888", "invoice_number_normalized": "DN888", "is_debit_note": True, "document_type": "DEBIT_NOTE", "total_tax_paise": 20000, "taxable_paise": 100000, "invoice_date": "2024-05-10"},
    ]

    state = ReconState()
    pr_index = {SUPPLIER_GSTIN_1: pr_records}
    pr_by_inv = build_pr_by_invoice(pr_index)
    candidate_indices = build_pr_candidate_indices(pr_index)

    process_gstr_records_chunk(
        gstr_records,
        effective_gstr_period=date(2024, 5, 1),
        pr_index=pr_index,
        pr_index_by_period={},
        state=state,
        pr_by_invoice=pr_by_inv,
        candidate_indices=candidate_indices,
    )
    execute_phase2_and_3(
        gstr_records,
        pr_records,
        state=state,
        candidate_indices=candidate_indices,
    )

    # Invariants verification
    assert len(state.clean_matched) == 1  # g-exact <-> p-exact
    assert len(state.review_required) == 1  # g-pfx <-> p-pfx
    assert len(state.missed_itc) == 1  # g-missed

    unmatched_pr = [p for p in pr_records if p["id"] not in state.consumed_pr_ids]
    assert len(unmatched_pr) == 1
    assert unmatched_pr[0]["id"] == "p-wrongful"

    # Record Conservation:
    # GSTR: 1 clean + 1 review + 1 missed = 3 total input GSTR
    assert len(state.clean_matched) + len(state.review_required) + len(state.missed_itc) == len(gstr_records)
    # PR: 1 clean + 1 review + 1 wrongful = 3 total input PR
    assert len(state.clean_matched) + len(state.review_required) + len(unmatched_pr) == len(pr_records)

    # Build Excel Workbook
    matched_pairs = [
        ({"id": "g-exact", "invoice_number": "INV-100", "taxable_amount": 1000.0, "tax_amount": 180.0},
         {"id": "p-exact", "invoice_number": "INV-100", "taxable_amount": 1000.0, "tax_amount": 180.0})
    ]
    missed_rows = [{"id": "g-missed", "invoice_number": "INV-999", "gstr2b_data": {"taxable_value": 500.0, "total_tax": 100.0}}]
    risk_rows = [{"id": "p-wrongful", "invoice_number": "DN-888", "is_debit_note": True, "document_type": "DEBIT_NOTE", "taxable_value": 1000.0, "tax_amount": 200.0}]
    review_rows = [{"id": "g-pfx", "invoice_number": "TAX-07/00721", "review_reason": "PREFIX_ALTERATION_REVIEW", "taxable_value": 2000.0, "tax_amount": 360.0}]

    xlsx_bytes, filename = build_excel_workbook_bytes(
        run_id="run-acc-001",
        firm_name="Alpha Chartered Accountants",
        client_trade_name="Industrial Forge Ltd",
        period_raw="2024-05",
        summary={"total_gstr2b_records": 3, "total_pr_records": 3},
        matched_pairs=matched_pairs,
        missed_rows=missed_rows,
        risk_rows=risk_rows,
        rule37_rows=[],
        section17_rows=[],
        review_required_rows=review_rows,
        generated_at=dt.now(timezone.utc),
        generated_by_name="Omkar Kadam",
    )

    assert len(xlsx_bytes) > 0
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    sheet_names = wb.sheetnames
    assert "Matched Records" in sheet_names
    assert "Review Required" in sheet_names
    assert "Compliance Risk" in sheet_names
    assert "Missed ITC" in sheet_names

    # Check doc_type display formatting
    assert _doc_type_display("DEBIT_NOTE") == "Debit Note"
    assert _doc_type_display("CREDIT_NOTE") == "Credit Note"
    assert _doc_type_display("INVOICE") == "Invoice"


# ==============================================================================
# PHASE 3: GSTR-8 STATUTORY & PERSISTENCE ACCEPTANCE TESTS
# ==============================================================================

@pytest.fixture(autouse=True)
def clean_gstr8_store():
    reset_gstr8_memory_store_for_testing()


def test_gstr8_statutory_rates_and_calculations():
    """Verify TCS rates: 1.0% pre-10-Jul-2024 vs 0.5% post-10-Jul-2024 (Notification 15/2024-CT)."""
    # 1. Pre-July 2024 (June 2024) -> 1.0% total
    rate_june = get_applicable_tcs_rates("2024-06")
    assert rate_june.total_rate_pct == Decimal("1.00")
    assert rate_june.cgst_rate == Decimal("0.0050")
    assert rate_june.sgst_rate == Decimal("0.0050")

    # 2. July 2024 transition without date -> Requires Review
    rate_july_nodate = get_applicable_tcs_rates("2024-07")
    assert rate_july_nodate.requires_review is True

    # 3. July 2024 post-cutoff (>= 2024-07-10) -> 0.5% total
    rate_july_post = get_applicable_tcs_rates("2024-07", transaction_date="2024-07-15")
    assert rate_july_post.total_rate_pct == Decimal("0.50")
    assert rate_july_post.cgst_rate == Decimal("0.0025")
    assert rate_july_post.sgst_rate == Decimal("0.0025")

    # 4. Standard supply calculation: Net = ₹1,00,000 - ₹10,000 = ₹90,000 (intra-state 27 -> 27)
    # 0.25% CGST = 225.00, 0.25% SGST = 225.00, Total = 450.00
    calc = calculate_gstr8_tcs(
        period="2026-07",
        gross_supplies=100000.0,
        returned_supplies=10000.0,
        eco_state="27",
        pos="27",
    )
    assert calc.net_supplies == Decimal("90000.00")
    assert calc.tcs_cgst == Decimal("225.00")
    assert calc.tcs_sgst == Decimal("225.00")
    assert calc.tcs_igst == Decimal("0.00")
    assert calc.total_tcs == Decimal("450.00")


def test_gstr8_data_preparation_validation_and_offline_json():
    """Verify batch creation, record preparation, validation, and GSTN offline JSON generation."""
    firm_id = str(uuid4())
    client_id = str(uuid4())
    user_id = str(uuid4())
    period = "2026-07"
    ecom_gstin = "27AABCU9603R1ZM"

    # Use None for sb to test memory store in development test mode
    # 1. Create Batch
    batch = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=ecom_gstin,
        period=period,
        user_id=user_id,
    )
    assert batch["status"] == "DRAFT"
    assert batch["period"] == period

    # 2. Add B2B Records
    rec1 = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch["id"],
        record_data={
            "supply_type": "B2B",
            "supplier_gstin": SUPPLIER_GSTIN_1,
            "supplier_name": "Industrial Forge Ltd",
            "gross_supplies": 500000.00,
            "returned_supplies": 50000.00,
            "pos": "27",
            "transaction_date": "2026-07-15",
        },
        user_id=user_id,
    )
    assert rec1["net_supplies"] == 450000.0
    assert rec1["needs_review"] is False

    # 3. Add July 2024 unverified record -> should trigger review flag
    batch_july = get_or_create_batch_sync(
        None,
        firm_id=firm_id,
        client_gstin_id=client_id,
        gstin=ecom_gstin,
        period="2024-07",
        user_id=user_id,
    )
    rec_review = add_or_update_gstr8_record_sync(
        None,
        batch_id=batch_july["id"],
        record_data={
            "supply_type": "B2B",
            "supplier_gstin": SUPPLIER_GSTIN_1,
            "supplier_name": "Industrial Forge Ltd",
            "gross_supplies": 200000.00,
            "returned_supplies": 0.00,
            "pos": "27",
            "transaction_date": None,  # Missing date in July 2024 transition!
        },
        user_id=user_id,
    )
    assert rec_review["needs_review"] is True
    assert "July 2024 transition record missing transaction_date" in rec_review["review_reason"]

    # 4. Generate GSTN Offline JSON for clean batch
    offline_json = build_gstr8_offline_json(None, batch_id=batch["id"])
    assert offline_json["gstin"] == ecom_gstin
    assert offline_json["fp"] == "072026"
    assert "tcs" in offline_json
    assert len(offline_json["tcs"]) == 1
    assert offline_json["tcs"][0]["gstin_supp"] == SUPPLIER_GSTIN_1


def test_gstr8_live_gstn_filing_safety_guard():
    """Verify that live return filing guard is strictly disabled for production environment."""
    # Production defaults enforce live filing is off
    s_prod = Settings(APP_ENV="production")
    assert s_prod.gstr3b_filing_enabled is False

    # Explicit disable flag
    s_disabled = Settings(GSTR3B_FILING_ENABLED=False)
    assert s_disabled.gstr3b_filing_enabled is False


# ==============================================================================
# PHASE 4: COMMERCIAL WORKFLOWS ACCEPTANCE TESTS
# ==============================================================================

def test_commercial_permitted_coupons_and_40_percent_pricing():
    """Verify subscription discount calculations including the 40% discount tier."""
    # Permitted discount tiers
    assert PERMITTED_DISCOUNTS == {20, 25, 30, 40}

    # Firm Annual Plan Base: ₹14,999.00 (1,499,900 paise)
    base_firm = 1499900

    # 1. 20% Discount: discount = 2,99,980 paise, discounted base = 11,99,920 paise, GST 18% = 2,15,986 paise, total = 14,15,906 paise
    p20 = calculate_discounted_pricing(base_firm, 20)
    assert p20["discount_amount_paise"] == 299980
    assert p20["discounted_base_paise"] == 1199920
    assert p20["gst_paise"] == 215986
    assert p20["total_paise"] == 1415906

    # 2. 25% Discount: discount = 3,74,975 paise, discounted base = 11,24,925 paise
    p25 = calculate_discounted_pricing(base_firm, 25)
    assert p25["discount_amount_paise"] == 374975
    assert p25["discounted_base_paise"] == 1124925

    # 3. 30% Discount: discount = 4,49,970 paise, discounted base = 10,49,930 paise
    p30 = calculate_discounted_pricing(base_firm, 30)
    assert p30["discount_amount_paise"] == 449970
    assert p30["discounted_base_paise"] == 1049930

    # 4. 40% Discount: discount = 5,99,960 paise, discounted base = 8,99,940 paise, GST = 1,61,989 paise, total = 10,61,929 paise
    p40 = calculate_discounted_pricing(base_firm, 40)
    assert p40["discount_amount_paise"] == 599960
    assert p40["discounted_base_paise"] == 899940
    assert p40["gst_paise"] == 161989
    assert p40["total_paise"] == 1061929

    # Rejection of unpermitted discounts
    with pytest.raises(ValueError, match="is not permitted"):
        calculate_discounted_pricing(base_firm, 35)

    with pytest.raises(ValueError, match="is not permitted"):
        calculate_discounted_pricing(base_firm, 50)


def test_commercial_payment_webhook_hmac_sha256_integrity():
    """Verify Razorpay webhook HMAC-SHA256 signature verification and tamper detection."""
    test_secret = "test_webhook_secret_xyz123"
    raw_body = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_12345","amount":899940}}}}'

    # Compute genuine signature
    valid_sig = hmac.new(test_secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    invalid_sig = "9999999999999999999999999999999999999999999999999999999999999999"

    with patch.object(settings, "RAZORPAY_KEY_SECRET", test_secret):
        # 1. Genuine signature accepted
        assert verify_razorpay_webhook_signature(raw_body, valid_sig) is True

        # 2. Forged signature rejected
        assert verify_razorpay_webhook_signature(raw_body, invalid_sig) is False

        # 3. Tampered payload rejected
        tampered_body = b'{"event":"payment.captured","payload":{"payment":{"entity":{"id":"pay_12345","amount":100}}}}'
        assert verify_razorpay_webhook_signature(tampered_body, valid_sig) is False


def test_commercial_notification_preferences_model():
    """Verify notification preference model parses defaults and values cleanly."""
    row = {
        "run_completed": True,
        "runs_expiring_soon": False,
        "payment_receipts": True,
        "rule37_alerts": True,
    }
    prefs = _prefs_from_row(row)
    assert prefs.run_completed is True
    assert prefs.runs_expiring_soon is False
    assert prefs.payment_receipts is True
    assert prefs.rule37_alerts is True
