"""
tests/test_credible_candidate_contention.py
=============================================
Regression tests for the CREDIBLE_CANDIDATE_FALLBACK contention fix in
app/services/reconciliation.py (~lines 1417-1478).

Bug class: when two different, still-unconsumed GSTR invoices are BOTH
credible candidates (per the C1-C4 test) for the SAME still-unconsumed PR
row, the phase must deterministically award the PR to the closer match
(lowest identity tier, then lowest amount diff_pct, then lowest date delta --
the same global-ranking key the earlier L1 order-independence fix
established), and route the loser to Review Required with an explanatory
note -- never silently to Missed ITC, and never let the loser "steal" the PR
out from under the winner.

IMPORTANT SCOPING NOTE #1 (why every test fixture below uses tier-1 / C1
identity, i.e. same GSTIN + amount/date proximity with NO invoice-number
relationship at all):
Verified empirically while writing these tests -- any candidate pair that
would qualify under C2/C3 (exact normalized invoice match) or C4 (format
variant) is, in practice, ALREADY claimed earlier by a separate, also
order-dependent, per-GSTR sequential pass: INVOICE_MATCH_AMOUNT_REVIEW
(reconciliation.py ~lines 1223-1316, Passes 1-3). That pass runs BEFORE
CREDIBLE_CANDIDATE_FALLBACK and has NO global ranking of its own -- for same
GSTIN + exact-normalized-invoice it has literally no amount cap (Pass 1), and
for same GSTIN + format-variant it also has no amount cap (Pass 3). So for
any PR still available at that point, it is claimed by whichever GSTR
happens to appear earlier in `unconsumed_gstr`'s iteration order, and
CREDIBLE_CANDIDATE_FALLBACK's own C2/C3/C4 criteria never get a chance to
matter for that PR. This was explicitly out of scope for this fix (the task
was scoped to "the CREDIBLE_CANDIDATE_FALLBACK phase... do not change the
C1-C4 threshold logic itself, only the assignment order/contention
resolution around it") and is flagged to the user as a likely follow-up.
The only tier that genuinely reaches CREDIBLE_CANDIDATE_FALLBACK's own
candidate pool uncontested by that earlier pass is C1 (same GSTIN + amount
within 5% + date within 45 days, with NO invoice-number check at all) --
so that's what every fixture below exercises.

IMPORTANT SCOPING NOTE #2:
The 5 "PR-theft" pairs verified as REAL_THEFT in verification_13_pairs.csv
(pairs 1, 2, 6, 9, 11) are NOT exercised by this fix either, for a related
but distinct reason: their "thief" GSTR invoice is resolved as a clean,
100%-confidence, exact PHASE 1 match (match_level=1) -- even earlier than
INVOICE_MATCH_AMOUNT_REVIEW -- so the PR row is already gone from every
later phase's candidate pool, including this one, by the time the "victim"
is considered. test_real_theft_pairs_unchanged_by_this_fix below documents
that explicitly with the real field values, rather than asserting the
(false) claim that they now land in Review Required.

Run:
    python3 -m pytest tests/test_credible_candidate_contention.py -v
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


def _matched_by_gid(res): return {m["gstr_id"]: m for m in res["matched"]}
def _review_by_gid(res): return {m["gstr_id"]: m for m in res["review_required"]}
def _missed_ids(res): return {m["gstr_id"] for m in res["missed_itc"]}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Basic contention: two C1-tier credible claimants (same GSTIN, amount
#    proximity only, deliberately unrelated invoice numbers so neither Phase 1
#    nor INVOICE_MATCH_AMOUNT_REVIEW can pick them up first) for one PR.
#    Closer amount (2.5% diff) must win; farther one (4.5% diff, still within
#    the 5% C1 cap) must lose to Review Required with an explanatory note,
#    NOT Missed ITC, and must NOT also consume the PR.
# ─────────────────────────────────────────────────────────────────────────────
def test_closer_amount_wins_loser_routes_to_review_not_missed():
    # Invoice numbers are deliberately pure-alphabetic and share no digits at
    # all (see module docstring note #1): any accidental shared numeric
    # substring would trip the is_invoice_format_variant() fuzzy fallback and
    # get claimed by the earlier INVOICE_MATCH_AMOUNT_REVIEW pass instead of
    # ever reaching CREDIBLE_CANDIDATE_FALLBACK's own C1 criterion.
    p = _pr(gstin=GSTIN_A, inv="PRBASEONE", inv_norm="PRBASEONE", total_tax=20_00000)
    g_close = _gstr(gstin=GSTIN_A, inv="ZQPCLOSEONE", inv_norm="ZQPCLOSEONE",
                     total_tax=20_50000)   # 2.5% diff
    g_far = _gstr(gstin=GSTIN_A, inv="WKTFARONE", inv_norm="WKTFARONE",
                   total_tax=20_90000)     # 4.5% diff (still within the 5% C1 cap)

    res = _run([g_close, g_far], [p])
    review = _review_by_gid(res)

    assert g_close["id"] in review, "Closer amount-match must win the PR"
    assert review[g_close["id"]]["pr_id"] == p["id"]
    assert review[g_close["id"]]["review_reason"] != "PR_CLAIMED_BY_BETTER_MATCH"

    assert g_far["id"] not in _missed_ids(res), (
        "Loser of a genuine credible-candidate contention must NOT fall through "
        "to Missed ITC -- it had real evidence, it just lost to a closer match."
    )
    assert g_far["id"] in review, "Loser must land in Review Required"
    loser_row = review[g_far["id"]]
    assert loser_row["pr_id"] == "", (
        "Loser must NOT be recorded as having consumed the contended PR row"
    )
    assert loser_row["review_reason"] == "PR_CLAIMED_BY_BETTER_MATCH"
    assert g_close["id"] in (loser_row.get("note") or ""), (
        "Loser's note must identify which invoice won the contended PR"
    )

    # Sanity: every GSTR row accounted for exactly once (matched+missed+review == total)
    assert res["stats"]["sanity_passed"], res["stats"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Tie-break: equal diff_pct -> smaller date delta wins.
# ─────────────────────────────────────────────────────────────────────────────
def test_equal_amount_diff_ties_broken_by_date_delta():
    p = _pr(gstin=GSTIN_A, inv="PRBASETWO", inv_norm="PRBASETWO",
             total_tax=20_00000, inv_date=date(2026, 6, 10))
    g_near_date = _gstr(gstin=GSTIN_A, inv="ZQPNEARTWO", inv_norm="ZQPNEARTWO",
                         total_tax=20_50000, inv_date=date(2026, 6, 12))   # 2-day gap
    g_far_date = _gstr(gstin=GSTIN_A, inv="WKTFARTWO", inv_norm="WKTFARTWO",
                        total_tax=20_50000, inv_date=date(2026, 6, 30))    # 20-day gap
    # Same 2.5% amount diff for both -- date delta must be the deciding factor.

    res = _run([g_near_date, g_far_date], [p])
    review = _review_by_gid(res)

    assert review[g_near_date["id"]]["pr_id"] == p["id"], "Closer date must win the tie"
    assert review[g_far_date["id"]]["pr_id"] == "", "Farther-date loser must not steal the PR"
    assert review[g_far_date["id"]]["review_reason"] == "PR_CLAIMED_BY_BETTER_MATCH"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Order independence: swapping input order must not change the winner.
#    (Same bug class as the earlier L1 order-independence fix, one phase later.)
# ─────────────────────────────────────────────────────────────────────────────
def test_contention_resolution_is_order_independent():
    def build():
        p = _pr(gstin=GSTIN_A, inv="PRBASETHREE", inv_norm="PRBASETHREE", total_tax=20_00000)
        g_close = _gstr(gstin=GSTIN_A, inv="ZQPCLOSETHREE", inv_norm="ZQPCLOSETHREE",
                         total_tax=20_50000)   # 2.5% diff
        g_far = _gstr(gstin=GSTIN_A, inv="WKTFARTHREE", inv_norm="WKTFARTHREE",
                       total_tax=20_90000)     # 4.5% diff
        return p, g_close, g_far

    p1, g_close1, g_far1 = build()
    res_forward = _run([g_close1, g_far1], [p1])

    p2, g_close2, g_far2 = build()
    res_reversed = _run([g_far2, g_close2], [p2])

    review_fwd = _review_by_gid(res_forward)
    review_rev = _review_by_gid(res_reversed)

    assert review_fwd[g_close1["id"]]["pr_id"] == p1["id"]
    assert review_rev[g_close2["id"]]["pr_id"] == p2["id"], (
        "Winner must be decided by match quality, not input list order"
    )
    assert review_fwd[g_far1["id"]]["pr_id"] == ""
    assert review_rev[g_far2["id"]]["pr_id"] == ""


# ─────────────────────────────────────────────────────────────────────────────
# 4. Three-way contention: single winner, both losers reference the SAME
#    actual winner (not each other) in their note.
# ─────────────────────────────────────────────────────────────────────────────
def test_three_way_contention_single_winner_correct_loser_notes():
    p = _pr(gstin=GSTIN_A, inv="PRBASEFOUR", inv_norm="PRBASEFOUR", total_tax=20_00000)
    g1 = _gstr(gstin=GSTIN_A, inv="ZQPWINFOUR", inv_norm="ZQPWINFOUR",
               total_tax=20_20000)   # 1% diff -- winner
    g2 = _gstr(gstin=GSTIN_A, inv="WKTMIDFOUR", inv_norm="WKTMIDFOUR",
               total_tax=20_60000)   # 3% diff
    g3 = _gstr(gstin=GSTIN_A, inv="VYRLOWFOUR", inv_norm="VYRLOWFOUR",
               total_tax=20_90000)   # 4.5% diff

    res = _run([g2, g3, g1], [p])   # deliberately not in quality order
    review = _review_by_gid(res)

    assert review[g1["id"]]["pr_id"] == p["id"], "1%-diff candidate must win"
    for loser in (g2, g3):
        row = review[loser["id"]]
        assert row["pr_id"] == "", f"{loser['id']} must not consume the PR"
        assert row["review_reason"] == "PR_CLAIMED_BY_BETTER_MATCH"
        assert g1["id"] in (row.get("note") or ""), (
            "Every loser's note must point at the actual winner, not another loser"
        )
    assert res["stats"]["sanity_passed"], res["stats"]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Non-contended credible candidates are completely unaffected: a single
#    GSTR row with no competitor for its PR must be assigned exactly as
#    before (this fix must be a no-op when there's nothing to contend).
# ─────────────────────────────────────────────────────────────────────────────
def test_uncontended_credible_candidate_unaffected():
    p = _pr(gstin=GSTIN_A, inv="PRBASEFIVE", inv_norm="PRBASEFIVE", total_tax=20_00000)
    g = _gstr(gstin=GSTIN_A, inv="ZQPSOLEFIVE", inv_norm="ZQPSOLEFIVE",
              total_tax=20_50000)   # 2.5% diff, sole candidate

    res = _run([g], [p])
    review = _review_by_gid(res)
    assert g["id"] in review
    assert review[g["id"]]["pr_id"] == p["id"]
    assert review[g["id"]]["review_reason"] != "PR_CLAIMED_BY_BETTER_MATCH"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Documentation test (NOT a claim this fix changes anything here):
#    the 5 REAL_THEFT pairs from verification_13_pairs.csv (pairs 1, 2, 6, 9,
#    11) reconstructed with their real field values. Their "thief" wins via a
#    clean PHASE 1 exact match (match_level=1, confidence=100) which runs
#    before CREDIBLE_CANDIDATE_FALLBACK (and before INVOICE_MATCH_AMOUNT_REVIEW
#    too), so the PR is already gone from every later phase's candidate pool
#    by the time it would consider the "victim". This fix does not, and should
#    not, alter that outcome -- see the module docstring for why silently
#    reassigning a 100%-confidence exact match to a fuzzy format-variant guess
#    would be a regression, not a fix.
# ─────────────────────────────────────────────────────────────────────────────
def test_real_theft_pairs_unchanged_by_this_fix():
    # (gstin, victim_inv, victim_norm, victim_tax_paise, victim_date,
    #  pr_inv, pr_norm, pr_tax_paise, pr_date,
    #  thief_inv, thief_norm, thief_tax_paise, thief_date)
    real_pairs = [
        ("06ZVWAT3988Z4ZR", "SI/3315/26", "SI331526", 54_15678, date(2026, 6, 21),
         "SI526", "SI526", 49_43497, date(2026, 6, 11),
         "SI/5/26", "SI526", 49_43497, date(2026, 6, 11)),
        ("09GRFDY5478G2ZG", "SI/3390/26", "SI339026", 52_61339, date(2026, 6, 8),
         "SI3326", "SI3326", 85_57962, date(2026, 6, 19),
         "SI/33/26", "SI3326", 85_57962, date(2026, 6, 19)),
        ("23AFQOF5808W7ZV", "INV/03424", "INV3424", 16_86227, date(2026, 6, 6),
         "INV3", "INV3", 13_38919, date(2026, 6, 10),
         "INV/00003", "INV3", 13_38919, date(2026, 6, 10)),
        ("07EYNBG8486R6Z2", "INV/03314", "INV3314", 87_79758, date(2026, 6, 16),
         "INV34", "INV34", 105_94588, date(2026, 6, 25),
         "INV/00034", "INV34", 105_94588, date(2026, 6, 25)),
        ("27SAYNS7630V6ZU", "INV-2026-3158", "INV20263158", 7_53052, date(2026, 6, 24),
         "INV2235", "INV2235", 10_55986, date(2026, 6, 9),
         "INV/02235", "INV2235", 10_55986, date(2026, 6, 9)),
    ]

    gstr_recs, pr_recs, victim_ids, thief_ids = [], [], [], []
    for (gstin, v_inv, v_norm, v_tax, v_date,
         pr_inv, pr_norm, pr_tax, pr_date,
         t_inv, t_norm, t_tax, t_date) in real_pairs:
        victim = _gstr(gstin=gstin, inv=v_inv, inv_norm=v_norm, total_tax=v_tax,
                        igst=v_tax, taxable=v_tax * 5, inv_date=v_date)
        thief = _gstr(gstin=gstin, inv=t_inv, inv_norm=t_norm, total_tax=t_tax,
                       igst=t_tax, taxable=t_tax * 5, inv_date=t_date)
        pr = _pr(gstin=gstin, inv=pr_inv, inv_norm=pr_norm, total_tax=pr_tax,
                  igst=pr_tax, taxable=pr_tax * 5, inv_date=pr_date)
        gstr_recs += [victim, thief]
        pr_recs.append(pr)
        victim_ids.append(victim["id"])
        thief_ids.append(thief["id"])

    res = _run(gstr_recs, pr_recs)
    matched = _matched_by_gid(res)
    missed = _missed_ids(res)

    for tid in thief_ids:
        assert tid in matched, "Thief must still win its PR as a clean Phase 1 match"
        # Thief vs PR invoice strings differ by formatting only → L2 Matched
        # (not L1 raw-identical). Still a clean Phase 1 win over the victim.
        assert matched[tid]["match_level"] == 2
        assert matched[tid].get("review_reason") is None
        assert matched[tid].get("match_status") == "matched"

    for vid in victim_ids:
        assert vid in missed, (
            "Victim must remain Missed ITC -- this fix only resolves contention "
            "for candidates still unconsumed when CREDIBLE_CANDIDATE_FALLBACK runs, "
            "and this PR is already consumed by the thief before that phase starts."
        )
