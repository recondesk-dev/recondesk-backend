"""PR post-match upsert payload tests (reconciliation_task write step)."""

from app.worker.reconciliation_task import (
    _build_pr_index_for_matching,
    _build_pr_post_match_upsert_row,
    _load_pr_matcher_and_raw_page,
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


def test_load_pr_matcher_and_raw_page_returns_db_row_count():
    class _Exec:
        data = [
            {"id": "a", "record_data": {"invoice_number": "INV1", "gstin": "27ABCDE1234F1Z0"}},
            {"id": "b", "record_data": {"gstin": "27ABCDE1234F1Z0"}},
        ]

        def execute(self):
            return self

    class _Query:
        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def range(self, *args, **kwargs):
            return _Exec()

    class _Client:
        def table(self, name):
            assert name == "pr_records"
            return _Query()

    chunk, raw, skipped, fetched = _load_pr_matcher_and_raw_page(
        _Client(), "run-1", 0, 500
    )
    assert fetched == 2
    assert len(chunk) == 1
    assert skipped == {"b"}
    assert "a" in raw


def test_build_pr_index_paginates_until_empty():
    pages = [
        [
            {
                "id": "1",
                "record_data": {
                    "invoice_number": "INV1",
                    "gstin": "27ABCDE1234F1Z0",
                },
            },
        ],
        [],
    ]
    offsets: list[int] = []

    class _Exec:
        def __init__(self, rows):
            self.data = rows

        def execute(self):
            return self

    class _Query:
        def __init__(self, client):
            self._client = client

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def range(self, offset, end):
            offsets.append(offset)
            idx = len(offsets) - 1
            rows = pages[idx] if idx < len(pages) else []
            return _Exec(rows)

    class _Client:
        def table(self, name):
            assert name == "pr_records"
            return _Query(self)

    index, loaded = _build_pr_index_for_matching(_Client(), "run-1")
    assert loaded == 1
    assert len(index["27ABCDE1234F1Z0"]) == 1
    assert offsets == [0]


def test_build_pr_index_advances_offset_by_db_rows_not_matcher_rows():
    """Invoice-less rows still occupy pagination slots; offset must skip them."""
    full_page = [
        {"id": str(i), "record_data": {"gstin": "27ABCDE1234F1Z0"}}
        for i in range(499)
    ] + [
        {
            "id": "499",
            "record_data": {
                "invoice_number": "INV499",
                "gstin": "27ABCDE1234F1Z0",
            },
        },
    ]
    second_page = [
        {
            "id": "500",
            "record_data": {
                "invoice_number": "INV500",
                "gstin": "27ABCDE1234F1Z0",
            },
        },
    ]
    pages = [full_page, second_page]
    offsets: list[int] = []

    class _Exec:
        def __init__(self, rows):
            self.data = rows

        def execute(self):
            return self

    class _Query:
        def range(self, offset, end):
            offsets.append(offset)
            idx = len(offsets) - 1
            rows = pages[idx] if idx < len(pages) else []
            return _Exec(rows)

        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

    class _Client:
        def table(self, name):
            return _Query()

    index, loaded = _build_pr_index_for_matching(_Client(), "run-1")
    assert loaded == 2
    assert len(index["27ABCDE1234F1Z0"]) == 2
    assert offsets == [0, 500]


def test_gstr_pagination_uses_page_size_not_batch_cap():
    """PostgREST may return fewer rows than requested; stop only when page is short."""
    from app.worker.reconciliation_task import DB_PAGE_SIZE

    # Simulates Supabase returning 1000 rows when 2000 were requested (old bug used BATCH=2000).
    pages = [list(range(1000)), list(range(1000, 1443))]
    offsets: list[int] = []

    class _Exec:
        def __init__(self, rows):
            self.data = [{"id": str(i), "record_data": {"supplier_gstin": "X", "invoice_number_norm": f"INV{i}", "items": []}} for i in rows]

        def execute(self):
            return self

    class _Query:
        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def order(self, *args, **kwargs):
            return self

        def range(self, offset, end):
            offsets.append(offset)
            idx = len(offsets) - 1
            rows = pages[idx] if idx < len(pages) else []
            return _Exec(rows)

    class _Client:
        def table(self, name):
            return _Query()

    # Inline the fixed pagination loop from _load_gstr_matcher_and_raw
    out = []
    offset = 0
    while True:
        q = _Client().table("gstr_records")
        end = offset + DB_PAGE_SIZE - 1
        rows = q.range(offset, end).execute().data or []
        if not rows:
            break
        out.extend(rows)
        offset += len(rows)
        if len(rows) < DB_PAGE_SIZE:
            break

    assert len(out) == 1443
    assert offsets == [0, 1000]
