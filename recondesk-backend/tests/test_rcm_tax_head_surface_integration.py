"""Tests for surface integration of RCM_FLAG_CONFLICT and TAX_HEAD_MISMATCH:
- IMS action recommendations (REASON_RCM_FLAG_CONFLICT, REASON_TAX_HEAD_MISMATCH)
- OutcomeRow normalized_reason preservation
- Matched bucket API filtering by discrepancy_reason
- Vendor follow-up WhatsApp and Email notices
"""

from __future__ import annotations

import pytest
from app.ims.ims_recommendation import (
    InvoiceRecommendationInput,
    REASON_RCM_FLAG_CONFLICT,
    REASON_TAX_HEAD_MISMATCH,
    REASON_NEEDS_REVIEW,
    recommend_invoice,
)
from app.routers.reconciliation_api import _filter_matched
from app.services.vendor_followup_engine import (
    generate_whatsapp_payload,
    generate_email_template,
)
from app.services.reconciliation_outcomes import OutcomeRow


def test_ims_recommendation_rcm_flag_conflict():
    inp = InvoiceRecommendationInput(
        invoice_id="inv-rcm-1",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-2024-001",
        category="review_required",
        match_status="REVIEW_REQUIRED",
        review_reason="RCM_FLAG_CONFLICT",
        total_tax_diff_paise=0,
        amount_paise=100000,
    )
    rec = recommend_invoice(inp)
    assert rec.recommended_action == "hold"
    assert REASON_RCM_FLAG_CONFLICT in rec.reason_codes
    assert REASON_NEEDS_REVIEW in rec.reason_codes
    assert "Reverse charge treatment conflict" in rec.human_readable_why
    assert "Section 9(3)/9(4)" in rec.human_readable_why


def test_ims_recommendation_tax_head_mismatch():
    inp = InvoiceRecommendationInput(
        invoice_id="inv-thm-1",
        supplier_gstin="27AABCU9603R1ZM",
        invoice_number="INV-2024-002",
        category="review_required",
        match_status="REVIEW_REQUIRED",
        review_reason="TAX_HEAD_MISMATCH",
        total_tax_diff_paise=0,
        amount_paise=180000,
    )
    rec = recommend_invoice(inp)
    assert rec.recommended_action == "hold"
    assert REASON_TAX_HEAD_MISMATCH in rec.reason_codes
    assert REASON_NEEDS_REVIEW in rec.reason_codes
    assert "Tax head allocation mismatch" in rec.human_readable_why
    assert "Section 34 Credit Note" in rec.human_readable_why


def test_filter_matched_by_discrepancy_reason():
    row_rcm = {
        "id": "1",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-1",
        "amount": 1000.0,
        "discrepancy_reason": "RCM_FLAG_CONFLICT",
    }
    row_thm = {
        "id": "2",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-2",
        "amount": 2000.0,
        "discrepancy_reason": "TAX_HEAD_MISMATCH",
    }
    row_amt = {
        "id": "3",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-3",
        "amount": 3000.0,
        "discrepancy_reason": "AMOUNT_MISMATCH",
    }
    pairs = [
        (row_rcm, None),
        (row_thm, None),
        (row_amt, None),
    ]

    # Filter for RCM
    filtered_rcm = _filter_matched(
        pairs,
        search_q=None,
        match_level_filter=None,
        amount_min_val=None,
        amount_max_val=None,
        require_notes=False,
        review_required=False,
        section174=False,
        discrepancy_reason_filter="RCM_FLAG_CONFLICT",
    )
    assert len(filtered_rcm) == 1
    assert filtered_rcm[0][0]["id"] == "1"

    # Filter for Tax Head
    filtered_thm = _filter_matched(
        pairs,
        search_q=None,
        match_level_filter=None,
        amount_min_val=None,
        amount_max_val=None,
        require_notes=False,
        review_required=False,
        section174=False,
        discrepancy_reason_filter="TAX_HEAD_MISMATCH",
    )
    assert len(filtered_thm) == 1
    assert filtered_thm[0][0]["id"] == "2"

    # No filter returns all
    filtered_all = _filter_matched(
        pairs,
        search_q=None,
        match_level_filter=None,
        amount_min_val=None,
        amount_max_val=None,
        require_notes=False,
        review_required=False,
        section174=False,
        discrepancy_reason_filter=None,
    )
    assert len(filtered_all) == 3


def test_vendor_followup_whatsapp_templates():
    wa_thm = generate_whatsapp_payload(
        supplier_gstin="27AABCU9603R1ZM",
        supplier_name="Acme Corp",
        vendor_phone="9876543210",
        at_risk_itc_rupees=25000.0,
        template_type="TAX_HEAD_MISMATCH_NOTICE",
    )
    assert "Tax Head / Place of Supply Discrepancy Notice" in wa_thm["message_text"]
    assert "Section 77 of the CGST Act" in wa_thm["message_text"]
    assert "Section 34" in wa_thm["message_text"]
    assert "25,000.00" in wa_thm["message_text"]
    assert "https://wa.me/919876543210" in wa_thm["whatsapp_url"]

    wa_rcm = generate_whatsapp_payload(
        supplier_gstin="27AABCU9603R1ZM",
        supplier_name="Acme Corp",
        vendor_phone="9876543210",
        at_risk_itc_rupees=15000.0,
        template_type="RCM_CONFLICT_NOTICE",
    )
    assert "Reverse Charge (RCM) Treatment Discrepancy" in wa_rcm["message_text"]
    assert "Section 9(3)/9(4)" in wa_rcm["message_text"]
    assert "15,000.00" in wa_rcm["message_text"]


def test_vendor_followup_email_templates():
    email_thm = generate_email_template(
        supplier_gstin="27AABCU9603R1ZM",
        supplier_name="Acme Corp",
        at_risk_itc_rupees=25000.0,
        template_type="TAX_HEAD_MISMATCH_NOTICE",
    )
    assert "Tax Head / Place of Supply Discrepancy" in email_thm["subject"]
    assert "Section 77 of the CGST Act" in email_thm["html_body"]
    assert "Section 34 Credit Note" in email_thm["html_body"]

    email_rcm = generate_email_template(
        supplier_gstin="27AABCU9603R1ZM",
        supplier_name="Acme Corp",
        at_risk_itc_rupees=15000.0,
        template_type="RCM_CONFLICT_NOTICE",
    )
    assert "Reverse Charge (RCM) Classification Discrepancy" in email_rcm["subject"]
    assert "Section 9(3) or 9(4)" in email_rcm["html_body"]
