"""Tests for bulk-accept-low-priority endpoint and low-priority review classification.

Verifies:
1. True review priorities (URGENT, HIGH, MEDIUM) are NEVER counted as low priority.
2. Minor rounding / freight variances (< ₹100) are classified as LOW and counted.
3. bulk-accept dry_run=True previews counts/amounts without writing.
4. bulk-accept dry_run=False marks low-priority records as acted with valid rr: IDs.
5. Acted records are excluded from low_priority_review_count.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch
import pytest

from app.routers.reconciliation_api import (
    bulk_accept_low_priority_review,
    BulkAcceptLowPriorityBody,
    _build_reconcile_summary,
)

RUN_ID = str(uuid.uuid4())
GSTR_URGENT = str(uuid.uuid4())
GSTR_LOW = str(uuid.uuid4())
PR_ID = str(uuid.uuid4())


def _make_test_payload() -> dict:
    """Create a payload with 1 URGENT item (₹1,14,384 diff) and 1 LOW item (₹15 diff)."""
    urgent_item = {
        "gstr_id": GSTR_URGENT,
        "pr_id": PR_ID,
        "side": "GSTR",
        "reason": "L3_AMOUNT_MISMATCH",
        "taxable_diff_paise": 11438464,  # ₹1,14,384.64 -> URGENT
        "supplier_gstin": "08DJT2363VEZ4",
        "invoice_number_normalized": "INV202402954",
        "invoice_date": "2024-10-12",
        "confidence_score": 60.0,
        "total_tax_paise": 13925087,
        "amount": 13925087,
        "match_level": 3,
    }
    low_item = {
        "gstr_id": GSTR_LOW,
        "pr_id": PR_ID,
        "side": "GSTR",
        "reason": "ROUNDING_DIFFERENCE",
        "taxable_diff_paise": 1500,  # ₹15.00 (< ₹100) -> LOW
        "supplier_gstin": "27AABCU9603R1ZN",
        "invoice_number_normalized": "INV-100",
        "invoice_date": "2024-10-15",
        "confidence_score": 98.0,
        "total_tax_paise": 500000,
        "amount": 500000,
        "match_level": 1,
    }
    return {
        "engine": {
            "matched": [],
            "duplicates": [],
            "review_required": [urgent_item, low_item],
            "review_required_typo": [],
            "missed_itc": [],
            "wrongful_risk": [],
        },
        "decisions": {"rows": []},
    }


def _make_gstr_map() -> dict:
    return {
        GSTR_URGENT: {"matcher": {"supplier_gstin": "08DJT2363VEZ4", "total_tax_paise": 13925087}},
        GSTR_LOW: {"matcher": {"supplier_gstin": "27AABCU9603R1ZN", "total_tax_paise": 500000}},
    }


@pytest.mark.asyncio
async def test_bulk_accept_low_priority_dry_run_only_counts_low():
    """Verify dry_run only counts the LOW priority item, NOT the URGENT item."""
    payload = _make_test_payload()
    gstr_map = _make_gstr_map()
    current_user = {"id": "user-uuid-1", "role": "admin"}

    with patch("app.routers.reconciliation_api.get_supabase") as mock_sb_fn, \
         patch("app.routers.reconciliation_api.assert_run_accessible") as mock_acc, \
         patch("app.routers.reconciliation_api._payload_or_404", return_value=payload), \
         patch("app.routers.reconciliation_api.ro.load_gstr_map", return_value=gstr_map), \
         patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={}):

        mock_acc.return_value = {"id": RUN_ID, "status": "COMPLETED", "is_locked": False}
        sb = MagicMock()
        mock_sb_fn.return_value = sb

        body = BulkAcceptLowPriorityBody(run_id=RUN_ID, dry_run=True)
        res = await bulk_accept_low_priority_review(body, current_user=current_user)

        # Only 1 item is LOW priority (₹15 diff); URGENT (₹1.14L diff) is excluded
        assert res.low_priority_count == 1
        assert res.low_priority_itc_paise == 500000
        assert res.accepted_count == 0
        assert res.dry_run is True


@pytest.mark.asyncio
async def test_bulk_accept_low_priority_executes_successfully():
    """Verify execution marks only the LOW item as acted with valid rr: ID."""
    payload = _make_test_payload()
    gstr_map = _make_gstr_map()
    current_user = {"id": "user-uuid-1", "role": "admin"}

    with patch("app.routers.reconciliation_api.get_supabase") as mock_sb_fn, \
         patch("app.routers.reconciliation_api.assert_run_accessible") as mock_acc, \
         patch("app.routers.reconciliation_api._payload_or_404", return_value=payload), \
         patch("app.routers.reconciliation_api.ro.load_gstr_map", return_value=gstr_map), \
         patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={}), \
         patch("app.routers.reconciliation_api._upsert_decision_status") as mock_upsert:

        mock_acc.return_value = {"id": RUN_ID, "status": "COMPLETED", "is_locked": False}
        sb = MagicMock()
        mock_sb_fn.return_value = sb

        body = BulkAcceptLowPriorityBody(run_id=RUN_ID, dry_run=False)
        res = await bulk_accept_low_priority_review(body, current_user=current_user)

        assert res.low_priority_count == 1
        assert res.accepted_count == 1
        assert res.dry_run is False
        # Verifies upsert was called with the LOW item's ID and 'acted' status
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        assert kwargs["record_id"] == f"rr:{GSTR_LOW}"
        assert kwargs["status_value"] == "acted"


def test_summary_low_priority_count_excludes_urgent_and_acted():
    """Verify summary only counts un-acted LOW items in low_priority_review_count."""
    payload = _make_test_payload()
    gstr_map = _make_gstr_map()

    run_row = {
        "id": RUN_ID,
        "status": "COMPLETED",
        "client_gstin_id": str(uuid.uuid4()),
        "period": "102024",
    }

    with patch("app.routers.reconciliation_api.get_user_profile", return_value={"role": "admin"}), \
         patch("app.routers.reconciliation_api.ro.load_gstr_map", return_value=gstr_map), \
         patch("app.routers.reconciliation_api.ro.load_pr_map", return_value={}), \
         patch("app.routers.reconciliation_api._notes_count_for_run", return_value={}):

        sb = MagicMock()
        # Mock client_gstins table lookup
        cg_mock = MagicMock()
        cg_mock.data = [{"trade_name": "Test Client", "gstin": "27AABCU9603R1ZN"}]
        sb.table().select().eq().limit().execute.return_value = cg_mock

        # When no decisions have been taken yet
        with patch("app.routers.reconciliation_api._decision_statuses_for_run", return_value={}):
            summary = _build_reconcile_summary(
                sb,
                run_row=run_row,
                payload=payload,
                current_user_id="user-uuid-1",
            )
            # Total review required is 2 (1 urgent + 1 low)
            assert summary["review_required_count"] == 2
            # But low priority review count is ONLY 1 (urgent is excluded)
            assert summary["low_priority_review_count"] == 1
            assert summary["low_priority_review_itc_paise"] == 500000

        # When the low item is acted, it is no longer counted in the banner
        with patch("app.routers.reconciliation_api._decision_statuses_for_run", return_value={GSTR_LOW: "acted"}):
            summary = _build_reconcile_summary(
                sb,
                run_row=run_row,
                payload=payload,
                current_user_id="user-uuid-1",
            )
            assert summary["low_priority_review_count"] == 0
            assert summary["low_priority_review_itc_paise"] == 0

