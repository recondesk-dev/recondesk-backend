"""Regression tests for Review Required (rr:) disposition ID validation and hydration.

Addresses Phase 5.7 REM-01:
- Defect 1: rr: record validation in _assert_record_ids_in_run
- Defect 2: Review Required decision-status hydration in _build_matched_pair_records
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from app.routers.reconciliation_api import (
    _assert_record_ids_in_run,
    _build_matched_pair_records,
)
from app.services.reconciliation_outcomes import OutcomeRow

RUN_ID = "e04d2e4f-d316-4836-bbd8-cde22dc658b8"
OTHER_RUN_ID = "11111111-2222-3333-4444-555555555555"
RR_UUID = "003e437b-6697-47fe-a07a-3846def231cf"
RR_TAGGED_ID = f"rr:{RR_UUID}"
UNRELATED_RR_ID = "rr:ffffffff-ffff-ffff-ffff-ffffffffffff"


def _make_sample_payload(gstr_id: str, pr_id: str = "pr-uuid-01") -> dict:
    """Construct a minimal reconciliation payload with a review_required entry."""
    en_row = {
        "gstr_id": gstr_id,
        "pr_id": pr_id,
        "side": "GSTR",
        "reason": "GSTIN_MISMATCH",
        "supplier_gstin": "27AABCU9603R1ZN",
        "invoice_number_normalized": "INV-001",
        "invoice_date": "2024-04-10",
        "confidence_score": 85.0,
        "total_tax_paise": 18000,
        "match_level": 2,
    }
    return {
        "engine": {
            "matched": [],
            "duplicates": [en_row],
            "review_required_typo": [],
            "missed_itc": [],
            "wrongful_risk": [],
        },
        "decisions": {"rows": []},
    }


def _make_sample_outcome_rows(gstr_id: str) -> list[OutcomeRow]:
    return [
        OutcomeRow(
            id=f"rrp:{gstr_id}-pr-01",
            category="review_required",
            supplier_gstin="27AABCU9603R1ZN",
            supplier_name="Acme Corp",
            invoice_number="INV-001",
            invoice_date="2024-04-10",
            match_status="REVIEW_REQUIRED",
            taxable_value_diff=0,
            igst_diff=0,
            cgst_diff=0,
            sgst_diff=0,
            total_tax_diff_paise=0,
            decision_what="Gstin Mismatch",
            decision_why="GSTIN_MISMATCH",
            decision_next="Manual review required",
            rule37_flag=False,
            blocked_credit_flag=False,
            late_filing_flag=False,
            is_credit_note=False,
            amount=18000,
            itc_available=True,
        )
    ]


# ---------------------------------------------------------------------------
# Defect 1: rr: Validation in _assert_record_ids_in_run
# ---------------------------------------------------------------------------

@patch("app.routers.reconciliation_api._source_software_for_run", return_value="tally")
@patch("app.routers.reconciliation_api._notes_count_for_run", return_value={})
@patch("app.routers.reconciliation_api._payload_or_404")
@patch("app.routers.reconciliation_api.ro.load_gstr_map")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
@patch("app.routers.reconciliation_api.ro.build_outcome_rows")
def test_assert_record_ids_in_run_rr_success(
    mock_build_outcome_rows: MagicMock,
    mock_load_pr_map: MagicMock,
    mock_load_gstr_map: MagicMock,
    mock_payload_or_404: MagicMock,
    mock_notes_count: MagicMock,
    mock_source_software: MagicMock,
):
    """An rr: tagged record belonging to the current run must pass validation."""
    mock_payload_or_404.return_value = _make_sample_payload(RR_UUID)
    mock_load_gstr_map.return_value = {
        RR_UUID: {"matcher": {"total_tax_paise": 18000}, "record_data": {}}
    }
    mock_load_pr_map.return_value = {}
    mock_build_outcome_rows.return_value = (_make_sample_outcome_rows(RR_UUID), {})

    mock_sb = MagicMock()
    # Must succeed without raising HTTPException
    _assert_record_ids_in_run(mock_sb, RUN_ID, [RR_TAGGED_ID])


@patch("app.routers.reconciliation_api._source_software_for_run", return_value="tally")
@patch("app.routers.reconciliation_api._notes_count_for_run", return_value={})
@patch("app.routers.reconciliation_api._payload_or_404")
@patch("app.routers.reconciliation_api.ro.load_gstr_map")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
@patch("app.routers.reconciliation_api.ro.build_outcome_rows")
def test_assert_record_ids_in_run_rr_unrelated_rejected(
    mock_build_outcome_rows: MagicMock,
    mock_load_pr_map: MagicMock,
    mock_load_gstr_map: MagicMock,
    mock_payload_or_404: MagicMock,
    mock_notes_count: MagicMock,
    mock_source_software: MagicMock,
):
    """An rr: tagged record with an unrelated UUID must be rejected with 404."""
    mock_payload_or_404.return_value = _make_sample_payload(RR_UUID)
    mock_load_gstr_map.return_value = {
        RR_UUID: {"matcher": {"total_tax_paise": 18000}, "record_data": {}}
    }
    mock_load_pr_map.return_value = {}
    mock_build_outcome_rows.return_value = (_make_sample_outcome_rows(RR_UUID), {})

    mock_sb = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        _assert_record_ids_in_run(mock_sb, RUN_ID, [UNRELATED_RR_ID])

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert f"record not found in this run: {UNRELATED_RR_ID}" in str(exc_info.value.detail)


@patch("app.routers.reconciliation_api._source_software_for_run", return_value="tally")
@patch("app.routers.reconciliation_api._notes_count_for_run", return_value={})
@patch("app.routers.reconciliation_api._payload_or_404")
@patch("app.routers.reconciliation_api.ro.load_gstr_map")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
@patch("app.routers.reconciliation_api.ro.build_outcome_rows")
def test_assert_record_ids_in_run_rr_from_other_run_rejected(
    mock_build_outcome_rows: MagicMock,
    mock_load_pr_map: MagicMock,
    mock_load_gstr_map: MagicMock,
    mock_payload_or_404: MagicMock,
    mock_notes_count: MagicMock,
    mock_source_software: MagicMock,
):
    """An rr: record from run A must be rejected when queried against run B."""
    # OTHER_RUN_ID has a completely different record in its payload
    other_uuid = "22222222-2222-2222-2222-222222222222"
    mock_payload_or_404.return_value = _make_sample_payload(other_uuid)
    mock_load_gstr_map.return_value = {
        other_uuid: {"matcher": {"total_tax_paise": 18000}, "record_data": {}}
    }
    mock_load_pr_map.return_value = {}
    mock_build_outcome_rows.return_value = (_make_sample_outcome_rows(other_uuid), {})

    mock_sb = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        _assert_record_ids_in_run(mock_sb, OTHER_RUN_ID, [RR_TAGGED_ID])

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert f"record not found in this run: {RR_TAGGED_ID}" in str(exc_info.value.detail)


# ---------------------------------------------------------------------------
# Defect 2: Review Required Decision Status Hydration
# ---------------------------------------------------------------------------

@patch("app.routers.reconciliation_api.ro.load_gstr_map")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
def test_build_matched_pair_records_hydrates_decision_status(
    mock_load_pr_map: MagicMock,
    mock_load_gstr_map: MagicMock,
):
    """Review Required records must hydrate their decision_status from decision_statuses."""
    mock_load_gstr_map.return_value = {
        RR_UUID: {"matcher": {"total_tax_paise": 18000}, "record_data": {}}
    }
    mock_load_pr_map.return_value = {}
    payload = _make_sample_payload(RR_UUID)
    outcomes = _make_sample_outcome_rows(RR_UUID)

    # 1. Stored status "acted" for bare UUID
    decision_map = {RR_UUID: "acted"}
    pairs = _build_matched_pair_records(
        None,
        rid=RUN_ID,
        payload=payload,
        note_counts={},
        fetch_review_required=True,
        precomputed_outcome_rows=outcomes,
        decision_statuses=decision_map,
    )
    assert len(pairs) == 1
    api_row, _ = pairs[0]
    assert api_row["id"] == RR_TAGGED_ID
    assert api_row["decision_status"] == "acted"

    # 2. Stored status "ignored" for bare UUID
    decision_map_ignored = {RR_UUID: "ignored"}
    pairs_ignored = _build_matched_pair_records(
        None,
        rid=RUN_ID,
        payload=payload,
        note_counts={},
        fetch_review_required=True,
        precomputed_outcome_rows=outcomes,
        decision_statuses=decision_map_ignored,
    )
    assert pairs_ignored[0][0]["decision_status"] == "ignored"

    # 3. No stored status defaults to "pending"
    pairs_pending = _build_matched_pair_records(
        None,
        rid=RUN_ID,
        payload=payload,
        note_counts={},
        fetch_review_required=True,
        precomputed_outcome_rows=outcomes,
        decision_statuses={},
    )
    assert pairs_pending[0][0]["decision_status"] == "pending"


# ---------------------------------------------------------------------------
# API Endpoint Integration: PATCH /api/reconcile/records/bulk-update
# ---------------------------------------------------------------------------

class FakeSupabaseForMismatchNotes:
    """In-memory Supabase mock testing real persistence without mocking helpers."""

    def __init__(self):
        self.rows: list[dict] = []
        self._filter_run: str | None = None
        self._filter_rec: str | None = None
        self._is_delete: bool = False

    def table(self, table_name: str):
        if table_name == "mismatch_notes":
            return self
        return MagicMock()

    def select(self, *args, **kwargs):
        self._filter_run = None
        self._filter_rec = None
        self._is_delete = False
        return self

    def delete(self, *args, **kwargs):
        self._filter_run = None
        self._filter_rec = None
        self._is_delete = True
        return self

    def insert(self, data: dict):
        self.rows.append(dict(data))
        return MagicMock(execute=lambda: MagicMock(data=[data]))

    def eq(self, col: str, val: Any):
        if col == "run_id":
            self._filter_run = val
        elif col == "record_id":
            self._filter_rec = val
        return self

    def execute(self):
        if self._is_delete:
            if self._filter_rec is not None:
                self.rows = [
                    r for r in self.rows
                    if not (r.get("run_id") == self._filter_run and r.get("record_id") == self._filter_rec)
                ]
            self._is_delete = False
            return MagicMock(data=[])
        filtered = self.rows
        if self._filter_run:
            filtered = [r for r in filtered if r.get("run_id") == self._filter_run]
        return MagicMock(data=filtered)


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
@patch("app.routers.reconciliation_api._payload_or_404")
@patch("app.routers.reconciliation_api._notes_count_for_run", return_value={})
@patch("app.routers.reconciliation_api._source_software_for_run", return_value="tally")
@patch("app.routers.reconciliation_api.ro.load_gstr_map")
@patch("app.routers.reconciliation_api.ro.load_pr_map")
@patch("app.routers.reconciliation_api.ro.build_outcome_rows")
@patch("app.routers.reconciliation_api.invalidate_run_bucket_cache")
def test_bulk_update_and_hydration_end_to_end(
    mock_invalidate: MagicMock,
    mock_build_outcome_rows: MagicMock,
    mock_load_pr_map: MagicMock,
    mock_load_gstr_map: MagicMock,
    mock_source_software: MagicMock,
    mock_notes_count: MagicMock,
    mock_payload_or_404: MagicMock,
    mock_get_supabase: MagicMock,
    mock_assert_run: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Real endpoint call through unmocked validation, prefix-stripping insert, and hydration."""
    fake_sb = FakeSupabaseForMismatchNotes()
    mock_get_supabase.return_value = fake_sb
    mock_assert_run.return_value = {"id": RUN_ID, "is_locked": False, "status": "DRAFT"}

    payload = _make_sample_payload(RR_UUID)
    outcomes = _make_sample_outcome_rows(RR_UUID)
    mock_payload_or_404.return_value = payload
    mock_load_gstr_map.return_value = {
        RR_UUID: {"matcher": {"total_tax_paise": 18000}, "record_data": {}}
    }
    mock_load_pr_map.return_value = {}
    mock_build_outcome_rows.return_value = (outcomes, {})

    # 1. Issue real PATCH /api/reconcile/records/bulk-update (unmocked validation + unmocked upsert)
    body = {
        "run_id": RUN_ID,
        "record_ids": [RR_TAGGED_ID],
        "decision_status": "acted",
    }
    res = client.patch("/api/reconcile/records/bulk-update", json=body, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"updated_count": 1}

    # 2. Verify that mismatch_notes table persisted the bare UUID (prefix stripped)
    assert len(fake_sb.rows) == 1
    persisted = fake_sb.rows[0]
    assert persisted["record_id"] == RR_UUID, "Must store bare UUID in mismatch_notes, not tagged rr: ID"
    assert persisted["note"] == "acted"
    assert persisted["note_type"] == "decision_status"
    assert persisted["run_id"] == RUN_ID

    # 3. Simulate SWR re-fetch: call _build_matched_pair_records with fake_sb
    pairs = _build_matched_pair_records(
        fake_sb,
        rid=RUN_ID,
        payload=payload,
        note_counts={},
        fetch_review_required=True,
    )
    assert len(pairs) == 1
    api_row, _ = pairs[0]
    assert api_row["id"] == RR_TAGGED_ID
    assert api_row["decision_status"] == "acted", "Re-fetched outcome row must hydrate 'acted' from DB"


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
@patch("app.routers.reconciliation_api._assert_record_ids_in_run")
@patch("app.routers.reconciliation_api._upsert_decision_status")
def test_bulk_update_rr_mark_as_acted(
    mock_upsert: MagicMock,
    mock_assert_records: MagicMock,
    mock_get_supabase: MagicMock,
    mock_assert_run: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Mark as Acted via /records/bulk-update succeeds for Review Required record."""
    mock_assert_run.return_value = {"id": RUN_ID, "is_locked": False, "status": "DRAFT"}
    mock_get_supabase.return_value = MagicMock()

    body = {
        "run_id": RUN_ID,
        "record_ids": [RR_TAGGED_ID],
        "decision_status": "acted",
    }
    res = client.patch("/api/reconcile/records/bulk-update", json=body, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"updated_count": 1}

    mock_assert_records.assert_called_once()
    mock_upsert.assert_called_once_with(
        mock_get_supabase.return_value,
        run_id=RUN_ID,
        record_id=RR_TAGGED_ID,
        status_value="acted",
        user_id="00000000-0000-0000-0000-000000000001",
    )


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
@patch("app.routers.reconciliation_api._assert_record_ids_in_run")
@patch("app.routers.reconciliation_api._upsert_decision_status")
def test_bulk_update_rr_mark_as_ignored(
    mock_upsert: MagicMock,
    mock_assert_records: MagicMock,
    mock_get_supabase: MagicMock,
    mock_assert_run: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Mark as Ignored via /records/bulk-update succeeds for Review Required record."""
    mock_assert_run.return_value = {"id": RUN_ID, "is_locked": False, "status": "DRAFT"}
    mock_get_supabase.return_value = MagicMock()

    body = {
        "run_id": RUN_ID,
        "record_ids": [RR_TAGGED_ID],
        "decision_status": "ignored",
    }
    res = client.patch("/api/reconcile/records/bulk-update", json=body, headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"updated_count": 1}

    mock_upsert.assert_called_once_with(
        mock_get_supabase.return_value,
        run_id=RUN_ID,
        record_id=RR_TAGGED_ID,
        status_value="ignored",
        user_id="00000000-0000-0000-0000-000000000001",
    )


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
def test_bulk_update_locked_run_rejected(
    mock_get_supabase: MagicMock,
    mock_assert_run: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Updating decisions on a locked or final run must return HTTP 409 Conflict."""
    mock_assert_run.return_value = {"id": RUN_ID, "is_locked": True, "status": "DRAFT"}
    mock_get_supabase.return_value = MagicMock()

    body = {
        "run_id": RUN_ID,
        "record_ids": [RR_TAGGED_ID],
        "decision_status": "acted",
    }
    res = client.patch("/api/reconcile/records/bulk-update", json=body, headers=auth_headers)
    assert res.status_code == 409
    assert "locked or final runs cannot be modified" in res.json()["detail"]


@patch("app.routers.reconciliation_api.assert_run_accessible")
@patch("app.routers.reconciliation_api.get_supabase")
def test_bulk_update_final_run_rejected(
    mock_get_supabase: MagicMock,
    mock_assert_run: MagicMock,
    client: TestClient,
    auth_headers: dict,
):
    """Updating decisions on a finalized run must return HTTP 409 Conflict."""
    mock_assert_run.return_value = {"id": RUN_ID, "is_locked": False, "status": "FINAL"}
    mock_get_supabase.return_value = MagicMock()

    body = {
        "run_id": RUN_ID,
        "record_ids": [RR_TAGGED_ID],
        "decision_status": "acted",
    }
    res = client.patch("/api/reconcile/records/bulk-update", json=body, headers=auth_headers)
    assert res.status_code == 409
    assert "locked or final runs cannot be modified" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Existing Prefixes Preservation: mi:, wr:, pm:, r37:, s175:
# ---------------------------------------------------------------------------

@patch("app.routers.reconciliation_api._source_software_for_run", return_value="tally")
@patch("app.routers.reconciliation_api._notes_count_for_run", return_value={})
@patch("app.routers.reconciliation_api._payload_or_404")
@patch("app.routers.reconciliation_api._build_missed_itc_records")
@patch("app.routers.reconciliation_api._build_wrongful_risk_records")
@patch("app.routers.reconciliation_api._build_matched_pair_records")
@patch("app.routers.reconciliation_api._build_rule37_rows")
@patch("app.routers.reconciliation_api._build_section175_rows")
def test_assert_record_ids_in_run_existing_prefixes_preserved(
    mock_build_s175: MagicMock,
    mock_build_r37: MagicMock,
    mock_build_matched: MagicMock,
    mock_build_risk: MagicMock,
    mock_build_missed: MagicMock,
    mock_payload_or_404: MagicMock,
    mock_notes_count: MagicMock,
    mock_source_software: MagicMock,
):
    """Existing prefixes (mi:, wr:, pm:, r37:, s175:) continue to be validated."""
    mock_payload_or_404.return_value = {"engine": {}, "decisions": {}}
    mock_build_missed.return_value = [{"id": "mi:uuid-1"}]
    mock_build_risk.return_value = [{"id": "wr:uuid-2"}]
    mock_build_matched.return_value = [({"id": "pm:uuid-3"}, None)]
    mock_build_r37.return_value = [{"id": "r37:hash-4"}]
    mock_build_s175.return_value = [{"id": "s175:uuid-5"}]

    mock_sb = MagicMock()

    # All existing prefixes must succeed
    _assert_record_ids_in_run(mock_sb, RUN_ID, ["mi:uuid-1"])
    _assert_record_ids_in_run(mock_sb, RUN_ID, ["wr:uuid-2"])
    _assert_record_ids_in_run(mock_sb, RUN_ID, ["pm:uuid-3"])
    _assert_record_ids_in_run(mock_sb, RUN_ID, ["r37:hash-4"])
    _assert_record_ids_in_run(mock_sb, RUN_ID, ["s175:uuid-5"])

    # Reject unknown IDs with existing prefix
    with pytest.raises(HTTPException) as exc_info:
        _assert_record_ids_in_run(mock_sb, RUN_ID, ["mi:unrelated-uuid"])
    assert exc_info.value.status_code == 404

