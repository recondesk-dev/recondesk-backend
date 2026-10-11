"""
Tests for Bulk GSTR-1 Multi-GSTIN Filing (filing_batches / filing_batch_items).

Priorities covered, in order of importance:
  1. test_partial_failure_isolation   — one GSTIN failing must not block/corrupt others
  2. test_retry_scope                  — retry must only touch failed/needs_review items
  3. test_dual_status_discipline       — outer "1" + inner "ER" must NOT mark item saved/filed
  4. test_batch_status_aggregation     — recalculate_batch_status must reflect item mix correctly

Run with:
    pytest tests/test_filing_batch.py -v
"""

from unittest.mock import MagicMock, patch
import pytest

from app.filing.filing_store import (
    create_batch,
    get_batch,
    recalculate_batch_status,
    update_batch_item,
)
from app.filing.gstr1_orchestrator import map_sales_register_to_gstr1
from app.filing.sandbox_filing_client import FilingApiResult, FilingClientError, ReturnStatusInfo
from app.routers.filing import retry_filing_batch
from app.worker.filing_batch_task import process_filing_batch


# ---------------------------------------------------------------------------
# Fake Supabase In-Memory Store
# ---------------------------------------------------------------------------

class FakeTable:
    def __init__(self, db, name):
        self.db = db
        self.name = name
        self.rows = self.db.setdefault(name, [])
        self._action = None
        self._insert_data = None
        self._update_data = None
        self._filters = []
        self._select_cols = "*"
        self._order_by = None
        self._limit_val = None

    def insert(self, data):
        self._action = "insert"
        self._insert_data = data
        return self

    def update(self, data):
        self._action = "update"
        self._update_data = data
        return self

    def select(self, cols="*"):
        self._action = "select"
        self._select_cols = cols
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, str(val)))
        return self

    def in_(self, col, vals):
        self._filters.append(("in", col, [str(v) for v in vals]))
        return self

    def order(self, col, desc=False):
        self._order_by = (col, desc)
        return self

    def limit(self, val):
        self._limit_val = val
        return self

    def single(self):
        return self

    def execute(self):
        import uuid
        res_data = []

        if self._action == "insert":
            raw_items = self._insert_data if isinstance(self._insert_data, list) else [self._insert_data]
            for item in raw_items:
                row = dict(item)
                if "id" not in row or not row["id"]:
                    row["id"] = str(uuid.uuid4())
                self.rows.append(row)
                res_data.append(row)
        elif self._action == "update":
            matching = self._get_matching_rows()
            for r in matching:
                r.update(self._update_data)
                res_data.append(r)
        elif self._action == "select":
            matching = self._get_matching_rows()
            if self._order_by:
                col, desc = self._order_by
                matching = sorted(matching, key=lambda x: str(x.get(col, "")), reverse=desc)
            if self._limit_val is not None:
                matching = matching[: self._limit_val]

            if "client_gstins" in self._select_cols:
                for r in matching:
                    cid = r.get("client_gstin_id")
                    cg_rows = self.db.get("client_gstins", [])
                    found = next((c for c in cg_rows if c.get("id") == cid), None)
                    r["client_gstins"] = found or {"trade_name": "Test Client", "legal_name": "Test Client Legal"}
            res_data = matching

        res = MagicMock()
        res.data = res_data
        return res

    def _get_matching_rows(self):
        matched = []
        for r in self.rows:
            keep = True
            for op, col, val in self._filters:
                r_val = str(r.get(col, ""))
                if op == "eq":
                    if r_val != val:
                        keep = False
                        break
                elif op == "in":
                    if r_val not in val:
                        keep = False
                        break
            if keep:
                matched.append(r)
        return matched


class FakeSupabase:
    def __init__(self):
        self.db = {}

    def table(self, name):
        return FakeTable(self.db, name)


class FakeFilingClient:
    def __init__(self, save_side_effect=None, save_return_value=None, status_side_effect=None, status_return_value=None):
        self.save_side_effect = save_side_effect
        self.save_return_value = save_return_value
        self.status_side_effect = status_side_effect
        self.status_return_value = status_return_value

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def save_gstr1(self, stoken, period, save_body):
        if self.save_side_effect:
            return self.save_side_effect(stoken, period, save_body)
        return self.save_return_value or FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-1"}}},
            reference_id="REF-1",
        )

    def get_return_status(self, stoken, period, reference_id):
        if self.status_side_effect:
            return self.status_side_effect(stoken, period, reference_id)
        return self.status_return_value or FilingApiResult(
            envelope={"data": {"status_cd": "P"}},
            return_status=ReturnStatusInfo(outer_status_cd="1", gstn_status_cd="P"),
        )

    def proceed_to_file(self, stoken, period, is_nil="N"):
        return FilingApiResult(
            envelope={"data": {"status_cd": "P"}},
            reference_id="REF-PROC",
            return_status=ReturnStatusInfo(outer_status_cd="1", gstn_status_cd="P"),
        )


def _b2b_sample_record(gstin: str):
    return {
        "gstin": gstin,
        "gstin_valid": True,
        "invoice_type": "B2B",
        "invoice_type_raw": "Tax Invoice",
        "invoice_number_raw": "B2B-001",
        "invoice_date": "2026-07-08",
        "place_of_supply": "27-Maharashtra",
        "reverse_charge": False,
        "taxable_amount_paise": 100000,
        "igst_paise": 0,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
        "cess_paise": 0,
        "total_tax_paise": 18000,
        "total_amount_paise": 118000,
        "tax_rate": 18.0,
        "hsn": "8203",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_gstins():
    """Three client GSTINs to use across batch tests."""
    return ["27AAAAA0000A1Z5", "27BBBBB1111B2Z6", "27CCCCC2222C3Z7"]


@pytest.fixture
def batch_with_three_items(sample_gstins):
    """
    Creates a real filing_batches row + 3 filing_batch_items rows via the
    actual store function.
    """
    sb = FakeSupabase()
    client_ids = []
    from app.services.maker_checker_service import _mc_store, ReturnApproval, ApprovalStatus
    for gstin in sample_gstins:
        cid = f"client-id-{gstin}"
        sb.table("client_gstins").insert({"id": cid, "gstin": gstin, "firm_owner_id": "test-firm-id"}).execute()
        client_ids.append(cid)
        # Seed Phase 3.2 maker-checker approval for batch worker execution
        _mc_store.put_approval(
            ReturnApproval(
                id=f"appr-{gstin}",
                firm_id="test-firm-id",
                client_gstin_id=cid,
                gstin=gstin,
                period="2026-07",
                return_type="GSTR-1",
                status=ApprovalStatus.APPROVED,
                approver_id="test-approver-id",
            )
        )

    batch = create_batch(
        sb,
        firm_id="test-firm-id",
        created_by="test-user-id",
        period="2026-07",
        client_gstin_ids=client_ids,
        return_type="gstr-1",
    )

    batch_id = batch["id"]
    return batch_id, sample_gstins, sb


# ---------------------------------------------------------------------------
# 1. PARTIAL-FAILURE ISOLATION (highest priority)
# ---------------------------------------------------------------------------

class TestPartialFailureIsolation:
    """
    A batch of N GSTINs where one fails must NOT block, roll back, or
    corrupt the others. Each GSTIN's status is independent.
    """

    def test_one_failure_does_not_block_others(self, batch_with_three_items):
        batch_id, gstins, sb = batch_with_three_items
        failing_gstin = gstins[1]

        def fake_save_gstr1(stoken, period, save_body):
            gstin = save_body.get("gstin")
            if gstin == failing_gstin:
                raise FilingClientError("Simulated GSTN Save failure")
            return FilingApiResult(
                envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-1"}}},
                reference_id="REF-1",
            )

        fake_client = FakeFilingClient(save_side_effect=fake_save_gstr1)

        def mock_fetch_sr(sb_arg, client_gstin_id, period):
            cg = next((c for c in sb.db.get("client_gstins", []) if c.get("id") == client_gstin_id), None)
            g = cg.get("gstin") if cg else "27AAAAA0000A1Z5"
            return [_b2b_sample_record(g)]

        with patch("app.worker.filing_batch_task.get_supabase", return_value=sb), patch(
            "app.worker.filing_batch_task.get_filing_client", return_value=fake_client
        ), patch(
            "app.worker.filing_batch_task.filing_store.get_active_session",
            return_value={"session_token": "tok123", "id": "sess1"},
        ), patch(
            "app.worker.filing_batch_task.fetch_sales_register_records",
            side_effect=mock_fetch_sr,
        ):
            process_filing_batch(batch_id)

        batch = get_batch(sb, batch_id)

        item_by_gstin = {item["gstin"]: item for item in batch["items"]}

        # the failing GSTIN is isolated to a failed/needs_review state
        assert item_by_gstin[failing_gstin]["status"] in (
            "failed",
            "needs_review",
        )

        # the OTHER two GSTINs completed normally, unaffected by the failure.
        # Save success (inner "P") auto-advances via proceed_to_file into
        # evc_pending (awaiting CA's EVC OTP) — that's the real terminal
        # state for a successful item in this pipeline, not "saved"/"filed".
        for gstin in gstins:
            if gstin == failing_gstin:
                continue
            assert item_by_gstin[gstin]["status"] in (
                "saved",
                "evc_pending",
                "filed",
            )

    def test_batch_status_reflects_partial_completion(
        self, batch_with_three_items
    ):
        batch_id, gstins, sb = batch_with_three_items
        failing_gstin = gstins[0]

        def fake_save_gstr1(stoken, period, save_body):
            gstin = save_body.get("gstin")
            if gstin == failing_gstin:
                raise FilingClientError("Simulated failure")
            return FilingApiResult(
                envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-1"}}},
                reference_id="REF-1",
            )

        fake_client = FakeFilingClient(save_side_effect=fake_save_gstr1)

        def mock_fetch_sr(sb_arg, client_gstin_id, period):
            cg = next((c for c in sb.db.get("client_gstins", []) if c.get("id") == client_gstin_id), None)
            g = cg.get("gstin") if cg else "27AAAAA0000A1Z5"
            return [_b2b_sample_record(g)]

        with patch("app.worker.filing_batch_task.get_supabase", return_value=sb), patch(
            "app.worker.filing_batch_task.get_filing_client", return_value=fake_client
        ), patch(
            "app.worker.filing_batch_task.filing_store.get_active_session",
            return_value={"session_token": "tok123", "id": "sess1"},
        ), patch(
            "app.worker.filing_batch_task.fetch_sales_register_records",
            side_effect=mock_fetch_sr,
        ):
            process_filing_batch(batch_id)

        batch = get_batch(sb, batch_id)

        # batch-level status must communicate "partial", not silently
        # report success or failure for the whole thing.
        # Schema enum name confirmed: "partially_completed"
        assert batch["status"] == "partially_completed"
        assert batch["failed_count"] == 1

        # "succeeded" isn't one field — the schema tracks granular per-state
        # counts. A GSTIN that reached evc_pending or filed both count as
        # having succeeded through Save; sum the relevant buckets.
        succeeded = (
            batch.get("saved_count", 0)
            + batch.get("evc_pending_count", 0)
            + batch.get("filed_count", 0)
        )
        assert succeeded == len(gstins) - 1


# ---------------------------------------------------------------------------
# 2. RETRY SCOPE
# ---------------------------------------------------------------------------

class TestRetryScope:
    """
    POST /batches/{id}/retry must only reset items in failed/needs_review.
    It must NOT touch items already saved/filed — re-triggering Save on an
    already-saved GSTIN risks duplicate submission or GSTN errors.
    """

    def test_retry_only_resets_failed_items(self, batch_with_three_items):
        batch_id, gstins, sb = batch_with_three_items
        batch = get_batch(sb, batch_id)
        items = batch["items"]

        # Manually set up a mixed state: one filed, one failed, one saved
        update_batch_item(sb, items[0]["id"], status="filed")
        update_batch_item(sb, items[1]["id"], status="failed")
        update_batch_item(sb, items[2]["id"], status="saved")

        user = {"id": "test-user-id", "role": "admin"}

        with patch("app.routers.filing.get_supabase", return_value=sb), patch(
            "app.routers.filing._firm_id", return_value="test-firm-id"
        ), patch(
            "app.worker.filing_batch_task.process_filing_batch.delay"
        ):
            retry_filing_batch(batch_id, current_user=user)

        batch = get_batch(sb, batch_id)
        item_by_gstin = {item["gstin"]: item for item in batch["items"]}

        # filed and saved items must be untouched
        assert item_by_gstin[gstins[0]]["status"] == "filed"
        assert item_by_gstin[gstins[2]]["status"] == "saved"

        # only the failed item is reset for reprocessing
        assert item_by_gstin[gstins[1]]["status"] in ("pending", "in_progress")

    def test_retry_on_fully_successful_batch_is_a_noop(
        self, batch_with_three_items
    ):
        batch_id, gstins, sb = batch_with_three_items
        batch = get_batch(sb, batch_id)
        for item in batch["items"]:
            update_batch_item(sb, item["id"], status="filed")

        user = {"id": "test-user-id", "role": "admin"}

        with patch("app.routers.filing.get_supabase", return_value=sb), patch(
            "app.routers.filing._firm_id", return_value="test-firm-id"
        ), patch(
            "app.worker.filing_batch_task.process_filing_batch.delay"
        ):
            retry_filing_batch(batch_id, current_user=user)

        batch = get_batch(sb, batch_id)
        # nothing should have changed — no items reset, no re-dispatch
        for item in batch["items"]:
            assert item["status"] == "filed"


# ---------------------------------------------------------------------------
# 3. DUAL-STATUS DISCIPLINE (the exact bug class caught twice in single-GSTIN)
# ---------------------------------------------------------------------------

class TestDualStatusDiscipline:
    """
    Sandbox's outer status_cd can be "1" (success) while GSTN's nested
    Return Status shows "ER" (error). A batch item must only be marked
    saved/filed once the INNER status is confirmed "P" — never on the
    outer status alone.
    """

    def test_outer_success_inner_error_does_not_mark_saved(
        self, batch_with_three_items
    ):
        batch_id, gstins, sb = batch_with_three_items
        target_gstin = gstins[0]

        fake_save_response = FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-1"}}},
            reference_id="REF-1",
        )
        fake_status_response = FilingApiResult(
            envelope={"data": {"status_cd": "ER", "error_report": {"error_code": "RET123", "error_msg": "Invalid JSON"}}},
            return_status=ReturnStatusInfo(outer_status_cd="1", gstn_status_cd="ER", error_cd="RET123", error_message="Invalid JSON"),
        )

        fake_client = FakeFilingClient(
            save_return_value=fake_save_response,
            status_return_value=fake_status_response,
        )

        def mock_fetch_sr(sb_arg, client_gstin_id, period):
            cg = next((c for c in sb.db.get("client_gstins", []) if c.get("id") == client_gstin_id), None)
            g = cg.get("gstin") if cg else "27AAAAA0000A1Z5"
            return [_b2b_sample_record(g)]

        with patch("app.worker.filing_batch_task.get_supabase", return_value=sb), patch(
            "app.worker.filing_batch_task.get_filing_client", return_value=fake_client
        ), patch(
            "app.worker.filing_batch_task.filing_store.get_active_session",
            return_value={"session_token": "tok123", "id": "sess1"},
        ), patch(
            "app.worker.filing_batch_task.fetch_sales_register_records",
            side_effect=mock_fetch_sr,
        ):
            process_filing_batch(batch_id)

        batch = get_batch(sb, batch_id)
        item = next(i for i in batch["items"] if i["gstin"] == target_gstin)

        # must NOT be marked saved/filed despite outer "1"
        assert item["status"] not in ("saved", "filed")
        assert item["status"] in ("failed", "needs_review")

    def test_inner_p_status_is_required_to_mark_saved(
        self, batch_with_three_items
    ):
        batch_id, gstins, sb = batch_with_three_items
        target_gstin = gstins[0]

        fake_save_response = FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-1"}}},
            reference_id="REF-1",
        )
        fake_status_response = FilingApiResult(
            envelope={"data": {"status_cd": "P"}},
            return_status=ReturnStatusInfo(outer_status_cd="1", gstn_status_cd="P"),
        )

        fake_client = FakeFilingClient(
            save_return_value=fake_save_response,
            status_return_value=fake_status_response,
        )

        def mock_fetch_sr(sb_arg, client_gstin_id, period):
            cg = next((c for c in sb.db.get("client_gstins", []) if c.get("id") == client_gstin_id), None)
            g = cg.get("gstin") if cg else "27AAAAA0000A1Z5"
            return [_b2b_sample_record(g)]

        with patch("app.worker.filing_batch_task.get_supabase", return_value=sb), patch(
            "app.worker.filing_batch_task.get_filing_client", return_value=fake_client
        ), patch(
            "app.worker.filing_batch_task.filing_store.get_active_session",
            return_value={"session_token": "tok123", "id": "sess1"},
        ), patch(
            "app.worker.filing_batch_task.fetch_sales_register_records",
            side_effect=mock_fetch_sr,
        ):
            process_filing_batch(batch_id)

        batch = get_batch(sb, batch_id)
        item = next(i for i in batch["items"] if i["gstin"] == target_gstin)

        # inner "P" confirms Save, which auto-advances to evc_pending
        # (via proceed_to_file) rather than stopping at "saved"
        assert item["status"] in ("saved", "evc_pending", "filed")


# ---------------------------------------------------------------------------
# 4. BATCH STATUS AGGREGATION (recalculate_batch_status direct unit tests)
# ---------------------------------------------------------------------------

class TestBatchStatusAggregation:
    """
    Direct tests on recalculate_batch_status with different item-status
    mixes — this is the function driving what the CA sees on the dashboard.
    """

    def _eval_status(self, item_statuses):
        sb = FakeSupabase()
        client_ids = [f"client-id-{i}" for i in range(len(item_statuses))]
        batch = create_batch(
            sb,
            firm_id="test-firm-id",
            created_by="test-user-id",
            period="2026-07",
            client_gstin_ids=client_ids,
            return_type="gstr-1",
        )
        batch_id = batch["id"]
        for item, st in zip(batch["items"], item_statuses):
            update_batch_item(sb, item["id"], status=st)

        res = recalculate_batch_status(sb, batch_id)
        return res["status"]

    def test_all_filed_is_completed(self):
        statuses = ["filed", "filed", "filed"]
        result = self._eval_status(statuses)
        assert result == "completed"

    def test_all_failed_is_failed(self):
        statuses = ["failed", "failed", "failed"]
        result = self._eval_status(statuses)
        assert result == "failed"

    def test_mixed_success_and_failure_is_partial(self):
        statuses = ["filed", "failed", "saved"]
        result = self._eval_status(statuses)
        assert result == "partially_completed"

    def test_mixed_evc_pending_and_failure_is_partial(self):
        statuses = ["evc_pending", "failed", "evc_pending"]
        result = self._eval_status(statuses)
        assert result == "partially_completed"

    def test_any_in_progress_is_not_terminal(self):
        statuses = ["filed", "in_progress", "pending"]
        result = self._eval_status(statuses)
        assert result in ("in_progress", "processing")

    def test_empty_batch_is_handled_gracefully(self):
        result = self._eval_status([])
        assert result is not None
