"""
tests/test_zero_discrepancy_invariant.py
=========================================
Regression guard for the "false tax-structure mismatch" bug: a Purchase
Register file that only reports an aggregate total_tax_paise (no separate
IGST/CGST/SGST columns -- a very common real-world PR export shape) must
never cause exact-amount GSTR<->PR pairs to be blocked from L1/Matched.

Root cause (see app/services/matcher.py): the adapter coerces a missing
igst_paise/cgst_paise/sgst_paise to 0, and the matcher used to read that 0 as
proof the PR invoice was structurally CGST+SGST -- fabricating a tax-structure
conflict out of absent data and forcing exact-amount pairs into
L3_AMOUNT_MISMATCH / Review Required with a (correctly) zero displayed diff.

Ground-truth dataset (500 records), modeled on the two real production runs
that exposed this bug (both had igst_paise/cgst_paise/sgst_paise = None on
every single PR row):

  350 exact matches             -- identical taxable + total tax, PR side has
                                    no per-head tax breakdown, GSTR side has a
                                    real IGST figure. MUST be Matched (L1).
  100 genuine amount mismatches -- same missing-breakdown PR shape, but a
                                    real ~3% taxable difference. MUST stay in
                                    Review Required with the correct non-zero
                                    diff.
   50 genuine GSTIN typos       -- same PAN, checksum digit differs. MUST stay
                                    in Review Required (GSTIN_MISMATCH), never
                                    silently matched.

This test asserts EXACT counts against ground truth (not just "> 0") so it
fails loudly if this class of bug reappears.
"""
from __future__ import annotations

from datetime import date

from app.matching.engine import run_bidirectional_reconciliation
from app.services.matcher import normalize_invoice

PERIOD = date(2026, 5, 1)

N_EXACT = 350
N_AMOUNT_MISMATCH = 100
N_GSTIN_TYPO = 50
N_TOTAL = N_EXACT + N_AMOUNT_MISMATCH + N_GSTIN_TYPO


def _gstin(i: int) -> str:
    """Deterministic, distinct, well-formed 15-char GSTIN per index."""
    return f"27AABCU{i:04d}R1ZX"


def _gstin_typo(i: int) -> str:
    """Same PAN as _gstin(i) (chars [2:12]), different checksum digit --
    a real-world GSTIN typo, not a different supplier."""
    return f"27AABCU{i:04d}R1ZY"


def _gstr_row(
    rid: str, gstin: str, invoice: str, taxable_paise: int, igst_paise: int
) -> dict:
    return {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": invoice,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": taxable_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": igst_paise,
        "total_tax_paise": igst_paise,
    }


def _pr_row_missing_breakdown(
    rid: str, gstin: str, invoice: str, taxable_paise: int, total_tax_paise: int
) -> dict:
    """Mirrors the real production PR shape: only an aggregate total_tax_paise
    column, no separate IGST/CGST/SGST columns at all (None, not 0)."""
    return {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": invoice,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_date": "2026-05-10",
        "taxable_amount_paise": taxable_paise,
        "cgst_paise": None,
        "sgst_paise": None,
        "igst_paise": None,
        "total_tax_paise": total_tax_paise,
    }


def _build_dataset() -> tuple[list[dict], list[dict], set[str], set[str], set[str]]:
    gstr_records: list[dict] = []
    pr_records: list[dict] = []
    exact_ids: set[str] = set()
    mismatch_ids: set[str] = set()
    typo_ids: set[str] = set()

    for i in range(N_EXACT):
        gstin = _gstin(i)
        invoice = f"EXACT-{i:04d}"
        taxable = 500_000 + i * 137
        igst = int(round(taxable * 0.18))
        gid, pid = f"g_exact_{i}", f"p_exact_{i}"
        gstr_records.append(_gstr_row(gid, gstin, invoice, taxable, igst))
        pr_records.append(_pr_row_missing_breakdown(pid, gstin, invoice, taxable, igst))
        exact_ids.add(gid)

    for i in range(N_AMOUNT_MISMATCH):
        gstin = _gstin(N_EXACT + i)
        invoice = f"MISMATCH-{i:04d}"
        taxable = 800_000 + i * 211
        igst = int(round(taxable * 0.18))
        pr_taxable = int(round(taxable * 1.03))  # genuine 3% diff -- above L2, within L3
        gid, pid = f"g_mismatch_{i}", f"p_mismatch_{i}"
        gstr_records.append(_gstr_row(gid, gstin, invoice, taxable, igst))
        pr_records.append(
            _pr_row_missing_breakdown(pid, gstin, invoice, pr_taxable, igst)
        )
        mismatch_ids.add(gid)

    for i in range(N_GSTIN_TYPO):
        idx = N_EXACT + N_AMOUNT_MISMATCH + i
        gstin = _gstin(idx)
        gstin_pr = _gstin_typo(idx)
        invoice = f"TYPO-{i:04d}"
        taxable = 300_000 + i * 97
        igst = int(round(taxable * 0.18))
        gid, pid = f"g_typo_{i}", f"p_typo_{i}"
        gstr_records.append(_gstr_row(gid, gstin, invoice, taxable, igst))
        pr_records.append(
            _pr_row_missing_breakdown(pid, gstin_pr, invoice, taxable, igst)
        )
        typo_ids.add(gid)

    return gstr_records, pr_records, exact_ids, mismatch_ids, typo_ids


def _run():
    gstr, pr, exact_ids, mismatch_ids, typo_ids = _build_dataset()
    res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
    return res, exact_ids, mismatch_ids, typo_ids


def test_dataset_size_sanity():
    gstr, pr, exact_ids, mismatch_ids, typo_ids = _build_dataset()
    assert len(gstr) == N_TOTAL == 500
    assert len(pr) == N_TOTAL
    assert len(exact_ids) == N_EXACT
    assert len(mismatch_ids) == N_AMOUNT_MISMATCH
    assert len(typo_ids) == N_GSTIN_TYPO


def test_exact_matches_are_all_matched_at_l1():
    """The core regression: PR rows with no IGST/CGST/SGST breakdown must not
    block exact-amount pairs from L1/Matched."""
    res, exact_ids, _mismatch_ids, _typo_ids = _run()
    matched_gstr_ids = {m["gstr_id"] for m in res["matched"]}
    missing = exact_ids - matched_gstr_ids
    assert not missing, (
        f"{len(missing)} exact-match records were NOT clean-matched "
        f"(false tax-structure-mismatch regression): {sorted(missing)[:10]}"
    )
    for m in res["matched"]:
        if m["gstr_id"] in exact_ids:
            assert m["match_level"] == 1, (
                f"{m['gstr_id']} matched but at level {m['match_level']}, expected 1"
            )


def test_genuine_amount_mismatches_stay_in_review_with_nonzero_diff():
    """Proves the fix does not over-correct: a real amount diff, even with the
    same missing-breakdown PR shape, must still be flagged with its true,
    non-zero discrepancy -- never silently zeroed out."""
    res, _exact_ids, mismatch_ids, _typo_ids = _run()
    review_by_gid = {r["gstr_id"]: r for r in res["review_required"]}
    missing = mismatch_ids - set(review_by_gid)
    assert not missing, (
        f"{len(missing)} genuine amount-mismatch records were not routed to "
        f"review_required: {sorted(missing)[:10]}"
    )
    for gid in mismatch_ids:
        diff = review_by_gid[gid].get("taxable_diff_paise")
        assert diff is not None and diff > 0, (
            f"{gid}: genuine amount mismatch must have a non-zero "
            f"taxable_diff_paise, got {diff}"
        )


def test_gstin_typos_stay_in_review_never_silently_matched():
    res, _exact_ids, _mismatch_ids, typo_ids = _run()
    matched_gstr_ids = {m["gstr_id"] for m in res["matched"]}
    silently_matched = typo_ids & matched_gstr_ids
    assert not silently_matched, (
        f"GSTIN-typo records must never be silently auto-matched: "
        f"{sorted(silently_matched)}"
    )


def test_exact_ground_truth_counts():
    """Exact counts, not just '> 0' -- the whole point of this regression test."""
    res, _exact_ids, _mismatch_ids, _typo_ids = _run()
    stats = res["stats"]
    assert stats["matched_count"] == N_EXACT, (
        f"Expected exactly {N_EXACT} matched, got {stats['matched_count']}"
    )
    assert stats["review_required_count"] == N_AMOUNT_MISMATCH + N_GSTIN_TYPO, (
        f"Expected exactly {N_AMOUNT_MISMATCH + N_GSTIN_TYPO} review_required, "
        f"got {stats['review_required_count']}"
    )
    assert stats["missed_itc_count"] == 0, (
        f"No records in this dataset should fall into missed_itc, "
        f"got {stats['missed_itc_count']}"
    )
    assert stats["sanity_passed"] is True, "Engine sanity check must pass"
