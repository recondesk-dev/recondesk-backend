"""PR post-match upsert payload tests (reconciliation_task write step)."""

from app.worker.reconciliation_task import (
    _build_pr_post_match_upsert_row,
    _matched_engine_meta_by_pr_id,
    _pr_match_status_for_record,
    _pr_record_data_missing_invoice_number,
    _write_pr_match_status_chunk,
)


def _gstr(**kwargs):
    base = {
        "id": "1",
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number_normalized": "INV001",
        "invoice_date": "2024-01-15",
        "taxable_amount_paise": 100000,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
        "igst_paise": 0,
        "total_tax_paise": 18000,
    }
    base.update(kwargs)
    return base


def _pr(**kwargs):
    base = {
        "id": "10",
        "supplier_gstin": "27ABCDE1234F1Z0",
        "invoice_number_normalized": "INV001",
        "invoice_date": "2024-01-15",
        "taxable_amount_paise": 100000,
        "cgst_paise": 9000,
        "sgst_paise": 9000,
        "igst_paise": 0,
        "total_tax_paise": 18000,
    }
    base.update(kwargs)
    return base


def test_build_pr_post_match_upsert_row_sets_column_and_jsonb():
    row = _build_pr_post_match_upsert_row(
        "42",
        "d2cfc3af-cf2a-4c16-906f-a69cdc1cf913",
        {"gstin": "27ABCDE1234F1Z0", "invoice_number": "INV001"},
        "matched",
        {"match_level": 1, "vendor_similarity_score": 0.91},
    )

    assert row["id"] == "42"
    assert row["run_id"] == "d2cfc3af-cf2a-4c16-906f-a69cdc1cf913"
    assert row["match_status"] == "matched"
    assert row["match_level"] == 1
    assert row["record_data"]["match_status"] == "matched"
    assert row["record_data"]["match_level"] == 1
    assert row["record_data"]["vendor_similarity_score"] == 0.91
    assert row["record_data"]["gstin"] == "27ABCDE1234F1Z0"


def test_build_pr_post_match_upsert_row_id_is_uuid_string_not_int():
    """Regression: int(pr_id) raises ValueError on UUIDs and skips every upsert row."""
    pr_uuid = "d2cfc3af-cf2a-4c16-906f-a69cdc1cf913"
    row = _build_pr_post_match_upsert_row(
        pr_uuid,
        "581f94f1-a2da-4756-87b5-c2d534f28a13",
        {"gstin": "27ABCDE1234F1Z0"},
        "matched",
        {"match_level": 1},
    )

    assert isinstance(row["id"], str)
    assert not isinstance(row["id"], int)
    assert row["id"] == pr_uuid


def test_build_pr_post_match_upsert_row_unmatched_omits_match_level():
    row = _build_pr_post_match_upsert_row(
        "7",
        "d2cfc3af-cf2a-4c16-906f-a69cdc1cf913",
        {"gstin": "27ABCDE1234F1Z0"},
        "unmatched",
        None,
    )

    assert row["match_status"] == "unmatched"
    assert "match_level" not in row
    assert row["record_data"]["match_status"] == "unmatched"
    assert "match_level" not in row["record_data"]


def test_matched_engine_meta_by_pr_id_includes_level_and_vendor_score():
    gstr = _gstr(id="1")
    pr = _pr(id="10")
    matched = [
        {
            "gstr_id": "1",
            "pr_id": "10",
            "vendor_similarity_score": 0.88,
        }
    ]
    meta = _matched_engine_meta_by_pr_id(
        matched,
        {"1": gstr},
        {"10": pr},
    )

    assert meta["10"]["match_level"] == 1
    assert meta["10"]["vendor_similarity_score"] == 0.88


def test_pr_match_status_for_record_classifies_matched_and_unmatched():
    pr = _pr(id="10")
    gstr = _gstr(id="1")

    assert (
        _pr_match_status_for_record(pr, {"10"}, {"27ABCDE1234F1Z0": [gstr]})
        == "matched"
    )
    assert (
        _pr_match_status_for_record(pr, set(), {"27ABCDE1234F1Z0": [gstr]})
        == "missing_in_2b"
    )
    assert _pr_match_status_for_record(pr, set(), {}) == "unmatched"


def test_pr_record_data_missing_invoice_number():
    assert _pr_record_data_missing_invoice_number(None) is True
    assert _pr_record_data_missing_invoice_number({}) is True
    assert _pr_record_data_missing_invoice_number({"gstin": "27ABCDE1234F1Z0"}) is True
    assert (
        _pr_record_data_missing_invoice_number({"invoice_number": "INV001"}) is False
    )
    assert (
        _pr_record_data_missing_invoice_number(
            {"invoice_number_normalized": "INV001"}
        )
        is False
    )


def test_write_pr_match_status_chunk_writes_unmatched_for_skipped_ids():
    upserted: list[dict] = []

    class _Exec:
        def execute(self):
            return self

    class _Table:
        def upsert(self, chunk, **kwargs):
            upserted.extend(chunk)
            return _Exec()

    class _Client:
        def table(self, name):
            assert name == "pr_records"
            return _Table()

    tracking, matched, written = _write_pr_match_status_chunk(
        _Client(),
        run_id="581f94f1-a2da-4756-87b5-c2d534f28a13",
        pr_chunk=[],
        pr_raw_by_id={"bad-id": {"gstin": "27ABCDE1234F1Z0"}},
        matched_pr_ids=set(),
        gstr_by_gstin={},
        gstr_by_id={},
        matched=[],
        skipped_pr_ids={"bad-id"},
    )

    assert matched == 0
    assert written == 1
    assert len(tracking) == 1
    assert tracking[0]["match_status"] == "unmatched"
    assert len(upserted) == 1
    assert upserted[0]["id"] == "bad-id"
    assert upserted[0]["match_status"] == "unmatched"
    assert upserted[0]["record_data"]["match_status"] == "unmatched"
