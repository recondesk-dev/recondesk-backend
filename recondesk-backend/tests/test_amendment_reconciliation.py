"""Tests for GSTR-2B amendment resolution and reconciliation integration."""

import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.matching.engine import run_bidirectional_reconciliation
from app.services.amendment_handler import (
    AmendmentResult,
    build_effective_gstr_records,
    process_amendment,
)


def _make_gstr(
    *,
    id: str,
    gstin: str = "27ABCDE1234F1Z5",
    inv: str,
    date: str = "2024-05-01",
    taxable: int = 100000,
    tax: int = 18000,
    is_amendment: bool = False,
    section: str = "b2b",
    oinum: str | None = None,
    oidt: str | None = None,
    supprd: str = "052024",
) -> dict:
    from app.services.matcher import normalize_invoice
    return {
        "id": id,
        "supplier_gstin": gstin,
        "supplier_name": "Supplier 1",
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date,
        "taxable_amount_paise": taxable,
        "cgst_paise": tax // 2,
        "sgst_paise": tax // 2,
        "igst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": tax,
        "is_amendment": is_amendment,
        "section": section,
        "original_invoice_number": normalize_invoice(oinum) if oinum else None,
        "original_invoice_number_raw": oinum,
        "original_invoice_date": oidt,
        "supprd": supprd,
        "doc_type": "INVOICE",
    }


def _make_pr(
    *,
    id: str,
    gstin: str = "27ABCDE1234F1Z5",
    inv: str,
    date: str = "2024-05-01",
    taxable: int = 100000,
    tax: int = 18000,
) -> dict:
    from app.services.matcher import normalize_invoice
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": normalize_invoice(inv),
        "invoice_date": date,
        "taxable_amount_paise": taxable,
        "cgst_paise": tax // 2,
        "sgst_paise": tax // 2,
        "igst_paise": 0,
        "cess_paise": 0,
        "total_tax_paise": tax,
        "doc_type": "INVOICE",
    }


# ==============================================================================
# TEST 1 — Original only
# ==============================================================================
def test_01_original_only():
    """Single normal B2B invoice must remain effective and reconcile normally."""
    gstr = [_make_gstr(id="g-1", inv="INV-001", tax=1000000)]
    res = build_effective_gstr_records(gstr)

    assert len(res.effective_records) == 1
    assert res.effective_records[0]["id"] == "g-1"
    assert len(res.superseded_records) == 0
    assert res.stats.amendment_count == 0
    assert res.stats.superseded_count == 0
    assert res.stats.effective_count == 1


# ==============================================================================
# TEST 2 — Original + one amendment (Same invoice number)
# ==============================================================================
def test_02_original_plus_one_amendment():
    """Original (₹10,000 tax) + Amendment (₹12,000 tax) -> only ₹12,000 effective."""
    g1 = _make_gstr(id="g-orig", inv="INV-001", tax=1000000, is_amendment=False, section="b2b")
    g2 = _make_gstr(
        id="g-amend",
        inv="INV-001",
        tax=1200000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-001",
        supprd="062024",
    )
    res = build_effective_gstr_records([g1, g2])

    assert len(res.effective_records) == 1
    eff = res.effective_records[0]
    assert eff["id"] == "g-amend"
    assert eff["total_tax_paise"] == 1200000
    assert eff.get("is_effective_amendment") is True
    assert eff.get("amendment_type") == "UPWARD_REVISION"
    assert eff.get("itc_change_paise") == 200000

    assert len(res.superseded_records) == 1
    assert res.superseded_records[0]["id"] == "g-orig"
    assert res.stats.raw_count == 2
    assert res.stats.effective_count == 1
    assert res.stats.superseded_count == 1


# ==============================================================================
# TEST 3 — Amendment with changed taxable and tax amounts
# ==============================================================================
def test_03_amendment_changed_taxable_and_tax():
    """Downward revision amendment correctly reflects revised financial figures."""
    g1 = _make_gstr(id="g-orig", inv="INV-002", taxable=2000000, tax=360000)
    g2 = _make_gstr(
        id="g-amend",
        inv="INV-002",
        taxable=1500000,
        tax=270000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-002",
    )
    res = build_effective_gstr_records([g1, g2])

    assert len(res.effective_records) == 1
    eff = res.effective_records[0]
    assert eff["taxable_amount_paise"] == 1500000
    assert eff["total_tax_paise"] == 270000
    assert eff.get("amendment_type") == "DOWNWARD_REVISION"
    assert eff.get("itc_change_paise") == -90000


# ==============================================================================
# TEST 4 — Renumbered amendment (oinum != inum)
# ==============================================================================
def test_04_amendment_changed_invoice_number():
    """Amended invoice renumbers INV-003 to INV-003-REV; links cleanly via oinum."""
    g1 = _make_gstr(id="g-orig", inv="INV-003", taxable=100000, tax=18000)
    g2 = _make_gstr(
        id="g-amend",
        inv="INV-003-REV",
        taxable=100000,
        tax=18000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-003",
    )
    res = build_effective_gstr_records([g1, g2])

    assert len(res.effective_records) == 1
    eff = res.effective_records[0]
    assert eff["id"] == "g-amend"
    assert eff["invoice_number"] == "INV-003-REV"
    assert len(res.superseded_records) == 1
    assert res.superseded_records[0]["id"] == "g-orig"


# ==============================================================================
# TEST 5 — Cross-month amendment (Original not in current run)
# ==============================================================================
def test_05_cross_month_amendment():
    """Amendment in current period without prior original must participate as effective."""
    g_amend = _make_gstr(
        id="g-aug-amend",
        inv="INV-JULY-01",
        taxable=500000,
        tax=90000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-JULY-01",
        supprd="082024",
    )
    res = build_effective_gstr_records([g_amend])

    assert len(res.effective_records) == 1
    assert res.effective_records[0]["id"] == "g-aug-amend"
    assert len(res.superseded_records) == 0
    assert res.effective_records[0].get("amendment_type") == "AMENDMENT_WITHOUT_ORIGINAL"


# ==============================================================================
# TEST 6 — Multiple amendments in direct chain (O -> A1 -> A2)
# ==============================================================================
def test_06_multiple_amendments_chain():
    """Original -> Amend 1 -> Amend 2: Terminal successor Amend 2 wins structurally."""
    g_orig = _make_gstr(id="g-orig", inv="INV-100", tax=100000, supprd="042024")
    g_amend1 = _make_gstr(
        id="g-a1",
        inv="INV-100-REV1",
        tax=120000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-100",
        supprd="052024",
    )
    g_amend2 = _make_gstr(
        id="g-a2",
        inv="INV-100-FINAL",
        tax=150000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-100-REV1",
        supprd="062024",
    )
    res = build_effective_gstr_records([g_orig, g_amend1, g_amend2])

    assert len(res.effective_records) == 1
    eff = res.effective_records[0]
    assert eff["id"] == "g-a2"
    assert eff["invoice_number"] == "INV-100-FINAL"
    assert eff["total_tax_paise"] == 150000

    superseded_ids = {r["id"] for r in res.superseded_records}
    assert superseded_ids == {"g-orig", "g-a1"}
    assert res.stats.effective_count == 1
    assert res.stats.superseded_count == 2


# ==============================================================================
# TEST 7 — Sibling amendments both referencing root original (A1 -> O <- A2)
# ==============================================================================
def test_07_sibling_amendments_tie_breaking():
    """A1 and A2 both point to O; later return period A2 wins."""
    g_orig = _make_gstr(id="g-orig", inv="INV-200", tax=100000, supprd="042024")
    g_a1 = _make_gstr(
        id="g-a1",
        inv="INV-200",
        tax=110000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-200",
        supprd="052024",
    )
    g_a2 = _make_gstr(
        id="g-a2",
        inv="INV-200",
        tax=130000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-200",
        supprd="062024",
    )
    res = build_effective_gstr_records([g_orig, g_a1, g_a2])

    assert len(res.effective_records) == 1
    assert res.effective_records[0]["id"] == "g-a2"
    assert res.effective_records[0]["total_tax_paise"] == 130000
    assert len(res.superseded_records) == 2


# ==============================================================================
# TEST 8 — Multiple unrelated invoices
# ==============================================================================
def test_08_multiple_unrelated_invoices():
    """Chained invoices are collapsed while unrelated invoices remain untouched."""
    # Invoice 1: has amendment
    inv1_orig = _make_gstr(id="inv1-o", inv="INV-001", tax=10000)
    inv1_amend = _make_gstr(
        id="inv1-a", inv="INV-001", tax=15000, is_amendment=True, section="b2ba", oinum="INV-001"
    )
    # Invoice 2: normal B2B only
    inv2 = _make_gstr(id="inv2", inv="INV-002", tax=20000)
    # Invoice 3: has amendment
    inv3_orig = _make_gstr(id="inv3-o", inv="INV-003", tax=30000)
    inv3_amend = _make_gstr(
        id="inv3-a", inv="INV-003-REV", tax=35000, is_amendment=True, section="b2ba", oinum="INV-003"
    )

    records = [inv1_orig, inv1_amend, inv2, inv3_orig, inv3_amend]
    res = build_effective_gstr_records(records)

    assert len(res.effective_records) == 3
    eff_ids = {r["id"] for r in res.effective_records}
    assert eff_ids == {"inv1-a", "inv2", "inv3-a"}
    assert len(res.superseded_records) == 2
    assert {r["id"] for r in res.superseded_records} == {"inv1-o", "inv3-o"}


# ==============================================================================
# TEST 9 — Duplicate amendment input
# ==============================================================================
def test_09_duplicate_amendment_input():
    """Identical duplicate amendment entries are deduplicated to avoid doubling ITC."""
    a1 = _make_gstr(
        id="a-copy-1",
        inv="INV-DUP-1",
        tax=50000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-DUP-1",
    )
    a2 = _make_gstr(
        id="a-copy-2",
        inv="INV-DUP-1",
        tax=50000,
        is_amendment=True,
        section="b2ba",
        oinum="INV-DUP-1",
    )
    res = build_effective_gstr_records([a1, a2])

    assert len(res.effective_records) == 1
    assert res.effective_records[0]["id"] == "a-copy-1"
    assert len(res.superseded_records) == 1
    assert res.superseded_records[0]["id"] == "a-copy-2"
    assert res.superseded_records[0]["superseded_reason"] == "DUPLICATE_AMENDMENT_INPUT"


# ==============================================================================
# TEST 10 — PR Matching with Effective Record
# ==============================================================================
def test_10_pr_matching_with_effective_record():
    """Reconciliation matches PR against effective amended record; no false mismatch."""
    g_orig = _make_gstr(id="g-orig", inv="INV-MATCH-1", taxable=100000, tax=18000)
    g_amend = _make_gstr(
        id="g-amend",
        inv="INV-MATCH-1",
        taxable=120000,
        tax=21600,
        is_amendment=True,
        section="b2ba",
        oinum="INV-MATCH-1",
    )
    # PR booked the revised figure
    pr = _make_pr(id="pr-1", inv="INV-MATCH-1", taxable=120000, tax=21600)

    recon_output = run_bidirectional_reconciliation(
        gstr_records=[g_orig, g_amend],
        pr_records=[pr],
        gstr_period=datetime.date(2024, 5, 1),
    )

    stats = recon_output["stats"]
    assert stats["total_gstr"] == 1  # Exactly 1 effective GSTR record in scope!
    assert stats["matched_count"] == 1
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0
    assert stats["sanity_passed"] is True
    assert len(recon_output["matched"]) == 1
    assert recon_output["matched"][0]["gstr_id"] == "g-amend"


# ==============================================================================
# TEST 11 — No amendment regression
# ==============================================================================
def test_11_no_amendment_regression():
    """Standard dataset with only normal B2B invoices remains 100% unchanged."""
    g1 = _make_gstr(id="g-1", inv="INV-NORM-1", taxable=100000, tax=18000)
    pr1 = _make_pr(id="pr-1", inv="INV-NORM-1", taxable=100000, tax=18000)

    recon_output = run_bidirectional_reconciliation(
        gstr_records=[g1],
        pr_records=[pr1],
        gstr_period=datetime.date(2024, 5, 1),
    )

    stats = recon_output["stats"]
    assert stats["total_gstr"] == 1
    assert stats["matched_count"] == 1
    assert stats["clean_matched_count"] == 1
    assert stats["missed_itc_count"] == 0
    assert stats["sanity_passed"] is True


# ==============================================================================
# TEST 12 — Celery Pipeline Integration Verification
# ==============================================================================
def test_12_pipeline_trace_executes_amendment_resolution():
    """Verify that execute_reconciliation actually calls build_effective_gstr_records."""
    from app.worker.reconciliation_task import execute_reconciliation

    mock_client = MagicMock()
    run_record = {
        "id": "run-test-123",
        "client_gstin_id": "00000000-0000-0000-0000-000000000001",
        "period": "2024-05",
        "gstr_records_imported": 2,
        "pr_records_imported": 1,
        "status": "MATCHING",
        "user_id": "user-test-123",
    }
    # Mock select().eq().limit().execute()
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [run_record]
    # Mock update().eq().eq().execute()
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [run_record]
    # Also support general update().eq().execute()
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [run_record]
    # Mock gstr_records: 1 original + 1 amendment
    g_orig_db = {
        "id": "g-db-orig",
        "record_data": {
            "supplier_gstin": "27ABCDE1234F1Z5",
            "invoice_number": "INV-TRACE-1",
            "invoice_date": "2024-05-01",
            "taxable_value_paise": 100000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "total_tax_paise": 18000,
            "is_amendment": False,
            "section": "b2b",
        },
    }
    g_amend_db = {
        "id": "g-db-amend",
        "record_data": {
            "supplier_gstin": "27ABCDE1234F1Z5",
            "invoice_number": "INV-TRACE-1",
            "invoice_date": "2024-05-01",
            "taxable_value_paise": 120000,
            "cgst_paise": 10800,
            "sgst_paise": 10800,
            "total_tax_paise": 21600,
            "is_amendment": True,
            "section": "b2ba",
            "oinum": "INV-TRACE-1",
        },
    }

    # Mock PR records
    pr_db = {
        "id": "pr-db-1",
        "record_data": {
            "supplier_gstin": "27ABCDE1234F1Z5",
            "invoice_number": "INV-TRACE-1",
            "invoice_date": "2024-05-01",
            "taxable_amount_paise": 120000,
            "total_tax_paise": 21600,
            "payment_status": "PAID",
        },
    }

    saved_payloads = []

    def mock_save(c, rid, payload, created_at=None):
        saved_payloads.append(payload)

    with patch("app.worker.reconciliation_task._supabase", return_value=mock_client), \
         patch("app.worker.reconciliation_task._update_run"), \
         patch("app.worker.reconciliation_task._load_gstr_matcher_and_raw") as mock_load_gstr, \
         patch("app.worker.reconciliation_task._build_pr_index_for_matching") as mock_load_pr, \
         patch("app.worker.reconciliation_task._load_pr_for_historical_periods_paged", return_value={}), \
         patch("app.worker.reconciliation_task.save_reconciliation_results", side_effect=mock_save), \
         patch("app.worker.reconciliation_task.notify_reconciliation_run_completed_email_maybe"):

        # Return matcher rows
        from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row, pr_db_row_to_matcher_row
        m_orig = gstr_db_row_to_matcher_row(g_orig_db)
        m_amend = gstr_db_row_to_matcher_row(g_amend_db)
        mock_load_gstr.return_value = ([m_orig, m_amend], {"g-db-orig": g_orig_db["record_data"], "g-db-amend": g_amend_db["record_data"]})

        pr_row = pr_db_row_to_matcher_row(pr_db)
        mock_load_pr.return_value = ({"27ABCDE1234F1Z5": [pr_row]}, 1, 0, [])

        execute_reconciliation("run-test-123")

    assert len(saved_payloads) == 1
    payload = saved_payloads[0]
    assert "amendment_summary" in payload
    summary = payload["amendment_summary"]
    assert summary["raw_count"] == 2
    assert summary["effective_count"] == 1
    assert summary["superseded_count"] == 1
    assert summary["chains_count"] == 1
