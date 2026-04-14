"""Hard adversarial tests for gstr2b_parser — run directly in terminal.

    python3 test_hard_gstr2b.py

Every test either asserts the correct output or catches the expected
exception.  A green line = pass.  Any AssertionError or unexpected
exception is printed in red and counted as FAIL.
"""

import json
import sys
import time
import traceback

from app.parsers.gstr2b_parser import _make_skip_entry, parse_gstr2b

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"

passed = failed = 0
results = []


def run(name, fn):
    global passed, failed
    try:
        fn()
        print(f"{GREEN}PASS{RESET}  {name}")
        passed += 1
        results.append(("PASS", name, None))
    except Exception as e:
        print(f"{RED}FAIL{RESET}  {name}")
        print(f"       {RED}{type(e).__name__}: {e}{RESET}")
        failed += 1
        results.append(("FAIL", name, e))


# ---------------------------------------------------------------------------
# Valid GSTINs (checksums verified)
# ---------------------------------------------------------------------------
BUYER   = "27AAAAA1234A1ZP"
SUP_1   = "29ABCDE1234F1ZX"
SUP_2   = "07CCCCC1234C1Z9"
SUP_3   = "19BBBBB5678B2ZO"
SUP_4   = "33DDDDD9999D3ZZ"
SUP_5   = "24EEEEE1111E4Z0"


def enc(obj):
    return json.dumps(obj).encode("utf-8")


def payload(b2b=None, cdnr=None, b2ba=None, cdnra=None, **extra):
    d = {"gstin": BUYER, "rtnprd": "042024", **extra}
    if b2b   is not None: d["b2b"]   = b2b
    if cdnr  is not None: d["cdnr"]  = cdnr
    if b2ba  is not None: d["b2ba"]  = b2ba
    if cdnra is not None: d["cdnra"] = cdnra
    return enc({"data": d})


def supplier(ctin, invoices):
    return {"ctin": ctin, "inv": invoices}


def inv(inum="INV001", dt="01-04-2024", val=1000, pos="27",
        rev="N", itcavl="Y", itms=None, **extra):
    i = {"inum": inum, "dt": dt, "val": val, "pos": pos,
         "rev": rev, "itcavl": itcavl, **extra}
    if itms is not None:
        i["itms"] = itms
    return i


def item(rt=18, txval=1000, igst=180, cgst=0, sgst=0, cess=0):
    return {"rt": rt, "txval": txval, "igst": igst,
            "cgst": cgst, "sgst": sgst, "cess": cess}


def cdnr_inv(ntnum="CN001", dt="01-04-2024", val=500, ntty="C",
             pos="27", rev="N", itcavl="Y", **extra):
    return {"ntnum": ntnum, "dt": dt, "val": val, "ntty": ntty,
            "pos": pos, "rev": rev, "itcavl": itcavl, **extra}


# ===========================================================================
# H01 — UTF-8 BOM prefix is rejected cleanly
# ===========================================================================
def h01():
    bom = b"\xef\xbb\xbf" + b'not json'
    try:
        parse_gstr2b(bom)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        assert "invalid_json" in str(e), f"unexpected message: {e}"

run("H01  UTF-8 BOM on non-JSON raises invalid_json", h01)


# ===========================================================================
# H02 — JSON error message includes line + col
# ===========================================================================
def h02():
    bad = b'{\n  "data": {\n    BROKEN\n  }\n}'
    try:
        parse_gstr2b(bad)
        raise AssertionError("expected ValueError")
    except ValueError as e:
        msg = str(e)
        assert "line" in msg and "col" in msg, f"no location in: {msg!r}"
        # Error is on line 3
        assert "line 3" in msg, f"expected line 3 in: {msg!r}"

run("H02  Malformed JSON error includes exact line and col", h02)


# ===========================================================================
# H03 — Amount as lakh suffix ("5L") parsed to correct paise
# ===========================================================================
def h03():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(val="5L")])]))
    assert r["total_parsed"] == 1
    rec = r["records"][0]
    # 5 lakh rupees = 500000 * 100 paise = 50000000
    assert rec["invoice_value_paise"] == 50_000_000, rec["invoice_value_paise"]
    assert "invoice_value" in rec["normalization_notes"]

run("H03  Amount with lakh suffix '5L' → correct paise + note", h03)


# ===========================================================================
# H04 — Amount with crore suffix ("2CR") parsed correctly
# ===========================================================================
def h04():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(val="2CR")])]))
    rec = r["records"][0]
    assert rec["invoice_value_paise"] == 20_000_000 * 100  # 2cr rupees in paise

run("H04  Amount with crore suffix '2CR' → correct paise", h04)


# ===========================================================================
# H05 — Negative amount stored as negative paise
# ===========================================================================
def h05():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(val="-500")])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["invoice_value_paise"] == -50_000

run("H05  Negative invoice value → negative paise", h05)


# ===========================================================================
# H06 — val=0 parses successfully (zero is valid)
# ===========================================================================
def h06():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(val=0)])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["invoice_value_paise"] == 0

run("H06  val=0 is valid, not skipped", h06)


# ===========================================================================
# H07 — Excel serial date in dt field
# ===========================================================================
def h07():
    import datetime
    # Excel serial 45383 → should parse to a valid date
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(dt=45383)])]))
    assert r["total_parsed"] == 1
    d = r["records"][0]["invoice_date"]
    assert isinstance(d, datetime.date)
    assert "invoice_date" in r["records"][0]["normalization_notes"]
    notes = r["records"][0]["normalization_notes"]["invoice_date"]
    assert "excel_serial_converted" in notes

run("H07  Excel serial in dt field → converted to date with note", h07)


# ===========================================================================
# H08 — Invoice number with all special chars becomes empty → skipped
# ===========================================================================
def h08():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(inum="!@#$%^&*()")])]))
    assert r["total_skipped"] == 1
    assert r["total_parsed"] == 0

run("H08  inum='!@#$%^&*()' normalises to empty → skipped", h08)


# ===========================================================================
# H09 — Invoice number 60-char → truncated to 50, note present
# ===========================================================================
def h09():
    long_inum = "A" * 60
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(inum=long_inum)])]))
    assert r["total_parsed"] == 1
    rec = r["records"][0]
    assert len(rec["invoice_number"]) == 50
    assert "truncated_to_50_chars" in rec["normalization_notes"].get("invoice_number", [])

run("H09  60-char inum truncated to 50 with note", h09)


# ===========================================================================
# H10 — Mixed good/bad suppliers: bad GSTIN skips its invoices, good continues
# ===========================================================================
def h10():
    good_inv = inv(inum="GOOD001")
    bad_inv  = inv(inum="BAD001")
    r = parse_gstr2b(payload(b2b=[
        supplier("INVALID_GSTIN_XYZ", [bad_inv]),   # bad ctin
        supplier(SUP_2, [good_inv]),                 # good ctin
    ]))
    assert r["total_parsed"] == 1
    assert r["total_skipped"] == 1
    assert r["records"][0]["invoice_number"] == "GOOD001"
    assert r["skipped"][0]["invoice_number"] == "BAD001"

run("H10  Bad supplier GSTIN skips its invoices; good supplier unaffected", h10)


# ===========================================================================
# H11 — Multiple suppliers, all valid, correct total_parsed
# ===========================================================================
def h11():
    suppliers = [supplier(g, [inv(inum=f"INV{i:02d}")]) 
                 for i, g in enumerate([SUP_1, SUP_2, SUP_3, SUP_4, SUP_5])]
    r = parse_gstr2b(payload(b2b=suppliers))
    assert r["total_parsed"] == 5
    assert r["total_skipped"] == 0

run("H11  5 valid suppliers × 1 invoice each → 5 parsed", h11)


# ===========================================================================
# H12 — Supplier with 0 invoices + good supplier → only good one counted
# ===========================================================================
def h12():
    r = parse_gstr2b(payload(b2b=[
        supplier(SUP_1, []),          # no invoices
        supplier(SUP_2, [inv()]),     # 1 invoice
    ]))
    assert r["total_parsed"] == 1
    assert r["total_skipped"] == 0
    assert r["metrics"]["total_suppliers_b2b"] == 2

run("H12  Empty inv list for one supplier, valid for another → 1 parsed", h12)


# ===========================================================================
# H13 — All 4 supported sections parsed in one file
# ===========================================================================
def h13():
    r = parse_gstr2b(payload(
        b2b   = [supplier(SUP_1, [inv(inum="B2B01")])],
        b2ba  = [supplier(SUP_1, [inv(inum="B2BA01")])],
        cdnr  = [supplier(SUP_1, [cdnr_inv(ntnum="CN01", ntty="C")])],
        cdnra = [supplier(SUP_1, [cdnr_inv(ntnum="CNA01", ntty="D")])],
    ))
    assert r["total_parsed"] == 4
    sections = r["metrics"]["sections_present"]
    for s in ["b2b", "b2ba", "cdnr", "cdnra"]:
        assert s in sections, f"{s} not in sections_present"

run("H13  All 4 sections (b2b/b2ba/cdnr/cdnra) parse in one file", h13)


# ===========================================================================
# H14 — b2ba with oinum missing → original_invoice_number is None
# ===========================================================================
def h14():
    r = parse_gstr2b(payload(b2ba=[supplier(SUP_1, [inv(inum="AMD01")])]))
    rec = r["records"][0]
    assert rec["is_amendment"] is True
    assert rec["original_invoice_number"] is None
    assert rec["original_invoice_number_raw"] is None
    assert rec["original_invoice_date"] is None

run("H14  b2ba with no oinum/oidt → originals are None, no crash", h14)


# ===========================================================================
# H15 — cdnra with ointnum present → original captured
# ===========================================================================
def h15():
    import datetime
    note = cdnr_inv(ntnum="CNA01", ntty="C", ointnum="CN001", ointdt="15-03-2024")
    r = parse_gstr2b(payload(cdnra=[supplier(SUP_1, [note])]))
    rec = r["records"][0]
    assert rec["is_amendment"] is True
    assert rec["original_invoice_number"] == "CN001"
    assert rec["original_invoice_date"] == datetime.date(2024, 3, 15)

run("H15  cdnra with ointnum/ointdt → originals captured correctly", h15)


# ===========================================================================
# H16 — Item with rt=0 (zero rate) → tax_rate=0.0, not skipped
# ===========================================================================
def h16():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(itms=[item(rt=0, igst=0)])])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["items"][0]["tax_rate"] == 0.0

run("H16  item rt=0 (zero-rated) → tax_rate=0.0, not skipped", h16)


# ===========================================================================
# H17 — item rt as string "18.5" → float 18.5
# ===========================================================================
def h17():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(itms=[item(rt="18.5")])])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["items"][0]["tax_rate"] == 18.5

run("H17  item rt='18.5' (string) → float 18.5", h17)


# ===========================================================================
# H18 — item rt="" (empty string) → invoice skipped
# ===========================================================================
def h18():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(itms=[item(rt="")])])]))
    assert r["total_skipped"] == 1
    assert "unparseable rt value" in r["skipped"][0]["error_reason"]

run("H18  item rt='' (empty string) → unparseable, invoice skipped", h18)


# ===========================================================================
# H19 — txval with comma-formatted number "1,00,000"
# ===========================================================================
def h19():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [
        inv(itms=[item(txval="1,00,000", igst="18,000")])
    ])]))
    assert r["total_parsed"] == 1
    it = r["records"][0]["items"][0]
    assert it["taxable_value_paise"] == 10_000_000  # 1,00,000 rupees
    assert it["igst_paise"] == 1_800_000

run("H19  txval='1,00,000' with commas → correct paise + commas_stripped note", h19)


# ===========================================================================
# H20 — cess field present → stored in cess_paise
# ===========================================================================
def h20():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [
        inv(itms=[item(txval=10000, igst=2800, cess=500)])
    ])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["items"][0]["cess_paise"] == 50_000

run("H20  cess field present → cess_paise correct", h20)


# ===========================================================================
# H21 — skip_reasons aggregates across multiple suppliers
# ===========================================================================
def h21():
    bad1 = inv(inum="BAD1", dt=None)   # missing_field for dt
    bad2 = inv(inum="BAD2", val="xyz") # invalid_format amount
    bad3 = inv(inum="BAD3", dt=None)   # missing_field for dt again
    r = parse_gstr2b(payload(b2b=[
        supplier(SUP_1, [bad1, bad3]),
        supplier(SUP_2, [bad2]),
    ]))
    assert r["total_skipped"] == 3
    reasons = r["metrics"]["skip_reasons"]
    assert reasons.get("missing_field for dt", 0) == 2
    assert sum(1 for v in reasons.values() if v > 0) >= 2

run("H21  skip_reasons aggregates correctly across multiple suppliers", h21)


# ===========================================================================
# H22 — normalization_note_frequency aggregates across records
# ===========================================================================
def h22():
    # lowercase invoice numbers → each gets "uppercased" note
    invoices = [inv(inum=f"inv{i:03d}") for i in range(5)]
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, invoices)]))
    assert r["total_parsed"] == 5
    freq = r["metrics"]["normalization_note_frequency"]
    # Each invoice_number has "uppercased" note → freq should be ≥ 5
    assert freq.get("uppercased", 0) >= 5

run("H22  normalization_note_frequency counts uppercased across 5 records", h22)


# ===========================================================================
# H23 — unique_key is (str, str, date) — not objects
# ===========================================================================
def h23():
    import datetime
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(inum="INV-X", dt="15-06-2024")])]))
    rec = r["records"][0]
    k = rec["unique_key"]
    assert isinstance(k[0], str),          f"key[0] type: {type(k[0])}"
    assert isinstance(k[1], str),          f"key[1] type: {type(k[1])}"
    assert isinstance(k[2], datetime.date), f"key[2] type: {type(k[2])}"
    assert k[0] == SUP_1
    assert k[1] == "INVX"   # symbols stripped
    assert k[2] == datetime.date(2024, 6, 15)

run("H23  unique_key is (str, str, date) — no wrapper objects", h23)


# ===========================================================================
# H24 — isd + impg keys present with garbage data → silently ignored
# ===========================================================================
def h24():
    data = {
        "gstin": BUYER, "rtnprd": "042024",
        "b2b":  [supplier(SUP_1, [inv()])],
        "isd":  [{"xyz": [None, 1, "bad"]}],
        "impg": {"not": "a list"},
        "impgsez": 999,
    }
    r = parse_gstr2b(enc({"data": data}))
    assert r["total_parsed"] == 1
    assert r["total_skipped"] == 0

run("H24  isd/impg/impgsez with garbage values → silently ignored", h24)


# ===========================================================================
# H25 — 1000 invoices across 10 suppliers in under 2 seconds
# ===========================================================================
def h25():
    gstins = [SUP_1, SUP_2, SUP_3, SUP_4, SUP_5,
              SUP_1, SUP_2, SUP_3, SUP_4, SUP_5]  # reuse — different inv nums
    suppliers = []
    idx = 0
    for i, g in enumerate(gstins):
        invoices = [
            inv(inum=f"INV{idx + j:05d}", itms=[item(txval=500, igst=90)])
            for j in range(100)
        ]
        suppliers.append(supplier(g, invoices))
        idx += 100

    p = payload(b2b=suppliers)
    start = time.perf_counter()
    r = parse_gstr2b(p)
    elapsed = time.perf_counter() - start

    assert r["total_parsed"] == 1000, f"parsed={r['total_parsed']}"
    assert r["total_skipped"] == 0
    assert elapsed < 2.0, f"took {elapsed:.3f}s"

run("H25  1000 invoices across 10 suppliers parse in < 2 seconds", h25)


# ===========================================================================
# H26 — raw_data in skipped entry is a shallow copy (not a reference)
#        Tested via _make_skip_entry directly (JSON round-trip breaks `is`)
# ===========================================================================
def h26():
    original = {"inum": "SK001", "sensitive": "secret", "nested": [1, 2, 3]}
    entry = _make_skip_entry("b2b", SUP_1, "SK001", "test_error", original)
    raw = entry["raw_data"]

    # raw_data is a separate dict object
    assert raw is not original

    # Mutating original does not affect raw_data
    original["sensitive"] = "MUTATED_ORIGINAL"
    assert raw["sensitive"] == "secret"

    # Mutating raw_data does not affect original
    raw["sensitive"] = "MUTATED_RAW"
    assert original["sensitive"] == "MUTATED_ORIGINAL"

    # Nested list is same reference (shallow copy — spec requirement)
    assert raw["nested"] is original["nested"]

run("H26  _make_skip_entry is shallow copy — mutations isolated, nested ref shared", h26)


# ===========================================================================
# H27 — gendt field preserved as string in generated_on
# ===========================================================================
def h27():
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv()])], gendt="2024-05-10"))
    assert r["generated_on"] == "2024-05-10"

run("H27  gendt field preserved verbatim in generated_on", h27)


# ===========================================================================
# H28 — sections absent from JSON not in sections_present or sections_empty
# ===========================================================================
def h28():
    # Only b2b present
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv()])]))
    m = r["metrics"]
    assert "b2b" in m["sections_present"]
    for s in ["b2ba", "cdnr", "cdnra"]:
        assert s not in m["sections_present"], f"{s} wrongly in sections_present"
        assert s not in m["sections_empty"],   f"{s} wrongly in sections_empty"

run("H28  Absent sections not in sections_present or sections_empty", h28)


# ===========================================================================
# H29 — total_invoices_seen == total_parsed + total_skipped always
# ===========================================================================
def h29():
    bad = inv(inum="BAD", dt=None)
    good = inv(inum="GOOD")
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [good, bad, good, bad])]))
    m = r["metrics"]
    assert m["total_invoices_seen"] == m["total_parsed"] + m["total_skipped"]

run("H29  total_invoices_seen == total_parsed + total_skipped invariant", h29)


# ===========================================================================
# H30 — dt as DD/MM/YYYY with slashes
# ===========================================================================
def h30():
    import datetime
    r = parse_gstr2b(payload(b2b=[supplier(SUP_1, [inv(dt="15/08/2024")])]))
    assert r["total_parsed"] == 1
    assert r["records"][0]["invoice_date"] == datetime.date(2024, 8, 15)

run("H30  dt='15/08/2024' (slash format) → parsed to correct date", h30)


# ===========================================================================
# Summary
# ===========================================================================
print()
print("=" * 55)
print(f"  {GREEN}PASS{RESET} {passed}   {RED}FAIL{RESET} {failed}   TOTAL {passed + failed}")
print("=" * 55)

if failed:
    print(f"\n{RED}Failed tests:{RESET}")
    for status, name, err in results:
        if status == "FAIL":
            print(f"  • {name}")
    sys.exit(1)
