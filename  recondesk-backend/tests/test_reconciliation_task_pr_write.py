"""PR post-match upsert payload tests (reconciliation_task write step)."""

from app.worker.reconciliation_task import (
    _build_pr_post_match_upsert_row,
    _matched_engine_meta_by_pr_id,
    _pr_match_status_for_record,
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
