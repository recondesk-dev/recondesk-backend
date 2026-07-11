"""
tests/test_credible_candidate_contention.py
=============================================
Regression tests for CREDIBLE_CANDIDATE_FALLBACK contention handling.

Product rule (Missed-ITC false-positive fix): same GSTIN + amount/date
proximity with NO invoice-number relationship is NOT credible identity.
Those pairs must fall through to Missed ITC / ITC at Risk — never Review
Required via retired criteria-1 (C1).

Contention ranking still applies when multiple GSTR rows share real invoice
identity evidence (exact normalized invoice or format variant) for one PR.
"""

import uuid
from datetime import date
from typing import Any

from app.matching.engine import run_bidirectional_reconciliation

PERIOD = date(2026, 6, 1)
INV_DATE = date(2026, 6, 10)
GSTIN_A = "29AAAAA1234A1Z1"


def _rec(
    gstin: str,
    inv: str,
    inv_norm: str,
    inv_date: date = INV_DATE,
    taxable: int = 100_00000,
    total_tax: int = 18_00000,
    igst: int = 18_00000,
    cgst: int = 0,
    sgst: int = 0,
    cess: int = 0,
    name: str = "Synthetic Supplier",
    **kw: Any,
) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv_norm,
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "total_tax_paise": total_tax,
        "igst_paise": igst,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "cess_paise": cess,
        "supplier_name": name,
        **kw,
    }


_gstr = _rec
_pr = _rec


def _run(gstr, pr):
    return run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)


def _review_by_gid(res): return {m["gstr_id"]: m for m in res["review_required"]}
def _missed_ids(res): return {m["gstr_id"] for m in res["missed_itc"]}


def test_amount_only_same_gstin_is_missed_itc_not_review():
    """Retired C1: unrelated invoice numbers + similar tax → Missed ITC."""
    p = _pr(gstin=GSTIN_A, inv="PRBASEONE", inv_norm="PRBASEONE", total_tax=20_00000)
    g = _gstr(gstin=GSTIN_A, inv="ZQPCLOSEONE", inv_norm="ZQPCLOSEONE",
              total_tax=20_50000)  # 2.5% diff, no invoice relationship

    res = _run([g], [p])
    assert g["id"] in _missed_ids(res)
    assert g["id"] not in _review_by_gid(res)
    assert res["stats"]["wrongful_risk_count"] == 1
    assert res["stats"]["sanity_passed"] is True


def test_two_amount_only_claimants_both_missed_not_contended_review():
    """Two unrelated GSTR rows near one PR tax → both Missed, PR → ITC at Risk."""
    p = _pr(gstin=GSTIN_A, inv="PRBASETWO", inv_norm="PRBASETWO", total_tax=20_00000)
    g_close = _gstr(gstin=GSTIN_A, inv="ZQPCLOSETWO", inv_norm="ZQPCLOSETWO",
                    total_tax=20_50000)
    g_far = _gstr(gstin=GSTIN_A, inv="WKTFARTWO", inv_norm="WKTFARTWO",
                  total_tax=20_90000)

    res = _run([g_close, g_far], [p])
    assert g_close["id"] in _missed_ids(res)
    assert g_far["id"] in _missed_ids(res)
    assert res["stats"]["review_required_count"] == 0
    assert res["stats"]["wrongful_risk_count"] == 1


def test_format_variant_amount_contention_closer_wins():
    """Two format-variant claimants for one PR: closer amount wins, loser reviews."""
    # GSTR FZ/2026/03763 ↔ PR F3763 style (engine format-variant), with amount gaps.
    p = _pr(
        gstin=GSTIN_A,
        inv="F3763",
        inv_norm="F3763",
        taxable=4_166_710,
        total_tax=750_000,
        igst=750_000,
    )
    g_close = _gstr(
        gstin=GSTIN_A,
        inv="FZ/2026/03763",
        inv_norm="FZ202603763",
        taxable=4_200_000,
        total_tax=760_000,  # closer
        igst=760_000,
    )
    g_far = _gstr(
        gstin=GSTIN_A,
        inv="FZ/2026/03763-B",
        inv_norm="FZ202603763B",
        taxable=4_500_000,
        total_tax=820_000,  # farther but still within 50% if variant matches
        igst=820_000,
    )
    # Only g_close shares format-variant identity with F3763; g_far's extra B
    # should not be a format variant — so only one credible claimant.
    res = _run([g_close, g_far], [p])
    review = _review_by_gid(res)
    # g_close should link (review or matched); g_far should be missed
    assert g_far["id"] in _missed_ids(res) or (
        g_far["id"] in review and review[g_far["id"]].get("review_reason")
        == "PR_CLAIMED_BY_BETTER_MATCH"
    )
    assert g_close["id"] not in _missed_ids(res)


def test_uncontended_exact_invoice_amount_mismatch_still_reviews():
    """Same GSTIN + same invoice + amount gap → Review, never Missed."""
    p = _pr(gstin=GSTIN_A, inv="INV-SHARED-1", inv_norm="INVSHARED1", total_tax=20_00000)
    g = _gstr(gstin=GSTIN_A, inv="INV-SHARED-1", inv_norm="INVSHARED1",
              total_tax=25_00000)  # 25% amount gap

    res = _run([g], [p])
    review = _review_by_gid(res)
    assert g["id"] in review
    assert g["id"] not in _missed_ids(res)
    assert review[g["id"]]["pr_id"] == p["id"]
