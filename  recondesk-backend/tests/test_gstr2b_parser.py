"""Tests for app/parsers/gstr2b_parser.py.

All 31 test cases (spec requires at least 24) must pass.

Verified valid GSTINs:
    BUYER_GSTIN  = "27AAAAA1234A1ZP"
    SUPPLIER_1   = "29ABCDE1234F1ZX"
    SUPPLIER_2   = "07CCCCC1234C1Z9"
"""

import datetime
import json
import time

import pytest

from app.parsers.gstr2b_parser import _make_skip_entry, parse_gstr2b

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

BUYER_GSTIN = "27AAAAA1234A1ZP"
SUPPLIER_1 = "29ABCDE1234F1ZX"
SUPPLIER_2 = "07CCCCC1234C1Z9"


def _enc(obj: dict) -> bytes:
    return json.dumps(obj).encode("utf-8")


def _payload(
    *,
    gstin: str = BUYER_GSTIN,
    rtnprd: str = "042024",
    b2b=None,
    b2ba=None,
    cdnr=None,
    cdnra=None,
    **extra,
) -> bytes:
    data: dict = {"gstin": gstin, "rtnprd": rtnprd, **extra}
    if b2b is not None:
        data["b2b"] = b2b
    if b2ba is not None:
        data["b2ba"] = b2ba
    if cdnr is not None:
        data["cdnr"] = cdnr
    if cdnra is not None:
        data["cdnra"] = cdnra
    return _enc({"data": data})


def _supplier(ctin: str, invoices: list) -> dict:
    return {"ctin": ctin, "inv": invoices}


def _invoice(
    inum: str = "INV001",
    dt: str = "01-04-2024",
    val=1000,
    pos: str = "27",
    rev: str = "N",
    itcavl: str = "Y",
    itms=None,
) -> dict:
    inv: dict = {"inum": inum, "dt": dt, "val": val, "pos": pos, "rev": rev, "itcavl": itcavl}
    if itms is not None:
        inv["itms"] = itms
    return inv


def _item(rt=18, txval=1000, igst=180, cgst=0, sgst=0, cess=0) -> dict:
    return {"rt": rt, "txval": txval, "igst": igst, "cgst": cgst, "sgst": sgst, "cess": cess}


def _cdnr_invoice(
    ntnum: str = "CN001",
    dt: str = "01-04-2024",
    val=500,
    ntty: str = "C",
    pos: str = "27",
    rev: str = "N",
    itcavl: str = "Y",
    itms=None,
    **extra,
) -> dict:
    inv: dict = {"ntnum": ntnum, "dt": dt, "val": val, "ntty": ntty, "pos": pos, "rev": rev, "itcavl": itcavl}
    if itms is not None:
        inv["itms"] = itms
    inv.update(extra)
    return inv


# ===========================================================================
# Happy-path tests
# ===========================================================================

def test_valid_b2b_all_fields_present_and_typed():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(itms=[_item()])])]))

    assert result["schema_version"] == "gstr2b_v1"
    assert result["buyer_gstin"] == BUYER_GSTIN
    assert result["period"] == "2024-04-01"
    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0

    rec = result["records"][0]
    assert rec["document_type"] == "INVOICE"
    assert rec["is_amendment"] is False
    assert rec["section"] == "b2b"
    assert rec["schema_version"] == "gstr2b_v1"
    assert rec["supplier_gstin"] == SUPPLIER_1
    assert rec["supplier_gstin_raw"] == SUPPLIER_1
    assert rec["invoice_number"] == "INV001"
    assert rec["invoice_number_raw"] == "INV001"
    assert isinstance(rec["invoice_date"], datetime.date)
    assert isinstance(rec["invoice_value_paise"], int)
    assert rec["reverse_charge"] is False
    assert rec["itc_available"] is True
    assert rec["original_invoice_number"] is None
    assert rec["original_invoice_date"] is None
    assert rec["original_invoice_number_raw"] is None
    assert rec["original_invoice_date_raw"] is None
    assert isinstance(rec["pos"], str)
    assert isinstance(rec["items"], list)
    assert len(rec["items"]) == 1
    assert isinstance(rec["normalization_notes"], dict)
    assert isinstance(rec["unique_key"], tuple)


def test_cdnr_ntty_c_is_credit_note():
    result = parse_gstr2b(_payload(cdnr=[_supplier(SUPPLIER_1, [_cdnr_invoice(ntty="C")])]))
    assert result["records"][0]["document_type"] == "CREDIT_NOTE"


def test_cdnr_ntty_d_is_debit_note():
    result = parse_gstr2b(_payload(cdnr=[_supplier(SUPPLIER_1, [_cdnr_invoice(ntty="D")])]))
    assert result["records"][0]["document_type"] == "DEBIT_NOTE"


def test_b2ba_is_amendment_true_with_originals():
    inv = {
        "inum": "INV002", "dt": "15-04-2024", "val": 2000,
        "pos": "27", "rev": "N", "itcavl": "Y",
        "oinum": "INV001", "oidt": "01-03-2024",
    }
    result = parse_gstr2b(_payload(b2ba=[_supplier(SUPPLIER_1, [inv])]))

    assert result["total_parsed"] == 1
    rec = result["records"][0]
    assert rec["is_amendment"] is True
    assert rec["section"] == "b2ba"
    assert rec["original_invoice_number"] == "INV001"
    assert rec["original_invoice_number_raw"] == "INV001"
    assert rec["original_invoice_date"] == datetime.date(2024, 3, 1)
    assert rec["original_invoice_date_raw"] == "01-03-2024"


def test_cdnra_is_amendment_true_with_originals():
    inv = {
        "ntnum": "CN002", "dt": "05-04-2024", "val": 600,
        "ntty": "C", "pos": "27", "rev": "N", "itcavl": "Y",
        "ointnum": "CN001", "ointdt": "10-03-2024",
    }
    result = parse_gstr2b(_payload(cdnra=[_supplier(SUPPLIER_1, [inv])]))

    assert result["total_parsed"] == 1
    rec = result["records"][0]
    assert rec["is_amendment"] is True
    assert rec["section"] == "cdnra"
    assert rec["original_invoice_number"] == "CN001"
    assert rec["original_invoice_date"] == datetime.date(2024, 3, 10)


def test_rtnprd_042024_parses_to_april_2024():
    result = parse_gstr2b(_payload(rtnprd="042024", b2b=[_supplier(SUPPLIER_1, [_invoice()])]))
    assert result["period"] == "2024-04-01"


def test_rev_y_sets_reverse_charge_true():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(rev="Y")])]))
    assert result["records"][0]["reverse_charge"] is True


def test_itcavl_n_sets_itc_available_false():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(itcavl="N")])]))
    assert result["records"][0]["itc_available"] is False


def test_normalization_notes_only_for_transformed_fields():
    # Clean values — no transformations applied, notes should be empty
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(inum="INV001", dt="01-04-2024", val=1000)])]))
    assert result["records"][0]["normalization_notes"] == {}

    # Lowercase + hyphenated invoice number → symbols_stripped + uppercased notes
    result2 = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(inum="inv-001")])]))
    notes = result2["records"][0]["normalization_notes"]
    assert "invoice_number" in notes
    assert set(notes["invoice_number"]) == {"symbols_stripped", "uppercased"}


def test_total_parsed_plus_skipped_equals_total_invoices_seen():
    bad = {"inum": "BAD", "dt": None, "val": 100, "pos": "27"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(), bad])]))
    m = result["metrics"]
    assert m["total_parsed"] + m["total_skipped"] == m["total_invoices_seen"]
    assert result["total_parsed"] + result["total_skipped"] == m["total_invoices_seen"]


def test_isd_and_impg_silently_ignored():
    data = {
        "gstin": BUYER_GSTIN, "rtnprd": "042024",
        "b2b": [_supplier(SUPPLIER_1, [_invoice()])],
        "isd": [{"ctin": SUPPLIER_1, "inv": [{"some": "data"}]}],
        "impg": [{"portcd": "INMAA1", "data": []}],
    }
    result = parse_gstr2b(_enc({"data": data}))
    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0


def test_unique_key_structure_on_every_record():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice()])]))
    for rec in result["records"]:
        key = rec["unique_key"]
        assert isinstance(key, tuple)
        assert len(key) == 3
        assert key[0] == rec["supplier_gstin"]
        assert key[1] == rec["invoice_number"]
        assert key[2] == rec["invoice_date"]


def test_skip_reasons_counted_correctly():
    bad1 = {"inum": "BAD1", "dt": None, "val": 100, "pos": "27"}
    bad2 = {"inum": "BAD2", "dt": None, "val": 200, "pos": "27"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(), bad1, bad2])]))
    assert result["metrics"]["skip_reasons"].get("missing_field for dt", 0) == 2


def test_sections_present_lists_only_sections_with_parsed_records():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice()])]))
    assert "b2b" in result["metrics"]["sections_present"]
    assert "b2b" not in result["metrics"]["sections_empty"]
    assert "cdnr" not in result["metrics"]["sections_present"]
    assert "cdnr" not in result["metrics"]["sections_empty"]


def test_empty_b2b_list_goes_to_sections_empty():
    result = parse_gstr2b(_payload(b2b=[]))
    assert "b2b" in result["metrics"]["sections_empty"]
    assert "b2b" not in result["metrics"]["sections_present"]


def test_all_b2b_invoices_fail_goes_to_sections_empty():
    bad = {"inum": "BAD", "dt": None, "val": 1000, "pos": "27"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [bad])]))
    assert "b2b" in result["metrics"]["sections_empty"]
    assert "b2b" not in result["metrics"]["sections_present"]


# ===========================================================================
# Adversarial tests
# ===========================================================================

def test_invalid_json_raises_value_error():
    with pytest.raises(ValueError, match="invalid_json"):
        parse_gstr2b(b"not json {{{")


def test_missing_data_key_raises_value_error():
    with pytest.raises(ValueError, match="missing_data_key"):
        parse_gstr2b(_enc({"wrong": {}}))


def test_b2b_not_a_list_treated_as_empty_no_crash():
    data = {"gstin": BUYER_GSTIN, "rtnprd": "042024", "b2b": 42}
    result = parse_gstr2b(_enc({"data": data}))
    assert "b2b" in result["metrics"]["sections_empty"]
    assert result["total_parsed"] == 0


def test_empty_inv_array_zero_records_no_error():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [])]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 0


def test_invalid_supplier_gstin_all_invoices_skipped_rest_continue():
    inv1 = _invoice(inum="INV001")
    inv2 = _invoice(inum="INV002")
    result = parse_gstr2b(
        _payload(b2b=[
            {"ctin": "INVALID_GSTIN", "inv": [inv1]},
            _supplier(SUPPLIER_2, [inv2]),
        ])
    )
    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 1
    assert result["records"][0]["invoice_number"] == "INV002"


def test_val_abc_goes_to_skipped():
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(val="abc")])]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 1


def test_dt_null_goes_to_skipped():
    inv = {"inum": "INV001", "dt": None, "val": 1000, "pos": "27", "rev": "N", "itcavl": "Y"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [inv])]))
    assert result["total_skipped"] == 1
    assert "missing_field for dt" in result["skipped"][0]["error_reason"]


def test_missing_itms_produces_empty_items_record_still_parsed():
    inv = {"inum": "INV001", "dt": "01-04-2024", "val": 1000, "pos": "27", "rev": "N", "itcavl": "Y"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [inv])]))
    assert result["total_parsed"] == 1
    assert result["records"][0]["items"] == []


def test_itms_non_list_goes_to_skipped():
    inv = {"inum": "INV001", "dt": "01-04-2024", "val": 1000, "pos": "27", "rev": "N", "itcavl": "Y", "itms": "invalid"}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [inv])]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 1
    assert "invalid_type for itms" in result["skipped"][0]["error_reason"]


def test_cdnr_unknown_ntty_goes_to_skipped_with_correct_reason():
    inv = _cdnr_invoice(ntty="X")
    result = parse_gstr2b(_payload(cdnr=[_supplier(SUPPLIER_1, [inv])]))
    assert result["total_skipped"] == 1
    assert result["skipped"][0]["error_reason"] == "unknown_note_type"


def test_b2ba_missing_oinum_original_is_none_no_crash():
    inv = {"inum": "INV002", "dt": "01-04-2024", "val": 2000, "pos": "27", "rev": "N", "itcavl": "Y"}
    result = parse_gstr2b(_payload(b2ba=[_supplier(SUPPLIER_1, [inv])]))
    assert result["total_parsed"] == 1
    rec = result["records"][0]
    assert rec["original_invoice_number"] is None
    assert rec["original_invoice_number_raw"] is None
    assert rec["original_invoice_date"] is None
    assert rec["original_invoice_date_raw"] is None


def test_supplier_entry_not_dict_silently_skipped():
    result = parse_gstr2b(_payload(b2b=["not_a_supplier_dict"]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 0


def test_invoice_entry_not_dict_goes_to_skipped():
    result = parse_gstr2b(_payload(b2b=[{"ctin": SUPPLIER_1, "inv": ["not_an_invoice"]}]))
    assert result["total_skipped"] == 1
    assert result["skipped"][0]["error_reason"] == "invalid_invoice_structure"


def test_rt_list_value_invoice_goes_to_skipped_with_type_error():
    bad_item = {"rt": [18], "txval": 1000, "igst": 180, "cgst": 0, "sgst": 0, "cess": 0}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(itms=[bad_item])])]))
    assert result["total_skipped"] == 1
    assert "invalid_type for rt" in result["skipped"][0]["error_reason"]


def test_txval_dict_value_invoice_goes_to_skipped_with_type_error():
    bad_item = {"rt": 18, "txval": {}, "igst": 180, "cgst": 0, "sgst": 0, "cess": 0}
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(itms=[bad_item])])]))
    assert result["total_skipped"] == 1
    assert "invalid_type for txval" in result["skipped"][0]["error_reason"]


def test_mutating_skip_raw_data_is_independent_shallow_copy():
    original = {"inum": "TEST", "val": 100, "extra": "original_value", "nested": [1, 2, 3]}
    skip_entry = _make_skip_entry("b2b", SUPPLIER_1, "TEST", "some_error", original)

    # raw_data is a shallow copy — modifying original primitive field does not affect skip
    original["extra"] = "changed"
    assert skip_entry["raw_data"]["extra"] == "original_value"

    # Modifying raw_data does not affect original
    skip_entry["raw_data"]["extra"] = "also_changed"
    assert original["extra"] == "changed"

    # Nested list is the same reference (shallow copy — not deepcopy)
    assert skip_entry["raw_data"]["nested"] is original["nested"]


# ===========================================================================
# New acceptance tests
# ===========================================================================

def test_buyer_gstin_and_period_correct_from_sample_file():
    """Parser returns correct buyer_gstin and period from a sample file."""
    result = parse_gstr2b(
        _payload(gstin=BUYER_GSTIN, rtnprd="042024", b2b=[_supplier(SUPPLIER_1, [_invoice()])])
    )
    assert result["buyer_gstin"] == BUYER_GSTIN
    assert result["period"] == "2024-04-01"
    assert result["schema_version"] == "gstr2b_v1"


def test_b2b_invoices_have_both_raw_and_normalized_columns():
    """Every parsed b2b record carries both *_raw source fields and normalized values."""
    result = parse_gstr2b(_payload(b2b=[_supplier(SUPPLIER_1, [_invoice(inum="inv-001", val=2500)])]))
    assert result["total_parsed"] == 1
    rec = result["records"][0]

    # Raw columns present and are strings
    assert isinstance(rec["supplier_gstin_raw"], str)
    assert isinstance(rec["invoice_number_raw"], str)
    assert isinstance(rec["invoice_date_raw"], str)
    assert isinstance(rec["invoice_value_raw"], str)

    # Normalized columns have correct types
    assert isinstance(rec["supplier_gstin"], str)
    assert isinstance(rec["invoice_number"], str)
    assert isinstance(rec["invoice_date"], datetime.date)
    assert isinstance(rec["invoice_value_paise"], int)

    # Raw and normalized differ when input needed transformation
    # "inv-001" → symbols stripped + uppercased → "INV001"
    assert rec["invoice_number_raw"] == "inv-001"
    assert rec["invoice_number"] == "INV001"
    assert rec["invoice_value_paise"] == 250000  # 2500 rupees × 100 paise


def test_malformed_json_raises_value_error_with_location():
    """Malformed JSON raises ValueError whose message includes line and col."""
    bad_payloads = [
        b'{"data": {"gstin": "X", BROKEN',          # missing quote / bad key
        b'{"data": {\n  "gstin": "X",\n  BAD\n}}',  # error on line 3
    ]
    for payload in bad_payloads:
        with pytest.raises(ValueError) as exc_info:
            parse_gstr2b(payload)
        msg = str(exc_info.value)
        assert msg.startswith("invalid_json"), f"unexpected message: {msg!r}"
        assert "line" in msg, f"no line info in: {msg!r}"
        assert "col" in msg, f"no col info in: {msg!r}"


def test_500_invoices_parse_under_2_seconds():
    """Parser handles 500 invoices and completes in under 2 seconds."""
    invoices = [
        _invoice(inum=f"INV{i:04d}", val=1000 + i, itms=[_item(txval=1000 + i, igst=180)])
        for i in range(500)
    ]
    payload = _payload(b2b=[_supplier(SUPPLIER_1, invoices)])

    start = time.perf_counter()
    result = parse_gstr2b(payload)
    elapsed = time.perf_counter() - start

    assert result["total_parsed"] == 500, f"expected 500 parsed, got {result['total_parsed']}"
    assert result["total_skipped"] == 0
    assert elapsed < 2.0, f"parsing took {elapsed:.2f}s — exceeded 2s budget"


def test_cdnr_records_flagged_as_credit_or_debit_note():
    """cdnr ntty=C → CREDIT_NOTE, ntty=D → DEBIT_NOTE; both present in one parse."""
    invoices = [
        _cdnr_invoice(ntnum="CN001", ntty="C", val=300),
        _cdnr_invoice(ntnum="DN001", ntty="D", val=400),
    ]
    result = parse_gstr2b(_payload(cdnr=[_supplier(SUPPLIER_1, invoices)]))

    assert result["total_parsed"] == 2
    by_num = {r["invoice_number"]: r["document_type"] for r in result["records"]}
    assert by_num["CN001"] == "CREDIT_NOTE"
    assert by_num["DN001"] == "DEBIT_NOTE"
    # Both are non-amendments from the cdnr section
    for rec in result["records"]:
        assert rec["section"] == "cdnr"
        assert rec["is_amendment"] is False
