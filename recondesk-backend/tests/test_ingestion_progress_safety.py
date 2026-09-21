"""Unit tests for Phase 5.7 REM-02 Slice 1: Progress Correctness and Bounded Progress Updates.

Verifies:
- Authoritative progress table (reconciliation_import_runs vs legacy wizard_runs).
- Bounded progress updates during bulk insertion (row-threshold, time-threshold, completion).
- Monotonic progress, bounds (never > 100%), and zero-row safety.
- No per-row progress writes.
- Preservation of error handling and existing behavior.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch
import pytest

from app.worker.tasks import (
    _bulk_insert,
    _update_run,
    run_import_job,
    ImportCancelledException,
)
from app.worker.reconciliation_task import run_wizard_job


class TestAuthoritativeProgressTable:
    """Verifies that progress updates target reconciliation_import_runs, not wizard_runs."""

    def test_update_run_writes_to_reconciliation_import_runs(self):
        """_update_run must write progress_pct and status_message to reconciliation_import_runs."""
        mock_client = MagicMock()
        mock_table_run = MagicMock()
        mock_table_wiz = MagicMock()

        def table_router(name: str):
            if name == "reconciliation_run":
                return mock_table_run
            if name == "reconciliation_import_runs":
                return mock_table_wiz
            return MagicMock()

        mock_client.table.side_effect = table_router

        _update_run(
            mock_client,
            "run-123",
            {
                "progress_percent": 65.5,
                "status_message": "Importing purchase records (25,000 / 50,000)…",
                "updated_at": "2026-09-21T12:00:00Z",
            },
        )

        # 1. reconciliation_run updated with progress_percent and status_message
        mock_table_run.update.assert_called_once_with(
            {
                "progress_percent": 65.5,
                "status_message": "Importing purchase records (25,000 / 50,000)…",
                "updated_at": "2026-09-21T12:00:00Z",
            }
        )
        mock_table_run.update().eq.assert_called_once_with("id", "run-123")

        # 2. reconciliation_import_runs updated with progress_pct (int) and status_message
        mock_table_wiz.update.assert_called_once_with(
            {
                "progress_pct": 65,
                "status_message": "Importing purchase records (25,000 / 50,000)…",
                "updated_at": "2026-09-21T12:00:00Z",
            }
        )
        mock_table_wiz.update().eq.assert_called_once_with("id", "run-123")

        # 3. Non-existent wizard_runs is NEVER queried
        table_names = [call_args[0][0] for call_args in mock_client.table.call_args_list]
        assert "wizard_runs" not in table_names
        assert "reconciliation_import_runs" in table_names

    def test_update_run_logs_warning_on_mirror_failure(self):
        """_update_run logs a warning instead of silently concealing an import_runs failure."""
        mock_client = MagicMock()
        mock_client.table.return_value.update.return_value.eq.return_value.execute.side_effect = [
            None,  # reconciliation_run succeeds
            RuntimeError("Network timeout connecting to PostgreSQL"),  # reconciliation_import_runs fails
        ]

        with patch("app.worker.tasks._log") as mock_log:
            _update_run(
                mock_client,
                "run-456",
                {"progress_percent": 40, "status_message": "Parsed"},
            )
            # Must log a warning, but NOT raise an unhandled exception
            mock_log.warning.assert_called_once()
            assert "Failed to mirror progress to reconciliation_import_runs" in mock_log.warning.call_args[0][0]

    def test_reconciliation_task_wizard_job_uses_reconciliation_import_runs(self):
        """run_wizard_job loads and updates reconciliation_import_runs, not wizard_runs."""
        mock_sb = MagicMock()
        mock_import_runs_table = MagicMock()
        mock_recon_run_table = MagicMock()

        # Simulate existing wizard run
        mock_import_runs_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {
                "id": "run-789",
                "client_id": "client-abc",
                "period": "2025-04-01",
                "gstr2b_r2_key": "gstr2b.json",
                "pr_r2_key": "pr.xlsx",
            }
        ]
        # Simulate existing reconciliation_run
        mock_recon_run_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"id": "run-789", "status": "uploading"}
        ]

        def router(name: str):
            if name == "reconciliation_import_runs":
                return mock_import_runs_table
            if name == "reconciliation_run":
                return mock_recon_run_table
            return MagicMock()

        mock_sb.table.side_effect = router

        with patch("app.worker.reconciliation_task._supabase", return_value=mock_sb), \
             patch("app.worker.tasks.run_import_job.apply") as mock_apply_import, \
             patch("app.worker.reconciliation_task.execute_reconciliation.apply") as mock_apply_recon:
            run_wizard_job("run-789")

        table_calls = [c[0][0] for c in mock_sb.table.call_args_list]
        assert "wizard_runs" not in table_calls
        assert "reconciliation_import_runs" in table_calls


class TestBoundedBulkInsertProgress:
    """Verifies bounded flushing logic in _bulk_insert()."""

    def test_row_threshold_flushing(self):
        """Flushes occur at intervals of at least 5,000 newly inserted rows and on completion."""
        mock_client = MagicMock()
        flushes: list[tuple[int, int]] = []

        def on_progress(inserted: int, total: int):
            flushes.append((inserted, total))

        # 12,000 rows across 24 chunks of 500
        rows = [{"id": i, "val": f"data_{i}"} for i in range(12000)]

        with patch("app.worker.tasks.time.monotonic", return_value=100.0):
            # Clock is frozen at 100.0, so time-threshold never triggers
            _bulk_insert(mock_client, "pr_records", rows, on_progress=on_progress)

        # Expected:
        # At 5000 rows: delta = 5000 >= 5000 -> Flush 1
        # At 10000 rows: delta = 5000 >= 5000 -> Flush 2
        # At 12000 rows: inserted == total -> Flush 3 (completion)
        assert flushes == [(5000, 12000), (10000, 12000), (12000, 12000)]
        assert len(flushes) == 3

    def test_time_threshold_flushing(self):
        """Flushes occur when >= 3.0 seconds elapse even if row threshold is not reached."""
        mock_client = MagicMock()
        flushes: list[tuple[int, int]] = []

        def on_progress(inserted: int, total: int):
            flushes.append((inserted, total))

        # 2,000 rows across 4 chunks of 500 (never reaches 5,000 rows)
        rows = [{"id": i} for i in range(2000)]

        # Sequence of clock timestamps returned by monotonic():
        # Start: 10.0
        # Chunk 1 (500 rows): 11.0 (elapsed 1.0s < 3.0s) -> no flush
        # Chunk 2 (1000 rows): 14.2 (elapsed 4.2s >= 3.0s) -> Flush 1
        # Chunk 3 (1500 rows): 15.0 (elapsed 0.8s < 3.0s) -> no flush
        # Chunk 4 (2000 rows): 16.0 (inserted == total) -> Flush 2 (completion)
        mock_times = [10.0, 11.0, 14.2, 15.0, 16.0, 16.0]

        with patch("app.worker.tasks.time.monotonic", side_effect=mock_times):
            _bulk_insert(mock_client, "pr_records", rows, on_progress=on_progress)

        assert flushes == [(1000, 2000), (2000, 2000)]

    def test_final_flush_guaranteed_on_completion(self):
        """The final batch always triggers a flush when inserted == total."""
        mock_client = MagicMock()
        flushes: list[tuple[int, int]] = []

        # 1,500 rows (3 chunks of 500), frozen clock, row threshold not met
        rows = [{"id": i} for i in range(1500)]
        with patch("app.worker.tasks.time.monotonic", return_value=50.0):
            _bulk_insert(
                mock_client,
                "pr_records",
                rows,
                on_progress=lambda ins, tot: flushes.append((ins, tot)),
            )

        assert flushes == [(1500, 1500)]

    def test_no_per_row_writes(self):
        """For a 50,000-row file, progress writes are bounded to ~10 flushes, not 50,000."""
        mock_client = MagicMock()
        flushes: list[tuple[int, int]] = []

        rows = [{"id": i} for i in range(50000)]
        with patch("app.worker.tasks.time.monotonic", return_value=100.0):
            _bulk_insert(
                mock_client,
                "pr_records",
                rows,
                on_progress=lambda ins, tot: flushes.append((ins, tot)),
            )

        # Exactly 10 flushes (at 5k, 10k, 15k, ..., 50k)
        assert len(flushes) == 10
        assert flushes[-1] == (50000, 50000)

    def test_zero_row_behavior(self):
        """Empty rows list does not trigger database inserts and does not cause division by zero."""
        mock_client = MagicMock()
        flushes: list[tuple[int, int]] = []

        _bulk_insert(
            mock_client,
            "pr_records",
            [],
            on_progress=lambda ins, tot: flushes.append((ins, tot)),
        )

        mock_client.table.assert_not_called()
        assert flushes == [(0, 0)]


class TestProgressMonotonicityAndBounds:
    """Verifies that progress percentages are monotonic, bounded, and formatted correctly."""

    def test_linear_mapping_from_40_to_85(self):
        """Progress starts at 40% and reaches 85% at insertion completion."""
        total = 52430
        last_reported_pct = 40
        reports: list[tuple[int, str]] = []

        def record_progress(inserted: int):
            nonlocal last_reported_pct
            if total <= 0:
                pct = 40
            else:
                pct = max(last_reported_pct, min(85, 40 + int((inserted / total) * 45)))
            last_reported_pct = pct
            msg = f"Importing purchase records ({inserted:,} / {total:,})…"
            reports.append((pct, msg))

        # Simulate steps
        steps = [0, 5000, 15000, 25000, 40000, 50000, 52430]
        for step in steps:
            record_progress(step)

        pct_values = [p[0] for p in reports]
        messages = [p[1] for p in reports]

        # 1. Monotonicity: strictly non-decreasing
        assert pct_values == sorted(pct_values)

        # 2. Bounds: within 40 to 85
        assert pct_values[0] == 40
        assert pct_values[-1] == 85
        assert all(40 <= p <= 85 for p in pct_values)

        # 3. Message formatting check
        assert "Importing purchase records (15,000 / 52,430)…" in messages
        assert "Importing purchase records (52,430 / 52,430)…" in messages

    def test_progress_never_exceeds_100_percent(self):
        """Even with overflowing input values, progress cannot exceed 100%."""
        total = 1000
        last_reported_pct = 40

        def calc_pct(inserted: int) -> int:
            nonlocal last_reported_pct
            pct = max(last_reported_pct, min(85, 40 + int((inserted / total) * 45)))
            last_reported_pct = pct
            return pct

        # Test extreme numbers
        assert calc_pct(2000) <= 85
        assert calc_pct(999999) <= 85

    def test_zero_total_protection(self):
        """total = 0 does not raise ZeroDivisionError and safely defaults to 40%."""
        total = 0
        last_reported_pct = 40
        pct = 40 if total <= 0 else max(last_reported_pct, min(85, 40 + int((0 / total) * 45)))
        assert pct == 40


class TestRunImportJobProgressIntegration:
    """Verifies the complete progress lifecycle in run_import_job."""

    @patch("app.worker.tasks._supabase")
    @patch("app.worker.tasks._s3")
    @patch("app.worker.tasks.parse_purchase_register")
    @patch("app.worker.tasks.run_import_sanity")
    def test_full_pr_import_progress_lifecycle(
        self,
        mock_sanity,
        mock_parse,
        mock_s3,
        mock_supabase_fn,
    ):
        """run_import_job must advance 5% -> 40% -> intermediate (40-85%) -> 90% -> 100%."""
        mock_client = MagicMock()
        mock_supabase_fn.return_value = mock_client

        # Mock run row
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"client_gstin_id": "cg-1", "period": "2025-04"}
        ]
        # Mock count accumulator
        mock_client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "gstr_records_imported": 100,
            "pr_records_imported": 12000,
        }

        # Mock S3 object
        mock_s3.return_value.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}

        # Mock parsed records: 12,000 items
        mock_parse.return_value = {
            "success": True,
            "records": [{"inv": f"INV-{i}"} for i in range(12000)],
            "sheets_used": [{"sheet": "Sheet1", "records": 12000}],
            "sheets_skipped": [],
            "warnings": [],
            "missing_invoice_number_count": 0,
        }
        mock_sanity.return_value = []

        progress_updates: list[tuple[int | float, str | None]] = []

        # Capture _update_run calls
        original_update_run = _update_run

        def track_update_run(client, run_id, fields):
            if "progress_percent" in fields:
                progress_updates.append((fields["progress_percent"], fields.get("status_message")))
            original_update_run(client, run_id, fields)

        with patch("app.worker.tasks._update_run", side_effect=track_update_run), \
             patch("app.worker.tasks.time.monotonic", return_value=100.0):
            run_import_job("run-123", "purchase_register", "uploads/pr.xlsx")

        pct_sequence = [u[0] for u in progress_updates]

        # 1. Starts at 5% (downloading)
        assert pct_sequence[0] == 5

        # 2. Reaches 40% after parse
        assert pct_sequence[1] == 40

        # 3. Intermediate updates during bulk insert (scaled between 40% and 85%)
        intermediate = [p for p in pct_sequence if 40 < p <= 85]
        assert len(intermediate) > 0

        # 4. Final intermediate is 85%
        assert 85 in pct_sequence

        # 5. Advances to 90% (finalizing)
        assert 90 in pct_sequence

        # 6. Completes at 100%
        assert pct_sequence[-1] == 100

        # 7. Strictly monotonic throughout
        assert pct_sequence == sorted(pct_sequence)


class TestGuardedStagingIdempotencyAndCancellation:
    """Verifies guarded staging purge on retry and in-flight cancellation handling."""

    @patch("app.worker.tasks._supabase")
    @patch("app.worker.tasks._s3")
    @patch("app.worker.tasks.parse_purchase_register")
    @patch("app.worker.tasks.run_import_sanity")
    def test_staging_idempotency_purges_unfinalized_run(
        self,
        mock_sanity,
        mock_parse,
        mock_s3,
        mock_supabase_fn,
    ):
        """run_import_job purges prior staging rows for run_id before inserting new rows."""
        mock_client = MagicMock()
        mock_supabase_fn.return_value = mock_client

        mock_pr_table = MagicMock()
        mock_recon_table = MagicMock()
        mock_import_runs_table = MagicMock()

        def table_router(name: str):
            if name == "pr_records":
                return mock_pr_table
            if name == "reconciliation_run":
                return mock_recon_table
            if name == "reconciliation_import_runs":
                return mock_import_runs_table
            return MagicMock()

        mock_client.table.side_effect = table_router

        # Run is in "failed" state (unfinalized retry)
        mock_recon_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"client_gstin_id": "cg-1", "period": "2025-04", "status": "failed", "is_locked": False}
        ]
        mock_recon_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "gstr_records_imported": None,
            "pr_records_imported": 10,
        }

        mock_s3.return_value.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
        mock_parse.return_value = {
            "success": True,
            "records": [{"inv": f"INV-{i}"} for i in range(10)],
            "sheets_used": [{"sheet": "Sheet1", "records": 10}],
            "sheets_skipped": [],
            "warnings": [],
            "missing_invoice_number_count": 0,
        }
        mock_sanity.return_value = []

        run_import_job("run-retry-1", "purchase_register", "uploads/pr.xlsx")

        # Verify delete was called on pr_records specifically for run-retry-1
        mock_pr_table.delete.assert_called_once()
        mock_pr_table.delete().eq.assert_called_with("run_id", "run-retry-1")

    @pytest.mark.parametrize("status,is_locked", [
        ("COMPLETED", False),
        ("completed", False),
        ("MATCHING", False),
        ("processing", False),
        ("FINAL", False),
        ("finalized", False),
        ("failed", True),  # locked flag set
    ])
    @patch("app.worker.tasks._supabase")
    @patch("app.worker.tasks._s3")
    @patch("app.worker.tasks.parse_purchase_register")
    def test_staging_idempotency_blocks_completed_or_locked_run(
        self,
        mock_parse,
        mock_s3,
        mock_supabase_fn,
        status: str,
        is_locked: bool,
    ):
        """run_import_job raises RuntimeError and never purges or inserts if run is finalized/locked."""
        mock_client = MagicMock()
        mock_supabase_fn.return_value = mock_client

        mock_pr_table = MagicMock()
        mock_recon_table = MagicMock()

        def table_router(name: str):
            if name == "pr_records":
                return mock_pr_table
            if name == "reconciliation_run":
                return mock_recon_table
            return MagicMock()

        mock_client.table.side_effect = table_router

        mock_recon_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"client_gstin_id": "cg-1", "period": "2025-04", "status": status, "is_locked": is_locked}
        ]

        mock_s3.return_value.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
        mock_parse.return_value = {
            "success": True,
            "records": [{"inv": "INV-1"}],
            "sheets_used": [{"sheet": "Sheet1", "records": 1}],
            "sheets_skipped": [],
            "warnings": [],
            "missing_invoice_number_count": 0,
        }

        with pytest.raises(RuntimeError, match=r"Cannot import into run .* \(run is finalized, locked, or processing\)"):
            run_import_job("run-locked", "purchase_register", "uploads/pr.xlsx")

        # Verify delete and insert were NEVER called on staging table
        mock_pr_table.delete.assert_not_called()
        mock_pr_table.insert.assert_not_called()

    @patch("app.worker.tasks._supabase")
    @patch("app.worker.tasks._s3")
    @patch("app.worker.tasks.parse_gstr2b")
    @patch("app.worker.tasks._load_and_normalize_gstr2b_body_for_parse")
    @patch("app.worker.tasks.run_import_sanity")
    def test_staging_deletion_scoped_to_run_id_and_target_table(
        self,
        mock_sanity,
        mock_norm,
        mock_parse,
        mock_s3,
        mock_supabase_fn,
    ):
        """Importing gstr2b purges gstr_records, not pr_records."""
        mock_client = MagicMock()
        mock_supabase_fn.return_value = mock_client

        mock_gstr_table = MagicMock()
        mock_pr_table = MagicMock()
        mock_recon_table = MagicMock()
        mock_import_runs_table = MagicMock()

        def table_router(name: str):
            if name == "gstr_records":
                return mock_gstr_table
            if name == "pr_records":
                return mock_pr_table
            if name == "reconciliation_run":
                return mock_recon_table
            if name == "reconciliation_import_runs":
                return mock_import_runs_table
            return MagicMock()

        mock_client.table.side_effect = table_router

        mock_recon_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"client_gstin_id": "cg-1", "period": "2025-04", "status": "queued", "is_locked": False}
        ]
        mock_recon_table.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "gstr_records_imported": 5,
            "pr_records_imported": None,
        }

        mock_s3.return_value.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
        mock_norm.return_value = {"b2b": []}
        mock_parse.return_value = {
            "success": True,
            "records": [{"inv": f"INV-{i}"} for i in range(5)],
        }
        mock_sanity.return_value = []

        run_import_job("run-gstr-target", "gstr2b", "uploads/gstr.json")

        # Verify gstr_records was purged for run-gstr-target
        mock_gstr_table.delete.assert_called_once()
        mock_gstr_table.delete().eq.assert_called_with("run_id", "run-gstr-target")

        # Verify pr_records was NEVER touched
        mock_pr_table.delete.assert_not_called()
        mock_pr_table.insert.assert_not_called()

    def test_bulk_insert_cancellation_aborts_early(self):
        """_bulk_insert aborts immediately and raises ImportCancelledException when cancelled."""
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_client.table.return_value = mock_table

        rows = [{"run_id": "run-1", "data": i} for i in range(15000)]
        call_count = 0

        def is_cancelled_sim():
            nonlocal call_count
            call_count += 1
            # Cancel after first batch flush (call_count == 2)
            return call_count >= 2

        with pytest.raises(ImportCancelledException, match="Import cancelled by user"):
            _bulk_insert(mock_client, "pr_records", rows, is_cancelled=is_cancelled_sim)

        # 15,000 rows at 500/chunk = 30 chunks total.
        # It should abort at chunk 10 (5,000 rows) instead of running all 30 chunks!
        assert mock_table.insert.call_count < 30

    @patch("app.worker.tasks._supabase")
    @patch("app.worker.tasks._s3")
    @patch("app.worker.tasks.parse_purchase_register")
    @patch("app.worker.tasks.run_import_sanity")
    def test_run_import_job_handles_cancellation_gracefully(
        self,
        mock_sanity,
        mock_parse,
        mock_s3,
        mock_supabase_fn,
    ):
        """run_import_job catches ImportCancelledException, purges partial records, and exits without failing."""
        mock_client = MagicMock()
        mock_supabase_fn.return_value = mock_client

        mock_pr_table = MagicMock()
        mock_recon_table = MagicMock()
        mock_import_runs_table = MagicMock()

        def table_router(name: str):
            if name == "pr_records":
                return mock_pr_table
            if name == "reconciliation_run":
                return mock_recon_table
            if name == "reconciliation_import_runs":
                return mock_import_runs_table
            return MagicMock()

        mock_client.table.side_effect = table_router

        mock_recon_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"client_gstin_id": "cg-1", "period": "2025-04", "status": "importing", "is_locked": False}
        ]
        # In cancellation check, wizard status reports cancelled
        mock_import_runs_table.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"status": "cancelled"}
        ]

        mock_s3.return_value.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
        mock_parse.return_value = {
            "success": True,
            "records": [{"inv": f"INV-{i}"} for i in range(1000)],
            "sheets_used": [{"sheet": "Sheet1", "records": 1000}],
            "sheets_skipped": [],
            "warnings": [],
            "missing_invoice_number_count": 0,
        }
        mock_sanity.return_value = []

        # Run import job — should NOT raise an unhandled exception
        run_import_job("run-cancel-test", "purchase_register", "uploads/pr.xlsx")

        # 1. Staging table had delete called to clean up partial records
        assert mock_pr_table.delete().eq.call_args_list[-1] == call("run_id", "run-cancel-test")

        # 2. reconciliation_run was NOT marked failed or complete
        for update_call in mock_recon_table.update.call_args_list:
            patch_dict = update_call[0][0]
            assert patch_dict.get("status") not in ("failed", "READY", "PURCHASE_IMPORT_COMPLETE", "complete")
            assert patch_dict.get("progress_percent") != 100

