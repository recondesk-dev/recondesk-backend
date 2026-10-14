"""Targeted regression and safety tests for ReconDesk V2.1 Hardening Implementation.

Covers all 5 audited phases:
  Phase 1 (P1 - High): GSTR-2B Debit Note Classification (70/70 target)
  Phase 2 (P2 - Medium): Debit Note Export Classification (Compliance Risk / Export)
  Phase 3 (P2 - Medium): Credit Note Tax Comparison Explanations (Magnitude-aware tax diff)
  Phase 4 (P1 - High): Invoice Prefix-Change Review Discovery (TAX-07/00721 vs BILL00721)
  Phase 5 (P1 - High): Combined OCR + Branch-Suffix Discovery (TAX-16/01611 vs TAX-16/016II-BR01)
  Phase 6 Safety Gates: 0 false-positive auto-matches, 0 cross-PAN auto-matches
"""

from __future__ import annotations

from datetime import date
import pytest

from app.parsers.gstr2b_parser import (
    _alt_map_note_row,
    _note_type_value,
    CREDIT_NOTE_STRINGS,
    DEBIT_NOTE_STRINGS,
)
from app.services.decision_templates import TEMPLATES
from app.routers.reconciliation_api import _build_wrongful_risk_records
from app.services.reconcile_export_workbook import _doc_type_display
from app.services.matcher import (
    MatchResult,
    build_compared_fields,
    match_gstr_to_pr,
    is_meaningful_numeric_sequence_mismatch,
    is_sequential_series_mismatch,
)
from app.services.reconciliation import (
    ReconState,
    build_pr_candidate_indices,
    build_pr_by_invoice,
    process_gstr_records_chunk,
    execute_phase2_and_3,
)


# =============================================================================
# Phase 1: GSTR-2B Debit Note Classification (Target: 70/70)
# =============================================================================

def test_phase1_note_type_value_aliases():
    """Verify _note_type_value recognizes all debit note and credit note aliases."""
    for val in ["Debit Note", "debit note", "DEBIT", "D", "dr", "DR", "Debit"]:
        assert _note_type_value({"Invoice type": val}) == "D"
        assert _note_type_value({"Document Type": val}) == "D"
        assert _note_type_value({"note_type": val}) == "D"
        assert _note_type_value({"inv_type": val}) == "D"
        assert _note_type_value({"voucher_type": val}) == "D"

    for val in ["Credit Note", "credit note", "CREDIT", "C", "cr", "CR", "Credit"]:
        assert _note_type_value({"Invoice type": val}) == "C"
        assert _note_type_value({"Document Type": val}) == "C"
        assert _note_type_value({"note_type": val}) == "C"


def test_phase1_alt_map_note_row_debit_note_70_variations():
    """Verify 70 synthetic rows with various debit note headers are all classified as 'D'."""
    header_variants = [
        "Invoice type", "invoice_type", "Invoice Type", "inv_type",
        "Document Type", "document_type", "Doc Type", "doc_type",
        "Note Type", "note_type", "Voucher Type", "voucher_type",
        "ntty", "Type",
    ]
    value_variants = ["Debit Note", "DEBIT NOTE", "Debit", "D", "DR", "debit note", "Debit note"]

    count = 0
    for i in range(70):
        h = header_variants[i % len(header_variants)]
        v = value_variants[i % len(value_variants)]
        raw_row = {
            "GSTIN of Supplier": "27AAPFU0939F1ZV",
            "Legal Name of Supplier": "Acme Industrial Tools",
            "Note Number": f"DN-{2024}-{i:04d}",
            "Note Date": "2024-05-15",
            "Taxable Value (₹)": 50000.0,
            "Integrated Tax (₹)": 9000.0,
            h: v,
        }
        mapped = _alt_map_note_row(raw_row)
        assert mapped is not None
        assert mapped["ntty"] == "D", f"Row {i} with key '{h}' and value '{v}' failed to parse as 'D'"
        count += 1

    assert count == 70


# =============================================================================
# Phase 2: Debit Note Export Classification (Target: 70/70)
# =============================================================================

def test_phase2_wrongful_risk_records_debit_note():
    """Verify unmatched PR debit notes are tagged with WRONGFUL_ITC_DEBIT_NOTE and document_type DEBIT_NOTE."""
    from collections import Counter
    from unittest.mock import MagicMock, patch

    pr_row = {
        "id": "pr-dn-001",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "supplier_name": "Precision Castings Pvt Ltd",
        "invoice_number": "DN-88901",
        "invoice_date": "2024-06-10",
        "taxable_value": 75000.0,
        "taxable_paise": 7500000,
        "total_tax_paise": 1350000,
        "is_debit_note": True,
        "document_type": "DEBIT_NOTE",
        "ntty": "D",
    }
    payload = {
        "engine": {
            "wrongful_itc_risk": [pr_row]
        }
    }
    mock_sb = MagicMock()
    with patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={"pr-dn-001": {"matcher": pr_row, "record_data": pr_row}}):
        with patch("app.routers.reconciliation_api._decision_statuses_for_run", return_value={}):
            results = _build_wrongful_risk_records(mock_sb, rid="run-1", payload=payload, note_counts=Counter())
            assert len(results) == 1
            rec = results[0]
            assert rec["document_type"] == "DEBIT_NOTE"
            assert rec["is_debit_note"] is True
            assert rec["decision_what"] == TEMPLATES["WRONGFUL_ITC_DEBIT_NOTE"]["what"]
            assert "Debit note" in rec["decision_why"] or "Debit Note" in rec["decision_why"]


def test_phase2_doc_type_display_in_export():
    """Verify _doc_type_display formats Debit Note correctly in export workbooks."""
    row = {
        "document_type": "DEBIT_NOTE",
        "is_debit_note": True,
        "purchase_register_data": {"document_type": "DEBIT_NOTE", "ntty": "D"},
    }
    assert _doc_type_display(row.get("document_type"), row) == "Debit Note"

    # Fallback checking purchase_register_data
    row_fallback = {
        "purchase_register_data": {"is_debit_note": True},
    }
    assert _doc_type_display(None, row_fallback) == "Debit Note"

    # Credit Note
    cn_row = {
        "document_type": "CREDIT_NOTE",
        "is_credit_note": True,
    }
    assert _doc_type_display(cn_row.get("document_type"), cn_row) == "Credit Note"


# =============================================================================
# Phase 3: Credit Note Tax Comparison Explanation (Target: 70/70)
# =============================================================================

def test_phase3_credit_note_magnitude_aware_tax_comparison():
    """Verify build_compared_fields produces 'exact' match for opposite-signed matching credit notes."""
    # GSTR credit note: total_tax_paise = +180000
    # PR credit note: total_tax_paise = -180000 (standard accounting sign)
    gstr_cn = {
        "id": "g-cn-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "CRN-00125",
        "is_credit_note": True,
        "document_type": "CREDIT_NOTE",
        "ntty": "C",
        "total_tax_paise": 180000,
        "taxable_paise": 1000000,
        "invoice_date": "2024-05-10",
    }
    pr_cn = {
        "id": "p-cn-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "CRN-00125",
        "is_credit_note": True,
        "document_type": "CREDIT_NOTE",
        "ntty": "C",
        "total_tax_paise": -180000,
        "taxable_paise": -1000000,
        "invoice_date": "2024-05-10",
    }

    compared = build_compared_fields(gstr_cn, pr_cn)
    tax_entry = next((f for f in compared if f["field_name"] == "tax_amount"), None)
    assert tax_entry is not None
    assert tax_entry["match_type"] == "exact", f"Expected 'exact' but got {tax_entry['match_type']}"

    taxable_entry = next((f for f in compared if f["field_name"] == "taxable_amount"), None)
    assert taxable_entry is not None
    assert taxable_entry["match_type"] == "exact"


def test_phase3_cross_document_tax_comparison_still_signed():
    """Verify mismatched document types (Invoice vs Credit Note) do not net out silently."""
    gstr_inv = {
        "id": "g-inv-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "INV-100",
        "is_credit_note": False,
        "document_type": "INVOICE",
        "total_tax_paise": 180000,
    }
    pr_cn = {
        "id": "p-cn-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "INV-100",
        "is_credit_note": True,
        "document_type": "CREDIT_NOTE",
        "total_tax_paise": -180000,
    }
    compared = build_compared_fields(gstr_inv, pr_cn)
    tax_entry = next((f for f in compared if f["field_name"] == "tax_amount"), None)
    assert tax_entry is not None
    assert tax_entry["match_type"] == "not_matched"


# =============================================================================
# Phase 4: Invoice Prefix-Change Review Discovery
# =============================================================================

def test_phase4_prefix_alteration_discovery_exact_financial():
    """Verify TAX-07/00721 vs BILL00721 matches under Level 3 PREFIX_ALTERATION_REVIEW."""
    g = {
        "id": "g-pfx-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-07/00721",
        "invoice_number_normalized": "TAX0700721",
        "total_tax_paise": 18000,
        "taxable_paise": 100000,
        "invoice_date": "2024-05-10",
    }
    p = {
        "id": "p-pfx-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "BILL00721",
        "invoice_number_normalized": "BILL00721",
        "total_tax_paise": 18000,
        "taxable_paise": 100000,
        "invoice_date": "2024-05-10",
    }

    result = match_gstr_to_pr(g, [p])
    assert result is not None
    assert result.matched is True
    assert result.level == 3
    assert result.requires_human_review is True
    assert result.review_reason == "PREFIX_ALTERATION_REVIEW"
    assert result.financial_status == "Exact"


def test_phase4_prefix_alteration_adversarial_rejections():
    """Verify safety gates reject sequential collisions, financial diffs, and cross-PAN."""
    # 1. Sequence number mismatch (00721 vs 00722)
    g_seq = {
        "id": "g1", "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-07/00721", "invoice_number_normalized": "TAX0700721",
        "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10",
    }
    p_seq = {
        "id": "p1", "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "BILL00722", "invoice_number_normalized": "BILL00722",
        "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10",
    }
    assert match_gstr_to_pr(g_seq, [p_seq]) is None

    # 2. Financial mismatch (> 5% difference)
    p_fin = dict(p_seq, invoice_number="BILL00721", invoice_number_normalized="BILL00721", total_tax_paise=25000, taxable_paise=150000)
    assert match_gstr_to_pr(g_seq, [p_fin]) is None

    # 3. Cross-PAN mismatch
    p_pan = dict(p_seq, invoice_number="BILL00721", invoice_number_normalized="BILL00721", supplier_gstin="24AAACG1234A1Z5")
    assert match_gstr_to_pr(g_seq, [p_pan]) is None


# =============================================================================
# Phase 5: Combined OCR + Branch-Suffix Discovery (181 candidates target)
# =============================================================================

def test_phase5_combined_ocr_branch_suffix_discovery():
    """Verify TAX-16/01611 vs TAX-16/016II-BR01 matches under Level 3 OCR_CONFIDENCE_REVIEW."""
    g = {
        "id": "g-ocr-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-16/01611",
        "invoice_number_normalized": "TAX1601611",
        "total_tax_paise": 18000,
        "taxable_paise": 100000,
        "invoice_date": "2024-05-10",
    }
    p = {
        "id": "p-ocr-1",
        "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-16/016II-BR01",
        "invoice_number_normalized": "TAX16016IIBR01",
        "total_tax_paise": 18000,
        "taxable_paise": 100000,
        "invoice_date": "2024-05-10",
    }

    result = match_gstr_to_pr(g, [p])
    assert result is not None
    assert result.matched is True
    assert result.level == 3
    assert result.requires_human_review is True
    assert result.review_reason == "OCR_CONFIDENCE_REVIEW"
    assert result.financial_status == "Exact"


def test_phase5_combined_ocr_branch_adversarial_rejections():
    """Verify safety gates reject genuine sequential collisions and cross-PAN for branch suffix cases."""
    # 1. Genuine sequence collision: 1611 vs 1612 with branch suffix
    g = {
        "id": "g1", "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-16/01611", "invoice_number_normalized": "TAX1601611",
        "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10",
    }
    p_collision = {
        "id": "p1", "supplier_gstin": "27AAPFU0939F1ZV",
        "invoice_number": "TAX-16/01612-BR01", "invoice_number_normalized": "TAX1601612BR01",
        "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10",
    }
    assert match_gstr_to_pr(g, [p_collision]) is None

    # 2. Cross-PAN with branch suffix
    p_xpan = {
        "id": "p2", "supplier_gstin": "24AAACG1234A1Z5",
        "invoice_number": "TAX-16/016II-BR01", "invoice_number_normalized": "TAX16016IIBR01",
        "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10",
    }
    assert match_gstr_to_pr(g, [p_xpan]) is None


# =============================================================================
# Phase 6: Full Reconciliation Pipeline Integration & Safety Gates
# =============================================================================

def test_full_pipeline_reconciliation_integration():
    """Run full reconciliation pipeline on a mixed batch containing all 5 bug patterns."""
    gstin = "27AAPFU0939F1ZV"

    gstr_records = [
        # Normal exact match
        {"id": "g-exact", "supplier_gstin": gstin, "invoice_number": "INV-100", "invoice_number_normalized": "INV100", "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10"},
        # Phase 4 prefix change
        {"id": "g-pfx", "supplier_gstin": gstin, "invoice_number": "TAX-07/00721", "invoice_number_normalized": "TAX0700721", "total_tax_paise": 36000, "taxable_paise": 200000, "invoice_date": "2024-05-10"},
        # Phase 5 OCR + branch
        {"id": "g-ocr", "supplier_gstin": gstin, "invoice_number": "TAX-16/01611", "invoice_number_normalized": "TAX1601611", "total_tax_paise": 54000, "taxable_paise": 300000, "invoice_date": "2024-05-10"},
    ]

    pr_records = [
        # Normal exact match
        {"id": "p-exact", "supplier_gstin": gstin, "invoice_number": "INV-100", "invoice_number_normalized": "INV100", "total_tax_paise": 18000, "taxable_paise": 100000, "invoice_date": "2024-05-10"},
        # Phase 4 prefix change counterpart
        {"id": "p-pfx", "supplier_gstin": gstin, "invoice_number": "BILL00721", "invoice_number_normalized": "BILL00721", "total_tax_paise": 36000, "taxable_paise": 200000, "invoice_date": "2024-05-10"},
        # Phase 5 OCR + branch counterpart
        {"id": "p-ocr", "supplier_gstin": gstin, "invoice_number": "TAX-16/016II-BR01", "invoice_number_normalized": "TAX16016IIBR01", "total_tax_paise": 54000, "taxable_paise": 300000, "invoice_date": "2024-05-10"},
    ]

    state = ReconState()
    pr_index = {gstin: pr_records}
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

    # 1. Exact match is clean matched (Level 1)
    clean_ids = [m["gstr_id"] for m in state.clean_matched]
    assert "g-exact" in clean_ids

    # 2. Both prefix change and OCR+branch are in review_required (Level 3)
    review_map = {r["gstr_id"]: r for r in state.review_required}
    assert "g-pfx" in review_map, "g-pfx was not captured in review_required"
    assert review_map["g-pfx"]["review_reason"] == "PREFIX_ALTERATION_REVIEW"

    assert "g-ocr" in review_map, "g-ocr was not captured in review_required"
    assert review_map["g-ocr"]["review_reason"] == "OCR_CONFIDENCE_REVIEW"

    # 3. SAFETY GATE: ZERO false-positive clean auto-matches
    clean_matched_pfx = [m for m in state.clean_matched if m["gstr_id"] in ("g-pfx", "g-ocr")]
    assert len(clean_matched_pfx) == 0, "Fuzzy candidates must NEVER be clean auto-matched!"

    # 4. SAFETY GATE: Missed ITC must not orphan these rows
    missed_gstr_ids = [m["id"] for m in state.missed_itc]
    assert "g-pfx" not in missed_gstr_ids
    assert "g-ocr" not in missed_gstr_ids
