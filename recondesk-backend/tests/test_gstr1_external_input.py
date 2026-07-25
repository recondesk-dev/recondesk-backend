"""Period/table-level NeedsExternalInput envelope (vs per-row pending_review)."""

from __future__ import annotations

import pytest

from app.filing.gstr1_external_input import (
    TABLE_DOC_ISSUE,
    TABLE_HSN,
    TABLE_NIL,
    FilingDataGaps,
    NeedsExternalInput,
    advances_unavailable_from_sr,
    doc_issue_unavailable_from_sr,
    hsn_unavailable_from_sr,
    nil_split_unavailable_from_sr,
)
from app.filing.gstr1_filing_mapper import PendingReviewInvoice


def test_needs_external_input_is_period_table_not_per_row():
    gap = hsn_unavailable_from_sr("2025-04")
    assert gap.table == TABLE_HSN
    assert gap.filing_period == "2025-04"
    assert "uqc" in gap.missing_fields
    assert "qty" in gap.missing_fields
    # Not a PendingReviewInvoice — different type / UX channel.
    assert not isinstance(gap, PendingReviewInvoice)


def test_nil_and_doc_helpers():
    nil = nil_split_unavailable_from_sr("2025-04")
    assert nil.table == TABLE_NIL
    assert nil.reason == "sr_lumps_nil_exempt_non_gst"

    doc = doc_issue_unavailable_from_sr("2025-04")
    assert doc.table == TABLE_DOC_ISSUE
    assert "series" in doc.message.lower() or "document" in doc.message.lower()


def test_filing_data_gaps_collects_tables():
    gaps = FilingDataGaps()
    gaps.add(hsn_unavailable_from_sr("2025-04"))
    gaps.add(doc_issue_unavailable_from_sr("2025-04"))
    gaps.add(advances_unavailable_from_sr("2025-04"))
    assert gaps.external_input_count == 3
    assert gaps.tables_blocked() == {TABLE_HSN, TABLE_DOC_ISSUE, "at"}


def test_rejects_unknown_table_and_bad_period():
    with pytest.raises(ValueError, match="table"):
        NeedsExternalInput(
            table="b2b",
            filing_period="2025-04",
            reason="x",
            message="y",
        )
    with pytest.raises(ValueError, match="YYYY-MM"):
        NeedsExternalInput(
            table=TABLE_HSN,
            filing_period="04-2025",
            reason="x",
            message="y",
        )


def test_pending_review_remains_row_scoped():
    """Smoke: review channel stays on a concrete SR record."""
    rec = {"invoice_number_raw": "X-1"}
    review = PendingReviewInvoice(
        record=rec,
        proposed_inv_typ=None,
        reason="export_typ_signal_conflict",
        suggested_table="exp",
    )
    assert review.record is rec
    assert not hasattr(review, "filing_period")
