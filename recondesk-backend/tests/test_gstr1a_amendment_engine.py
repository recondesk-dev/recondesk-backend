"""Unit and integration tests for ReconDesk Phase 4.1:
GSTR-1A Amendment Intelligence & Filing Integration Engine.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.rules.gstr1a_eligibility import Gstr1aWindowStatus
from app.services.gstr1a_service import (
    Gstr1aDuplicateError,
    Gstr1aError,
    Gstr1aWindowClosedError,
    add_or_update_amendment_item_sync,
    build_gstr1a_offline_json,
    calculate_diff_and_deltas,
    compute_batch_figures_digest,
    compute_gstr1a_window_for_gstin,
    compute_item_digest,
    delete_amendment_item_sync,
    get_gstr1a_liability_impact_sync,
    get_or_create_batch_sync,
    invalidate_gstr3b_approvals_and_consent,
)
from app.services.pre_filing_validator import (
    ValidationSeverity,
    validate_gstr1a_pre_filing,
)
from app.filing.gstr3b_suggestions import load_osup_det_suggestion
from app.filing.sandbox_filing_client import (
    FilingApiError,
    FilingGstnError,
    SandboxFilingClient,
)


class MockQueryBuilder:
    def __init__(self, data=None):
        self._data = data or []

    def select(self, *args, **kwargs):
        return self

    def insert(self, val):
        if isinstance(val, dict):
            self._data = [val]
        elif isinstance(val, list):
            self._data = val
        return self

    def update(self, val):
        if self._data and isinstance(self._data, list):
            for row in self._data:
                row.update(val)
        return self

    def delete(self):
        self._data = []
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        res = MagicMock()
        res.data = self._data
        return res


class MockSupabase:
    def __init__(self):
        self.tables: dict[str, list[dict[str, Any]]] = {
            "gstr1a_amendment_batches": [],
            "gstr1a_amendment_items": [],
            "gstr1a_amendment_audit_trail": [],
            "return_filing_approvals": [],
            "client_filing_authorizations": [],
            "gstr1_reconciliation_run": [],
        }

    def table(self, table_name: str):
        data = self.tables.setdefault(table_name, [])
        qb = MockQueryBuilder(data)

        # Connect modifications back to table storage
        orig_insert = qb.insert
        def insert_hook(val):
            if isinstance(val, dict):
                row = dict(val)
                if "id" not in row:
                    row["id"] = f"mock-{len(data) + 1}"
                data.append(row)
                qb._data = [row]
            elif isinstance(val, list):
                for v in val:
                    row = dict(v)
                    if "id" not in row:
                        row["id"] = f"mock-{len(data) + 1}"
                    data.append(row)
                qb._data = val
            return qb

        orig_update = qb.update
        def update_hook(val):
            for row in data:
                row.update(val)
            qb._data = data
            return qb

        orig_delete = qb.delete
        def delete_hook():
            data.clear()
            qb._data = []
            return qb

        qb.insert = insert_hook
        qb.update = update_hook
        qb.delete = delete_hook
        return qb


# ==============================================================================
# 1. WINDOW CALCULATION & RULE 59(1A) TESTS
# ==============================================================================

def test_gstr1a_window_rule_59_1a_closed_when_3b_filed():
    """Rule 59(1A): GSTR-1A is permanently closed once GSTR-3B is filed."""
    res = compute_gstr1a_window_for_gstin(
        gstin="27AAPFU0939F1ZV",
        period="2026-01",
        gstr1_filed_date="2026-01-11",
        gstr3b_filed_date="2026-01-19",
        as_of=date(2026, 1, 20),
    )
    assert res["status"] == Gstr1aWindowStatus.WINDOW_CLOSED.value
    assert res["days_remaining"] == 0
    assert "Rule 59(1A)" in str(res["note"])


def test_gstr1a_window_not_open_before_gstr1_filed():
    """Rule 59(1A): GSTR-1A is not open if GSTR-1 has not yet been filed."""
    res = compute_gstr1a_window_for_gstin(
        gstin="27AAPFU0939F1ZV",
        period="2026-01",
        gstr1_filed_date=None,
        gstr3b_filed_date=None,
        as_of=date(2026, 1, 10),
    )
    assert res["status"] == Gstr1aWindowStatus.NOT_OPEN.value
    assert res["days_remaining"] is None


def test_gstr1a_window_open_between_gstr1_and_3b_monthly():
    """Window is open between GSTR-1 filing and monthly 3B due date (20th)."""
    res = compute_gstr1a_window_for_gstin(
        gstin="27AAPFU0939F1ZV",
        period="2026-01",
        gstr1_filed_date="2026-01-10",
        gstr3b_filed_date=None,
        filing_frequency="monthly",
        as_of=date(2026, 2, 15),
    )
    assert res["status"] == Gstr1aWindowStatus.OPEN.value
    assert res["gstr3b_due_date"] == "2026-02-20"
    assert res["days_remaining"] == 5


def test_gstr1a_window_qrmp_group_a_and_group_b():
    """QRMP filers have staggered deadlines (22nd for Group A, 24th for Group B)."""
    # Maharashtra (27) is Group A -> 22nd
    res_mh = compute_gstr1a_window_for_gstin(
        gstin="27AAPFU0939F1ZV",
        period="2026-03",
        gstr1_filed_date="2026-04-12",
        gstr3b_filed_date=None,
        filing_frequency="qrmp",
        as_of=date(2026, 4, 18),
    )
    assert res_mh["status"] == Gstr1aWindowStatus.OPEN.value
    assert res_mh["gstr3b_due_date"] == "2026-04-22"
    assert res_mh["days_remaining"] == 4

    # Uttar Pradesh (09) is Group B -> 24th
    res_up = compute_gstr1a_window_for_gstin(
        gstin="09AAPFU0939F1ZV",
        period="2026-03",
        gstr1_filed_date="2026-04-12",
        gstr3b_filed_date=None,
        filing_frequency="qrmp",
        as_of=date(2026, 4, 18),
    )
    assert res_up["status"] == Gstr1aWindowStatus.OPEN.value
    assert res_up["gstr3b_due_date"] == "2026-04-24"
    assert res_up["days_remaining"] == 6


# ==============================================================================
# 2. DIFF & TAX DELTA CALCULATION
# ==============================================================================

def test_addition_delta_calculation():
    """An invoice addition delta equals the full amended values."""
    amen = {
        "taxable_value": 100000.0,
        "igst": 18000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
    }
    diff = calculate_diff_and_deltas("ADDITION", "4A", None, amen)
    assert diff["delta_taxable_value"] == 100000.0
    assert diff["delta_igst"] == 18000.0
    assert diff["delta_cgst"] == 0.0


def test_amendment_delta_calculation():
    """An invoice amendment delta equals (amended - original)."""
    orig = {
        "taxable_value": 50000.0,
        "igst": 9000.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
    }
    amen = {
        "taxable_value": 75000.0,
        "igst": 13500.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
    }
    diff = calculate_diff_and_deltas("AMENDMENT", "9A_B2B", orig, amen)
    assert diff["delta_taxable_value"] == 25000.0
    assert diff["delta_igst"] == 4500.0
    assert "taxable_value" in diff["diff_summary"]
    assert diff["diff_summary"]["taxable_value"]["original"] == 50000.0
    assert diff["diff_summary"]["taxable_value"]["amended"] == 75000.0


def test_credit_note_delta_reduces_liability():
    """A credit note addition reduces outward liability (negative delta)."""
    amen = {
        "taxable_value": 20000.0,
        "igst": 3600.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
        "note_type": "C",
    }
    diff = calculate_diff_and_deltas("ADDITION", "9B_CDNR", None, amen)
    assert diff["delta_taxable_value"] == -20000.0
    assert diff["delta_igst"] == -3600.0
    assert diff["is_credit_note"] is True


def test_debit_note_delta_increases_liability():
    """A debit note addition increases outward liability (positive delta)."""
    amen = {
        "taxable_value": 20000.0,
        "igst": 3600.0,
        "cgst": 0.0,
        "sgst": 0.0,
        "cess": 0.0,
        "note_type": "D",
    }
    diff = calculate_diff_and_deltas("ADDITION", "9B_CDNR", None, amen)
    assert diff["delta_taxable_value"] == 20000.0
    assert diff["delta_igst"] == 3600.0
    assert diff["is_credit_note"] is False


def test_credit_note_amendment_delta_more_credit():
    """Amending a credit note to higher value further reduces outward liability."""
    orig = {
        "taxable_value": 10000.0,
        "igst": 1800.0,
        "note_type": "C",
    }
    amen = {
        "taxable_value": 15000.0,
        "igst": 2700.0,
        "note_type": "C",
    }
    diff = calculate_diff_and_deltas("AMENDMENT", "9B_CDNRA", orig, amen)
    # Extra credit of 5000 -> outward liability reduced by 5000
    assert diff["delta_taxable_value"] == -5000.0
    assert diff["delta_igst"] == -900.0


def test_credit_note_amendment_delta_reduced_credit():
    """Amending a credit note to lower value increases outward liability."""
    orig = {
        "taxable_value": 10000.0,
        "igst": 1800.0,
        "note_type": "C",
    }
    amen = {
        "taxable_value": 8000.0,
        "igst": 1440.0,
        "note_type": "C",
    }
    diff = calculate_diff_and_deltas("AMENDMENT", "9B_CDNRA", orig, amen)
    # Credit reduced by 2000 -> outward liability increases by 2000
    assert diff["delta_taxable_value"] == 2000.0
    assert diff["delta_igst"] == 360.0


def test_debit_note_amendment_delta():
    """Amending a debit note to higher value increases outward liability."""
    orig = {
        "taxable_value": 10000.0,
        "igst": 1800.0,
        "note_type": "D",
    }
    amen = {
        "taxable_value": 15000.0,
        "igst": 2700.0,
        "note_type": "D",
    }
    diff = calculate_diff_and_deltas("AMENDMENT", "9B_CDNRA", orig, amen)
    assert diff["delta_taxable_value"] == 5000.0
    assert diff["delta_igst"] == 900.0



# ==============================================================================
# 3. DUPLICATE DETECTION & WINDOW ENFORCEMENT
# ==============================================================================

def test_duplicate_amendment_prevention():
    """Cannot amend the exact same invoice twice in the same batch."""
    sb = MockSupabase()
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000002"
    gstin = "27AAPFU0939F1ZV"
    period = "2026-01"

    # Add item 1
    add_or_update_amendment_item_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=gstin,
        period=period,
        table_name="9A_B2B",
        action_type="AMENDMENT",
        original_invoice_number="INV-001",
        amended_payload={"taxable_value": 10000, "igst": 1800},
        skip_window_check=True,
    )

    # Attempt adding duplicate amendment for INV-001
    with pytest.raises(Gstr1aDuplicateError) as exc_info:
        add_or_update_amendment_item_sync(
            sb,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin=gstin,
            period=period,
            table_name="9A_B2B",
            action_type="AMENDMENT",
            original_invoice_number="INV-001",
            amended_payload={"taxable_value": 15000, "igst": 2700},
            skip_window_check=True,
        )
    assert "already exists" in str(exc_info.value)


def test_window_closed_prevents_item_addition():
    """Trying to add an item when GSTR-3B is already filed raises Gstr1aWindowClosedError."""
    sb = MockSupabase()
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000002"

    with pytest.raises(Gstr1aWindowClosedError):
        add_or_update_amendment_item_sync(
            sb,
            firm_id=firm_id,
            client_gstin_id=client_gid,
            gstin="27AAPFU0939F1ZV",
            period="2026-01",
            table_name="4A",
            action_type="ADDITION",
            amended_payload={"taxable_value": 10000, "igst": 1800},
            skip_window_check=False,
            gstr1_filed=True,
            gstr3b_filed=True,  # GSTR-3B filed!
        )


# ==============================================================================
# 4. GSTR-3B LIABILITY PROPAGATION & APPROVAL INVALIDATION
# ==============================================================================

def test_gstr3b_approval_and_consent_invalidation():
    """GSTR-1A modifications durably invalidate pre-existing GSTR-3B approval and client consent."""
    sb = MockSupabase()
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    # Setup pre-existing GSTR-3B approval and authorization
    sb.tables["return_filing_approvals"] = [{
        "id": "app-3b-1",
        "firm_id": firm_id,
        "client_gstin_id": client_gid,
        "period": period,
        "return_type": "GSTR-3B",
        "status": "APPROVED",
    }]
    sb.tables["client_filing_authorizations"] = [{
        "id": "auth-3b-1",
        "firm_id": firm_id,
        "client_gstin_id": client_gid,
        "period": period,
        "return_type": "GSTR-3B",
        "status": "AUTHORIZED",
    }]

    # Invalidate
    res = invalidate_gstr3b_approvals_and_consent(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        period=period,
    )
    assert res["invalidated_approvals"] == 1
    assert res["invalidated_consents"] == 1

    # Check updated statuses
    assert sb.tables["return_filing_approvals"][0]["status"] == "RESET"
    assert sb.tables["client_filing_authorizations"][0]["status"] == "REVOKED"


def test_gstr3b_suggestion_incorporates_gstr1a_deltas():
    """GSTR-3B load_osup_det_suggestion incorporates net GSTR-1A deltas."""
    sb = MockSupabase()
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    # GSTR-1 reconcile run baseline: 1,00,000 txval, 18,000 igst
    sb.tables["gstr1_reconciliation_run"] = [{
        "id": "run-g1-1",
        "client_gstin_id": client_gid,
        "period": period,
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 5,
                "gstr1": {
                    "taxable_value_paise": 10000000,
                    "igst_paise": 1800000,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                    "cess_paise": 0,
                },
            }
        },
    }]

    # GSTR-1A batch with +50,000 txval, +9,000 igst
    sb.tables["gstr1a_amendment_batches"] = [{
        "id": "batch-1",
        "client_gstin_id": client_gid,
        "period": period,
        "status": "APPROVED",
        "delta_taxable_value": 50000.00,
        "delta_igst": 9000.00,
        "delta_cgst": 0.00,
        "delta_sgst": 0.00,
        "delta_cess": 0.00,
        "total_additions": 1,
        "total_amendments": 0,
        "figures_digest": "mock-digest-123",
    }]

    sugg = load_osup_det_suggestion(sb, client_gstin_id=client_gid, period=period)
    assert sugg["available"] is True
    assert sugg["gstr1a_applied"] is True
    assert sugg["osup_det"]["txval"] == 150000.00
    assert sugg["osup_det"]["iamt"] == 27000.00


# ==============================================================================
# 5. PRE-FILING STATUTORY VALIDATION & FIGURES DIGEST
# ==============================================================================

def test_validate_gstr1a_pre_filing_clean():
    """Clean GSTR-1A batch passes pre-filing validation."""
    batch = {
        "client_gstin_id": "cg-1",
        "gstin": "27AAPFU0939F1ZV",
        "period": "2026-01",
        "total_additions": 1,
        "total_amendments": 0,
        "delta_taxable_value": 100000.0,
        "delta_igst": 18000.0,
        "figures_digest": "abc123hash",
    }
    items = [{
        "table_name": "4A",
        "action_type": "ADDITION",
        "recipient_gstin": "29AABCS1429B1Z2",  # Inter-state Karnataka (29) vs Maharashtra (27)
        "pos": "29",
        "delta_taxable_value": 100000.0,
        "delta_igst": 18000.0,
        "delta_cgst": 0.0,
        "delta_sgst": 0.0,
        "delta_cess": 0.0,
    }]

    val = validate_gstr1a_pre_filing(
        gstin="27AAPFU0939F1ZV",
        period="2026-01",
        batch=batch,
        items=items,
        gstr1_filed=True,
        gstr3b_filed=False,
    )
    assert val.is_valid is True
    assert val.overall_severity == ValidationSeverity.CLEAN
    assert val.return_type == "gstr-1a"


def test_validate_gstr1a_pre_filing_invalid_recipient_gstin():
    """Invalid recipient GSTIN produces CRITICAL_ERROR."""
    batch = {"figures_digest": "hash"}
    items = [{
        "table_name": "4A",
        "action_type": "ADDITION",
        "recipient_gstin": "INVALID_GSTIN_123",
        "pos": "29",
        "delta_igst": 1800.0,
    }]
    val = validate_gstr1a_pre_filing(
        gstin="27AAPFU0939F1ZV",
        period="2026-01",
        batch=batch,
        items=items,
        gstr1_filed=True,
        gstr3b_filed=False,
    )
    assert val.is_valid is False
    assert any(v.code == "G1A_INVALID_RECIPIENT_GSTIN" for v in val.violations)


# ==============================================================================
# 6. OFFICIAL OFFLINE GSTN JSON EXPORT
# ==============================================================================

def test_build_gstr1a_offline_json_structure():
    """Generates official GSTN offline tool JSON structure."""
    batch = {
        "gstin": "27AAPFU0939F1ZV",
        "period": "2026-01",
        "figures_digest": "canonical-hash-789",
    }
    items = [
        {
            "table_name": "4A",
            "action_type": "ADDITION",
            "amended_payload": {"inum": "INV-100", "val": 50000},
        },
        {
            "table_name": "9A_B2B",
            "action_type": "AMENDMENT",
            "original_invoice_number": "INV-50",
            "original_invoice_date": "2026-01-05",
            "amended_payload": {"inum": "INV-50-REV", "val": 60000},
        },
    ]
    export_data = build_gstr1a_offline_json(batch, items)
    assert export_data["gstin"] == "27AAPFU0939F1ZV"
    assert export_data["fp"] == "012026"
    assert export_data["version"] == "GSTR1A_v1.0"
    assert len(export_data["b2b"]) == 1
    assert export_data["b2b"][0]["inum"] == "INV-100"
    assert len(export_data["b2ba"]) == 1
    assert export_data["b2ba"][0]["oinum"] == "INV-50"


# ==============================================================================
# 7. SANDBOX FILING CLIENT METHODS
# ==============================================================================

def test_sandbox_client_save_gstr1a_success():
    """Sandbox client posts to /gstrs/gstr-1a/{year}/{month}."""
    client = SandboxFilingClient(api_key="test-key", api_secret="test-secret", base_url="https://api.sandbox.mock")
    with patch.object(client, "_request") as mock_req:
        mock_req.return_value = {
            "status_cd": "1",
            "data": {"reference_id": "REF-GSTR1A-999"},
        }
        res = client.save_gstr1a("taxpayer-tok", period="2026-01", save_body={"gstin": "27A..."})
        assert res.reference_id == "REF-GSTR1A-999"
        mock_req.assert_called_once()
        assert "/gstrs/gstr-1a/2026/01" in mock_req.call_args[0][1]


def test_sandbox_client_unsupported_by_gstn_api_handling():
    """When GSTN/GSP sandbox returns 501 or 404, maps to structured UNSUPPORTED_BY_GSTN_API error."""
    client = SandboxFilingClient(api_key="test-key", api_secret="test-secret", base_url="https://api.sandbox.mock")
    with patch.object(client, "_request", side_effect=FilingApiError("Endpoint not found", status_code=501)):
        with pytest.raises(FilingGstnError) as exc_info:
            client.save_gstr1a("taxpayer-tok", period="2026-01", save_body={"gstin": "27A..."})
        assert exc_info.value.error_cd == "UNSUPPORTED_BY_GSTN_API"


def test_gstr1a_window_late_gstr3b_allows_item_addition():
    """Rule 59(1A): Taxpayers filing GSTR-3B late can still add and curate GSTR-1A amendments prior to 3B filing."""
    sb = MockSupabase()
    firm_id = "00000000-0000-0000-0000-000000000001"
    client_gid = "00000000-0000-0000-0000-000000000002"
    gstin = "27AAPFU0939F1ZV"
    period = "2026-01"

    # Even if today is after the 20th, since GSTR-3B is unfiled, adding items succeeds
    item = add_or_update_amendment_item_sync(
        sb,
        firm_id=firm_id,
        client_gstin_id=client_gid,
        gstin=gstin,
        period=period,
        table_name="4A",
        action_type="ADDITION",
        amended_invoice_number="INV-LATE-01",
        amended_payload={"taxable_value": 50000, "igst": 9000},
        skip_window_check=False,
        gstr1_filed=True,
        gstr3b_filed=False,
    )
    assert item["amended_invoice_number"] == "INV-LATE-01"
    assert item["delta_taxable_value"] == 50000.0


def test_gstr3b_double_counting_prevented_when_already_in_baseline():
    """If baseline GSTR-1 run has already incorporated GSTR-1A deltas, do not compound them."""
    from app.filing.gstr3b_suggestions import load_osup_det_suggestion

    sb = MockSupabase()
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    sb.tables["gstr1_reconciliation_run"] = [{
        "id": "run-g1-already-inc",
        "client_gstin_id": client_gid,
        "period": period,
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 5,
                "gstr1a_applied": True,  # Already applied in baseline run!
                "gstr1": {
                    "taxable_value_paise": 10000000,
                    "igst_paise": 1800000,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                    "cess_paise": 0,
                },
            }
        },
    }]

    # Even with an active batch in DB
    sb.tables["gstr1a_amendment_batches"] = [{
        "id": "batch-1",
        "client_gstin_id": client_gid,
        "period": period,
        "status": "APPROVED",
        "delta_taxable_value": 25000.0,
        "delta_igst": 4500.0,
        "delta_cgst": 0.0,
        "delta_sgst": 0.0,
        "delta_cess": 0.0,
    }]

    sugg = load_osup_det_suggestion(sb, client_gstin_id=client_gid, period=period)
    assert sugg["available"] is True
    assert sugg["gstr1a_applied"] is True
    # The taxable value remains 100,000 without double-adding 25,000!
    assert sugg["osup_det"]["txval"] == 100000.0
    assert sugg["osup_det"]["iamt"] == 18000.0
    assert sugg["gstr1a"].get("already_incorporated_in_baseline") is True


def test_rejected_gstr1a_batch_does_not_flow_into_gstr3b():
    """If GSTR-1A batch was rejected in maker-checker review, deltas do not flow into GSTR-3B."""
    from app.filing.gstr3b_suggestions import load_osup_det_suggestion

    sb = MockSupabase()
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    sb.tables["gstr1_reconciliation_run"] = [{
        "id": "run-g1-base",
        "client_gstin_id": client_gid,
        "period": period,
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 5,
                "gstr1": {
                    "taxable_value_paise": 10000000,
                    "igst_paise": 1800000,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                    "cess_paise": 0,
                },
            }
        },
    }]

    sb.tables["gstr1a_amendment_batches"] = [{
        "id": "batch-rejected",
        "client_gstin_id": client_gid,
        "period": period,
        "status": "REJECTED",  # Rejected by Checker!
        "delta_taxable_value": 50000.0,
        "delta_igst": 9000.0,
        "delta_cgst": 0.0,
        "delta_sgst": 0.0,
        "delta_cess": 0.0,
    }]

    sugg = load_osup_det_suggestion(sb, client_gstin_id=client_gid, period=period)
    assert sugg["available"] is True
    # Should NOT have gstr1a_applied since batch is REJECTED
    assert "gstr1a_applied" not in sugg
    assert sugg["osup_det"]["txval"] == 100000.0
    assert sugg["osup_det"]["iamt"] == 18000.0


@pytest.mark.parametrize(
    "status, expected_applied",
    [
        ("DRAFT", False),
        ("PREPARED", False),
        ("UNDER_REVIEW", False),
        ("REJECTED", False),
        ("APPROVED", True),
        ("SAVED", True),
        ("FILED", True),
    ],
)
def test_every_batch_status_eligibility_for_gstr3b_table_3_1(status: str, expected_applied: bool):
    """Verify strictly that ONLY APPROVED, SAVED, and FILED GSTR-1A batches modify GSTR-3B Table 3.1."""
    from app.filing.gstr3b_suggestions import load_osup_det_suggestion

    sb = MockSupabase()
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    sb.tables["gstr1_reconciliation_run"] = [{
        "id": "run-g1-test",
        "client_gstin_id": client_gid,
        "period": period,
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 5,
                "gstr1": {
                    "taxable_value_paise": 10000000,
                    "igst_paise": 1800000,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                    "cess_paise": 0,
                },
            }
        },
    }]

    sb.tables["gstr1a_amendment_batches"] = [{
        "id": f"batch-{status.lower()}",
        "client_gstin_id": client_gid,
        "period": period,
        "status": status,
        "delta_taxable_value": 50000.0,
        "delta_igst": 9000.0,
        "delta_cgst": 0.0,
        "delta_sgst": 0.0,
        "delta_cess": 0.0,
    }]

    sugg = load_osup_det_suggestion(sb, client_gstin_id=client_gid, period=period)
    assert sugg["available"] is True
    if expected_applied:
        assert sugg.get("gstr1a_applied") is True
        assert sugg["osup_det"]["txval"] == 150000.0
        assert sugg["osup_det"]["iamt"] == 27000.0
    else:
        assert "gstr1a_applied" not in sugg
        assert sugg["osup_det"]["txval"] == 100000.0
        assert sugg["osup_det"]["iamt"] == 18000.0


def test_multiple_batches_do_not_duplicate_adjustments():
    """When multiple batches exist, only the single highest-priority eligible batch is applied."""
    from app.filing.gstr3b_suggestions import load_osup_det_suggestion

    sb = MockSupabase()
    client_gid = "00000000-0000-0000-0000-000000000002"
    period = "2026-01"

    sb.tables["gstr1_reconciliation_run"] = [{
        "id": "run-g1-multi",
        "client_gstin_id": client_gid,
        "period": period,
        "result_payload": {
            "tie_out": {
                "gstr1_record_count": 5,
                "gstr1": {
                    "taxable_value_paise": 10000000,
                    "igst_paise": 1800000,
                    "cgst_paise": 0,
                    "sgst_paise": 0,
                    "cess_paise": 0,
                },
            }
        },
    }]

    # Batch 1 (SAVED: 30,000 txval) and Batch 2 (APPROVED: 20,000 txval)
    sb.tables["gstr1a_amendment_batches"] = [
        {
            "id": "batch-saved",
            "client_gstin_id": client_gid,
            "period": period,
            "status": "SAVED",
            "delta_taxable_value": 30000.0,
            "delta_igst": 5400.0,
            "delta_cgst": 0.0,
            "delta_sgst": 0.0,
            "delta_cess": 0.0,
        },
        {
            "id": "batch-approved",
            "client_gstin_id": client_gid,
            "period": period,
            "status": "APPROVED",
            "delta_taxable_value": 20000.0,
            "delta_igst": 3600.0,
            "delta_cgst": 0.0,
            "delta_sgst": 0.0,
            "delta_cess": 0.0,
        },
    ]

    sugg = load_osup_det_suggestion(sb, client_gstin_id=client_gid, period=period)
    assert sugg["available"] is True
    assert sugg["gstr1a_applied"] is True
    # Takes only batch-saved (30,000), does NOT sum both (50,000)!
    assert sugg["osup_det"]["txval"] == 130000.0
    assert sugg["osup_det"]["iamt"] == 23400.0
    assert sugg["gstr1a"]["batch_id"] == "batch-saved"


