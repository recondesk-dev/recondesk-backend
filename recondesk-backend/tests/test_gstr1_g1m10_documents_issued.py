"""G1M10 — Documents Issued Summary (GSTR-1 Table 13).

Covers:
- Summary computation from sample Sales Register
- Graceful degradation when cancellations are not tracked
- OOM regression: messy/pathological invoice series must not crash
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.rules.gstr1_mismatch_rules import (
    MismatchSeverity,
    MismatchType,
    summarize_documents_issued,
)

SAMPLE_DIR = Path(__file__).resolve().parent / "sample_gstr1_3b_test"
SAMPLE_SR = SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx"
SAMPLE_GSTR1 = SAMPLE_DIR / "sample_gstr1.json"

DOWNLOADS = Path.home() / "Downloads"
MESSY_SR = DOWNLOADS / "Sales_Register_MESSY.xlsx"
MESSY_G1 = DOWNLOADS / "GSTR1_MESSY.json"
MESSY_G3 = DOWNLOADS / "GSTR3B_MESSY.json"


def _sr(
    *,
    inv: str,
    invoice_type: str = "B2B",
    cancelled: object | None = ...,
) -> dict:
    rec: dict = {
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_type": invoice_type,
        "document_type": invoice_type,
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
    }
    if cancelled is not ...:
        rec["cancelled"] = cancelled
    return rec


class TestSummarizeDocumentsIssued:

    def test_groups_tax_invoices_by_series(self):
        records = [
            _sr(inv="INV/001"),
            _sr(inv="INV/002"),
            _sr(inv="INV/004"),
        ]
        summary, flags = summarize_documents_issued(records, None)
        assert summary["total_series"] == 1
        assert summary["total_documents_issued"] == 3
        row = summary["series"][0]
        assert row["document_type"] == "TAX_INVOICE"
        assert row["series_prefix"] == "INV/"
        assert row["opening_number"] == "INV/001"
        assert row["closing_number"] == "INV/004"
        assert row["total_issued"] == 3
        assert row["cancelled"] is None
        assert row["net_issued"] == 3
        assert row["span_bounded"] is True
        assert row["expected_serial_count"] == 4
        assert summary["cancellations_determinable"] is False

        types = {f.details.get("issue_type") for f in flags}
        assert "summary_computed" in types
        assert "cancellations_unknown" in types
        assert all(f.mismatch_type == MismatchType.DOCUMENTS_ISSUED_SUMMARY for f in flags)
        assert all(f.severity == MismatchSeverity.LOW for f in flags)

    def test_separates_credit_notes(self):
        records = [
            _sr(inv="INV/001", invoice_type="B2B"),
            _sr(inv="CN/001", invoice_type="CREDIT_NOTE"),
            _sr(inv="CN/002", invoice_type="CREDIT_NOTE"),
        ]
        summary, _ = summarize_documents_issued(records, None)
        by_type = summary["by_document_type"]
        assert "TAX_INVOICE" in by_type
        assert "CREDIT_NOTE" in by_type
        assert by_type["CREDIT_NOTE"]["total_issued"] == 2

    def test_explicit_cancelled_flag_counted(self):
        records = [
            _sr(inv="INV/001", cancelled=False),
            _sr(inv="INV/002", cancelled=True),
            _sr(inv="INV/003", cancelled=False),
        ]
        summary, flags = summarize_documents_issued(records, None)
        row = summary["series"][0]
        assert row["cancelled"] == 1
        assert row["net_issued"] == 2
        assert summary["cancellations_determinable"] is True
        assert not any(
            f.details.get("issue_type") == "cancellations_unknown" for f in flags
        )

    def test_empty_inputs(self):
        summary, flags = summarize_documents_issued([], [])
        assert summary["series"] == []
        assert flags == []

    def test_skips_hsn_summary_rows(self):
        records = [
            _sr(inv="INV/001"),
            {
                "invoice_number": "HSN-8203-0",
                "invoice_type": "HSN_SUMMARY",
                "document_type": "HSN_SUMMARY",
                "section": "hsn",
            },
        ]
        summary, _ = summarize_documents_issued(records, None)
        assert summary["total_documents_issued"] == 1


class TestSampleDataIntegration:

    def test_sample_sr_summary(self):
        from app.parsers.sales_register_parser import parse_sales_register

        if not SAMPLE_SR.exists():
            pytest.skip(f"Sample SR not found: {SAMPLE_SR}")
        parsed = parse_sales_register(SAMPLE_SR.read_bytes(), SAMPLE_SR.name)
        assert parsed.get("success")
        summary, flags = summarize_documents_issued(parsed["records"], None)

        assert summary["total_documents_issued"] == len(parsed["records"])
        assert summary["total_series"] >= 1
        assert summary["cancellations_determinable"] is False
        assert "TAX_INVOICE" in summary["by_document_type"]
        tax = summary["by_document_type"]["TAX_INVOICE"]
        assert tax["total_issued"] == len(parsed["records"])
        assert tax["cancelled"] is None

        for row in summary["series"]:
            assert row["opening_number"]
            assert row["closing_number"]
            assert row["total_issued"] >= 1
            # Sample invoice numbers share a sane prefix span
            assert row["span_bounded"] is True

        assert any(f.details.get("issue_type") == "summary_computed" for f in flags)
        assert any(f.details.get("issue_type") == "cancellations_unknown" for f in flags)


class TestMessyOomRegression:

    def test_messy_sr_completes_quickly_without_oom(self):
        """Pathological RD2026273xxx vs RD3xxx series must not allocate huge ranges."""
        from app.parsers.sales_register_parser import parse_sales_register

        if not MESSY_SR.is_file():
            pytest.skip("MESSY SR fixture not present in ~/Downloads")

        parsed = parse_sales_register(MESSY_SR.read_bytes(), MESSY_SR.name)
        assert parsed.get("success")

        t0 = time.perf_counter()
        summary, flags = summarize_documents_issued(parsed["records"], None)
        elapsed = time.perf_counter() - t0

        assert elapsed < 2.0, f"G1M10 took too long ({elapsed:.2f}s) — possible OOM path"
        assert summary["total_documents_issued"] == len(parsed["records"])
        assert summary["total_series"] >= 1
        # Messy mixed formats → at least one span_skipped flag
        assert any(f.details.get("issue_type") == "span_skipped" for f in flags)
        for row in summary["series"]:
            # Never materialise expected_serial_count for unbounded spans
            if not row["span_bounded"]:
                assert row["expected_serial_count"] is None

    @pytest.mark.asyncio
    async def test_messy_pipeline_includes_documents_issued(self):
        if not (MESSY_SR.is_file() and MESSY_G1.is_file() and MESSY_G3.is_file()):
            pytest.skip("MESSY fixtures not present in ~/Downloads")

        from app.routers.gstr1_reconcile import _run_pipeline

        with patch(
            "app.routers.gstr1_reconcile._verify_buyer_gstins_for_g1m7",
            new_callable=AsyncMock,
            return_value=[],
        ):
            out = await _run_pipeline(
                MESSY_SR.read_bytes(),
                MESSY_SR.name,
                MESSY_G1.read_bytes(),
                MESSY_G3.read_bytes(),
                None,
            )

        assert out["success"] is True
        docs = out.get("documents_issued") or {}
        assert docs.get("total_series", 0) >= 1
        assert docs.get("total_documents_issued", 0) == 25
        g1m10 = [
            m for m in out.get("mismatches", [])
            if "G1M10" in str(m.get("mismatch_type", ""))
        ]
        assert len(g1m10) >= 1
