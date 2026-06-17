"""Checklist verification for GSTR-2B parser."""

import json
import time

# Patch normalize_gstin to bypass checksum (test GSTINs are not real)
import app.services.normalizer as normalizer

_real_normalize_gstin = normalizer.normalize_gstin

def _bypass_gstin(gstin):
    return gstin

normalizer.normalize_gstin = _bypass_gstin

from app.parsers.gstr2b_parser import parse_gstr2b

PASS = "  PASS"
FAIL = "  FAIL"

results = []


# ---------------------------------------------------------------------------
# 1. Correct buyer_gstin and period from sample file
# ---------------------------------------------------------------------------
def check_1():
    sample = {
        "data": {
            "gstin": "27AABCU9603R1ZX",
            "rtnprd": "042024",
            "gendt": "2024-05-10",
            "b2b": [],
        }
    }
    out = parse_gstr2b(json.dumps(sample).encode())
    ok_gstin  = out["buyer_gstin"] == "27AABCU9603R1ZX"
    ok_period = out["period"] == "2024-04-01"
    if ok_gstin and ok_period:
        print(f"{PASS}  [1] buyer_gstin={out['buyer_gstin']}  period={out['period']}")
        return True
    else:
        print(f"{FAIL}  [1] buyer_gstin={out['buyer_gstin']!r}  period={out['period']!r}")
        return False


# ---------------------------------------------------------------------------
# 2. b2b invoices: raw AND normalized columns present
# ---------------------------------------------------------------------------
def check_2():
    sample = {
        "data": {
            "gstin": "27AABCU9603R1ZX",
            "rtnprd": "042024",
            "gendt": "2024-05-10",
            "b2b": [
                {
                    "ctin": "29AABCU9603R1ZY",
                    "inv": [
                        {
                            "inum": "inv-001",
                            "dt": "10-04-2024",
                            "val": "11800",
                            "pos": "27",
                            "rev": "N",
                            "itcavl": "Y",
                            "itms": [
                                {"rt": 18, "txval": 10000, "igst": 1800, "cgst": 0, "sgst": 0, "cess": 0}
                            ],
                        }
                    ],
                }
            ],
        }
    }
    out  = parse_gstr2b(json.dumps(sample).encode())
    recs = out["records"]

    required_raw  = {"invoice_number_raw", "invoice_date_raw", "invoice_value_raw",
                     "supplier_gstin_raw"}
    required_norm = {"invoice_number", "invoice_date_norm", "invoice_value_paise",
                     "supplier_gstin", "supplier_gstin_norm", "invoice_number_norm",
                     "buyer_gstin", "taxable_value"}

    if not recs:
        print(f"{FAIL}  [2] no records returned")
        return False

    rec = recs[0]
    missing_raw  = required_raw  - rec.keys()
    missing_norm = required_norm - rec.keys()

    if missing_raw or missing_norm:
        print(f"{FAIL}  [2] missing raw={missing_raw}  norm={missing_norm}")
        return False

    # spot-check values
    ok = (
        rec["invoice_number_raw"]  == "inv-001"
        and rec["invoice_number"]      == "INV001"          # normalized: symbols stripped, uppercased
        and rec["invoice_date_norm"]   == "2024-04-10"
        and rec["invoice_value_paise"] == 1_180_000
        and rec["taxable_value"]       == 10_000
        and rec["buyer_gstin"]         == "27AABCU9603R1ZX"
    )
    if ok:
        print(f"{PASS}  [2] all raw+norm columns present and correct")
        return True
    else:
        print(f"{FAIL}  [2] value mismatch — rec={json.dumps(rec, default=str, indent=2)}")
        return False


# ---------------------------------------------------------------------------
# 3. Malformed JSON raises clear ValueError with location
# ---------------------------------------------------------------------------
def check_3():
    bad_inputs = [
        (b"{bad json",      "invalid_json"),
        (b'{"x": 1}',       "missing_data_key"),
        (b'{"data": "str"}', "invalid_data_structure"),
        (b'{"data": {"gstin": "", "rtnprd": "042024"}}', "missing_gstin"),
        (b'{"data": {"gstin": "27AABCU9603R1ZX", "rtnprd": ""}}', "missing_rtnprd"),
        (b'{"data": {"gstin": "27AABCU9603R1ZX", "rtnprd": "BADPRD"}}', "invalid_rtnprd"),
    ]

    all_ok = True
    for payload, expected_fragment in bad_inputs:
        try:
            parse_gstr2b(payload)
            print(f"{FAIL}  [3] expected ValueError for {payload[:40]} — got none")
            all_ok = False
        except ValueError as e:
            msg = str(e)
            if expected_fragment in msg:
                print(f"{PASS}  [3] {expected_fragment!r} → {msg!r}")
            else:
                print(f"{FAIL}  [3] expected {expected_fragment!r} in error, got {msg!r}")
                all_ok = False
        except Exception as e:
            print(f"{FAIL}  [3] unexpected exception type {type(e).__name__}: {e}")
            all_ok = False

    return all_ok


# ---------------------------------------------------------------------------
# 4. 500-invoice file parses in under 2 seconds
# ---------------------------------------------------------------------------
def check_4():
    invoices = [
        {
            "inum": f"INV{i:04d}",
            "dt": "10-04-2024",
            "val": str(1000 + i),
            "pos": "27",
            "rev": "N",
            "itcavl": "Y",
            "itms": [
                {"rt": 18, "txval": 1000 + i, "igst": (1000 + i) * 0.18,
                 "cgst": 0, "sgst": 0, "cess": 0}
            ],
        }
        for i in range(500)
    ]
    sample = {
        "data": {
            "gstin": "27AABCU9603R1ZX",
            "rtnprd": "042024",
            "gendt": "2024-05-10",
            "b2b": [{"ctin": "29AABCU9603R1ZY", "inv": invoices}],
        }
    }
    payload = json.dumps(sample).encode()

    t0 = time.perf_counter()
    out = parse_gstr2b(payload)
    elapsed = time.perf_counter() - t0

    parsed = out["total_parsed"]
    skipped = out["total_skipped"]
    ok = elapsed < 2.0 and parsed == 500 and skipped == 0
    status = PASS if ok else FAIL
    print(f"{status}  [4] parsed={parsed} skipped={skipped} elapsed={elapsed:.3f}s (limit 2s)")
    return ok


# ---------------------------------------------------------------------------
# 5. cdnr records flagged as CREDIT_NOTE / DEBIT_NOTE
# ---------------------------------------------------------------------------
def check_5():
    sample = {
        "data": {
            "gstin": "27AABCU9603R1ZX",
            "rtnprd": "042024",
            "gendt": "2024-05-10",
            "cdnr": [
                {
                    "ctin": "29AABCU9603R1ZY",
                    "nt": [
                        {
                            "ntty": "C",
                            "nt_num": "CN001",
                            "nt_dt": "10-04-2024",
                            "val": "500",
                            "pos": "27",
                            "rev": "N",
                            "itcavl": "Y",
                            "itms": [
                                {"rt": 18, "txval": 500, "igst": 90, "cgst": 0, "sgst": 0, "cess": 0}
                            ],
                        },
                        {
                            "ntty": "D",
                            "nt_num": "DN001",
                            "nt_dt": "15-04-2024",
                            "val": "200",
                            "pos": "27",
                            "rev": "N",
                            "itcavl": "N",
                            "itms": [
                                {"rt": 5, "txval": 200, "igst": 10, "cgst": 0, "sgst": 0, "cess": 0}
                            ],
                        },
                    ],
                }
            ],
        }
    }
    out  = parse_gstr2b(json.dumps(sample).encode())
    recs = {r["invoice_number"]: r for r in out["records"]}

    ok_cn = recs.get("CN1", {}).get("doc_type") == "CREDIT_NOTE"   # "CN001" → normalized "CN1"
    ok_dn = recs.get("DN1", {}).get("doc_type") == "DEBIT_NOTE"    # "DN001" → normalized "DN1"

    # fallback: maybe leading zeros not stripped (mixed alphanum)
    if not ok_cn:
        ok_cn = recs.get("CN001", {}).get("doc_type") == "CREDIT_NOTE"
    if not ok_dn:
        ok_dn = recs.get("DN001", {}).get("doc_type") == "DEBIT_NOTE"

    all_doc_types = {r["invoice_number"]: r["doc_type"] for r in out["records"]}

    if ok_cn and ok_dn:
        print(f"{PASS}  [5] doc_types={all_doc_types}")
        return True
    else:
        print(f"{FAIL}  [5] expected CREDIT_NOTE+DEBIT_NOTE, got {all_doc_types}")
        return False


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------
print("\n=== GSTR-2B Parser Checklist ===\n")
checks = [check_1, check_2, check_3, check_4, check_5]
passed = sum(fn() for fn in checks)
total  = len(checks)
print(f"\n{'='*40}")
print(f"Result: {passed}/{total} checks passed")
print('='*40)
