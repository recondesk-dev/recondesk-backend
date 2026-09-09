"""Regression coverage for GSTR-2B records with a structurally malformed
supplier GSTIN (``ctin``).

Previously, ANY GSTIN normalization failure (missing, wrong length, or wrong
pattern) caused the parser to silently drop the invoice entirely — it never
entered reconciliation, never appeared in Total GSTR, and its legitimate PR
counterpart (if any) was left to fall through to "ITC at Risk — Not Reflected
in GSTR-2B", implying the supplier never filed when in fact they did (just
with a corrupted GSTIN digit).

Fix: a GSTIN that is the right length (15) but fails the structural
GSTIN/PAN pattern (``invalid_format``) is now RETAINED, flagged
``gstin_format_invalid=True``, and routed through a dedicated fallback match
pass that ignores GSTIN entirely (invoice_number + amount + trade name only).
GSTINs that are hopelessly short/garbage (``invalid_length``) or missing
(``empty``) are still dropped — there is no usable signal to retain.

Layers covered:
  1. Parser (app.parsers.gstr2b_parser): retain vs. drop behavior + new
     ``gstin_format_invalid`` flag + ``gstin_format_invalid_count`` metric.
  2. Adapter (app.services.reconciliation_record_adapter): flag propagation
     into the matcher row.
  3. Engine (app.services.reconciliation / app.matching.engine): the new
     GSTIN_FORMAT_INVALID fallback pass, review_required routing with a note,
     missed_itc fallback tagging, and the new invalid_gstin_* summary stats.
"""
from datetime import date

import pytest

from app.matching.engine import run_bidirectional_reconciliation
from app.parsers.gstr2b_parser import SKIP_INVALID_GSTIN, parse_gstr2b
from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row

BUYER_GSTIN = "27AAAAA1234A1ZP"
SUPPLIER_1 = "29ABCDE1234F1ZW"

# Same length (15) and same characters as SUPPLIER_1 except the mandatory
# literal 'Z' at position 13 is corrupted to 'X' -> fails GSTIN_REGEX
# (invalid_format), NOT invalid_length. This mirrors the real-world pattern
# found in production data: a single-character checksum/format typo.
MALFORMED_15CHAR_GSTIN = "29ABCDE1234F1XW"


def _payload(*, gstin: str = BUYER_GSTIN, rtnprd: str = "052026", b2b=None) -> bytes:
    import json

    data: dict = {"gstin": gstin, "rtnprd": rtnprd}
    if b2b is not None:
        data["b2b"] = b2b
    return json.dumps({"data": data}).encode("utf-8")


def _invoice(inum="INV001", dt="01-05-2026", val=1000, pos="27") -> dict:
    return {"inum": inum, "dt": dt, "val": val, "pos": pos, "rev": "N", "itcavl": "Y"}


# ===========================================================================
# 1. Parser layer
# ===========================================================================


def test_malformed_15char_gstin_is_retained_not_dropped():
    result = parse_gstr2b(
        _payload(b2b=[{"ctin": MALFORMED_15CHAR_GSTIN, "trdnm": "Acme Traders", "inv": [_invoice()]}])
    )
    assert result["total_skipped"] == 0
    assert result["total_parsed"] == 1
    rec = result["records"][0]
    assert rec["gstin_format_invalid"] is True
    assert rec["supplier_gstin"] == MALFORMED_15CHAR_GSTIN


def test_malformed_15char_gstin_counted_in_metrics():
    result = parse_gstr2b(
        _payload(b2b=[{"ctin": MALFORMED_15CHAR_GSTIN, "inv": [_invoice()]}])
    )
    assert result["gstin_format_invalid_count"] == 1
    assert result["metrics"]["gstin_format_invalid_count"] == 1


def test_clean_gstin_is_never_flagged():
    result = parse_gstr2b(_payload(b2b=[{"ctin": SUPPLIER_1, "inv": [_invoice()]}]))
    rec = result["records"][0]
    assert rec["gstin_format_invalid"] is False
    assert result["gstin_format_invalid_count"] == 0


def test_hopelessly_short_gstin_still_dropped():
    """A garbage string with no real length/shape (invalid_length) carries no
    usable signal and must remain dropped -- only right-length-wrong-pattern
    (invalid_format) GSTINs are retained."""
    result = parse_gstr2b(_payload(b2b=[{"ctin": "SHORT", "inv": [_invoice()]}]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 1
    assert result["skipped"][0]["category"] == SKIP_INVALID_GSTIN
    assert result["gstin_format_invalid_count"] == 0


def test_missing_gstin_still_dropped():
    result = parse_gstr2b(_payload(b2b=[{"ctin": "", "inv": [_invoice()]}]))
    assert result["total_parsed"] == 0
    assert result["total_skipped"] == 1


# ===========================================================================
# 2. Adapter layer
# ===========================================================================


def test_adapter_propagates_gstin_format_invalid_flag():
    row = {
        "id": "g1",
        "record_data": {
            "supplier_gstin": MALFORMED_15CHAR_GSTIN,
            "invoice_number": "INV001",
            "gstin_format_invalid": True,
        },
    }
    matcher_row = gstr_db_row_to_matcher_row(row)
    assert matcher_row["gstin_format_invalid"] is True


def test_adapter_defaults_flag_to_false_when_absent():
    row = {
        "id": "g1",
        "record_data": {"supplier_gstin": SUPPLIER_1, "invoice_number": "INV001"},
    }
    matcher_row = gstr_db_row_to_matcher_row(row)
    assert matcher_row["gstin_format_invalid"] is False


# ===========================================================================
# 3. Engine layer — GSTIN_FORMAT_INVALID fallback pass
# ===========================================================================


def _gstr(id, gstin, inv, taxable_rs, tax_rs=None, dt="2026-05-01", name="", gstin_format_invalid=False):
    tax_rs = int(taxable_rs * 0.18) if tax_rs is None else tax_rs
    return {
        "id": id,
        "supplier_gstin": gstin,
        "supplier_name": name,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": tax_rs * 100,
        "gstin_format_invalid": gstin_format_invalid,
    }


def _pr(id, gstin, inv, taxable_rs, tax_rs=None, dt="2026-05-01", name=""):
    tax_rs = int(taxable_rs * 0.18) if tax_rs is None else tax_rs
    return {
        "id": id,
        "supplier_gstin": gstin,
        "supplier_name": name,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt) if dt else None,
        "taxable_amount_paise": taxable_rs * 100,
        "total_tax_paise": tax_rs * 100,
    }


def test_gstin_format_invalid_with_pr_match_becomes_gstin_mismatch_review():
    """The GSTR record's GSTIN is malformed/untrustworthy, but a PR row with the
    same invoice number, same amount, and a matching trade name exists under a
    DIFFERENT (valid) GSTIN. This must be resolved via invoice+amount+name and
    classified as Review Required (GSTIN_MISMATCH) with an explanatory note —
    never silently lost, and never counted as clean/verified ITC."""
    gstr = [
        _gstr(
            "g1", MALFORMED_15CHAR_GSTIN, "INV9001", 50000,
            name="Acme Traders Pvt Ltd", gstin_format_invalid=True,
        )
    ]
    pr = [_pr("p1", SUPPLIER_1, "INV9001", 50000, name="Acme Traders Pvt Ltd")]

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    assert len(res["missed_itc"]) == 0
    assert len(res["review_required"]) == 1
    row = res["review_required"][0]
    assert row["gstr_id"] == "g1"
    assert row["pr_id"] == "p1"
    assert row["review_reason"] == "GSTIN_MISMATCH"
    assert row["gstin_format_invalid"] is True
    assert row["note"] == "Supplier GSTIN has invalid format — verify manually"

    stats = res["stats"]
    assert stats["invalid_gstin_count"] == 1
    assert stats["invalid_gstin_matched_count"] == 1
    assert stats["invalid_gstin_unresolved_count"] == 0


def test_gstin_format_invalid_with_no_pr_match_falls_to_missed_itc_with_note():
    """No PR row anywhere matches this invoice number (even ignoring GSTIN) —
    the record must still land in Missed ITC (it is a genuine GSTR-2B line
    item) but flagged distinctly so a CA doesn't treat it as fully-verified,
    clean ITC available for claim."""
    gstr = [
        _gstr(
            "g1", MALFORMED_15CHAR_GSTIN, "INV9002", 75000,
            gstin_format_invalid=True,
        )
    ]
    pr: list = []

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    assert len(res["review_required"]) == 0
    assert len(res["missed_itc"]) == 1
    mi = res["missed_itc"][0]
    assert mi["gstr_id"] == "g1"
    assert mi["gstin_format_invalid"] is True
    assert mi["mismatch_reason"] == "GSTIN format invalid — could not verify against PR"

    stats = res["stats"]
    assert stats["invalid_gstin_count"] == 1
    assert stats["invalid_gstin_matched_count"] == 0
    assert stats["invalid_gstin_unresolved_count"] == 1


def test_gstin_format_invalid_does_not_match_wrong_invoice_or_amount():
    """The fallback pass must not become an anything-goes fuzzy match: a PR row
    with a completely different invoice number and amount must NOT be picked
    up, even though the GSTR record's GSTIN can't be trusted."""
    gstr = [_gstr("g1", MALFORMED_15CHAR_GSTIN, "INV9003", 100000, gstin_format_invalid=True)]
    pr = [_pr("p1", SUPPLIER_1, "INV_UNRELATED", 999999)]

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    assert len(res["review_required"]) == 0
    assert len(res["missed_itc"]) == 1
    # The unrelated PR row remains unconsumed -> ITC at Risk, not silently eaten.
    assert len(res["wrongful_itc_risk"]) == 1
    assert res["wrongful_itc_risk"][0]["id"] == "p1"


def test_normal_gstin_mismatch_path_unaffected_by_new_flag():
    """Sanity: GSTR records WITHOUT gstin_format_invalid continue to use the
    pre-existing GSTIN_MISMATCH path (exact-length, near-miss GSTIN) exactly as
    before -- the new fallback pass only activates for flagged records."""
    gstr = [_gstr("g1", "27AAAAA0000A1Z5", "INV9004", 60000)]
    pr = [_pr("p1", "27AAAAA0000A1Z6", "INV9004", 60000)]  # 1-char GSTIN typo

    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=date(2026, 5, 1))

    assert len(res["review_required"]) == 1
    row = res["review_required"][0]
    assert row["review_reason"] == "GSTIN_MISMATCH"
    assert "gstin_format_invalid" not in row
    assert row["note"] is None
    assert res["stats"]["invalid_gstin_count"] == 0
