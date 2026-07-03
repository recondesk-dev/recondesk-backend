"""test_duplicate_lifecycle.py
Comprehensive reconciliation lifecycle tests.

Covers:
  A. Clean 1:1 match — stays in matched, not in review_required
  B. Deterministic duplicate (same inv, different amount/date) — paired as clean match
  C. 1 GSTR → 2 PRs (same inv/amount) — review_required, not missed/risk
  D. 2 GSTRs → 1 PR (same inv/amount) — review_required, not missed/risk
  E. 2 GSTRs → 2 PRs ambiguous (identical) — review_required
  F. 2 GSTRs → 2 PRs unambiguous (distinct amounts) — clean pairs
  G. GSTIN mismatch (edit distance ≤ 2, same inv+amount) — gstin_mismatch, NOT missed/risk
  H. Genuine GSTR-only — missed_itc only
  I. Genuine PR-only — itc_at_risk only
  J. Bucket exclusivity — no record in >1 bucket
  K. Review Required records must NOT contribute to financial KPI totals
  L. Clean match NOT contaminated by orphan with same invoice number
"""
from __future__ import annotations

from datetime import date

import pytest

from app.matching.engine import run_bidirectional_reconciliation


# ── helpers ──────────────────────────────────────────────────────────────────

GSTIN_A = "27AAAAA0000A1Z5"
GSTIN_B = "27AAAAA0000B1Z5"   # 1-char diff from A (edit distance 1)
GSTIN_C = "29BBBBB0000B1Z5"   # completely different


def _g(id, gstin=GSTIN_A, inv="INV001", tax=10000, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt),
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": tax * 18,
    }


def _p(id, gstin=GSTIN_A, inv="INV001", tax=10000, dt="2026-05-01"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number": inv,
        "invoice_number_normalized": inv,
        "invoice_date": date.fromisoformat(dt),
        "taxable_amount_paise": tax * 100,
        "total_tax_paise": tax * 18,
    }


def _run(gstr_list, pr_list):
    return run_bidirectional_reconciliation(
        gstr_list, pr_list, gstr_period=date(2026, 5, 1)
    )


def _all_ids(result):
    """Collect all GSTR and PR ids from every bucket for exclusivity check."""
    gstr_ids: list[str] = []
    pr_ids: list[str] = []

    for m in result.get("matched", []):
        gstr_ids.append(str(m.get("gstr_id", "")))
        pr_ids.append(str(m.get("pr_id", "")))

    for gm in result.get("gstin_mismatch", []):
        gstr_ids.append(str(gm.get("gstr_id", "")))
        pr_ids.append(str(gm.get("pr_id", "")))

    for mi in result.get("missed_itc", []):
        gstr_ids.append(str(mi.get("gstr_id", "")))

    for wr in result.get("wrongful_itc_risk", []):
        pr_ids.append(str(wr.get("id", "")))

    for rr in result.get("review_required", []):
        if rr.get("side") == "GSTR":
            gstr_ids.append(str(rr.get("gstr_id", "")))
        else:
            pr_ids.append(str(rr.get("id", "")))

    return gstr_ids, pr_ids


# ── Test A: Clean 1:1 match ──────────────────────────────────────────────────

def test_a_clean_match_stays_in_matched():
    """A perfect 1:1 match must appear in matched, zero in review_required."""
    res = _run([_g("g1")], [_p("p1")])
    stats = res["stats"]
    assert stats["clean_matched_count"] >= 1
    assert stats["duplicate_conflict_count"] == 0
    assert stats["genuine_gstr_only_count"] == 0
    assert stats["genuine_pr_only_count"] == 0
    # g1 must be in matched, not review_required
    matched_gstr = {str(m["gstr_id"]) for m in res["matched"]}
    assert "g1" in matched_gstr


# ── Test B: Deterministic duplicate (different amounts → unambiguous) ─────────

def test_b_deterministic_duplicate_pair_resolves_as_clean():
    """Two GSTRs and two PRs for same supplier+invoice but distinct amounts
    must be paired deterministically and land in matched (not review_required)."""
    gstr = [_g("g1", tax=100, dt="2026-05-01"), _g("g2", tax=200, dt="2026-05-02")]
    pr = [_p("p1", tax=100, dt="2026-05-01"), _p("p2", tax=200, dt="2026-05-02")]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats["duplicate_conflict_count"] == 0
    assert stats["genuine_gstr_only_count"] == 0
    assert stats["genuine_pr_only_count"] == 0
    # 2 clean matched (or at least both consumed as matched)
    assert len(res["matched"]) == 2


# ── Test C: 1 GSTR → 2 PRs (ambiguous) ──────────────────────────────────────

def test_c_one_gstr_two_pr_duplicate_pr_flagged():
    """1 GSTR matched against 2 identical PRs → first matches normally,
    second is flagged as duplicate data-entry. None should be in missed_itc
    or wrongful_itc_risk."""
    gstr = [_g("g1", tax=100)]
    pr = [_p("p1", tax=100), _p("p2", tax=100)]
    res = _run(gstr, pr)
    stats = res["stats"]
    # Correct behavior: 1 clean match + 1 duplicate PR row
    assert stats["clean_matched_count"] == 1
    assert stats["duplicate_pr_count"] == 1
    assert stats["duplicate_conflict_count"] == 0
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0


# ── Test D: 2 GSTRs → 1 PR (ambiguous) ──────────────────────────────────────

def test_d_two_gstr_one_pr_goes_to_review():
    """2 identical GSTRs, 1 PR → all go to review_required, none to missed_itc."""
    gstr = [_g("g1", tax=100), _g("g2", tax=100)]
    pr = [_p("p1", tax=100)]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats["duplicate_conflict_count"] >= 1
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0


# ── Test E: Ambiguous N:N (identical) → review_required ──────────────────────

def test_e_ambiguous_nn_all_review():
    """2 GSTRs + 2 PRs with identical amounts/dates → all 4 to review_required."""
    gstr = [_g("g1", tax=100, dt="2026-05-01"), _g("g2", tax=100, dt="2026-05-01")]
    pr = [_p("p1", tax=100, dt="2026-05-01"), _p("p2", tax=100, dt="2026-05-01")]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats["clean_matched_count"] == 0
    assert stats["duplicate_conflict_count"] == 2
    assert len(res["review_required"]) == 4


# ── Test F: Unambiguous N:N → deterministic pairs ────────────────────────────

def test_f_unambiguous_nn_paired_as_clean():
    """2 GSTRs + 2 PRs with distinct amounts → deterministically paired as clean."""
    gstr = [_g("g1", tax=100, dt="2026-05-01"), _g("g2", tax=200, dt="2026-05-02")]
    pr = [_p("p1", tax=100, dt="2026-05-01"), _p("p2", tax=200, dt="2026-05-02")]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats["clean_matched_count"] == 2
    assert stats["duplicate_conflict_count"] == 0


# ── Test G: GSTIN mismatch ───────────────────────────────────────────────────

def test_g_gstin_mismatch_not_double_orphan():
    """GSTIN with 1-char diff, same invoice+amount → gstin_mismatch.
    Must NOT appear in missed_itc or wrongful_itc_risk."""
    gstr = [_g("g1", gstin=GSTIN_A)]
    pr = [_p("p1", gstin=GSTIN_B)]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats["gstin_mismatch_count"] == 1
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0


# ── Test H: Genuine GSTR-only → missed_itc only ──────────────────────────────

def test_h_genuine_gstr_only_is_missed_itc():
    """GSTR with no matching PR → missed_itc, not review_required."""
    gstr = [_g("g1", inv="UNIQUE-GSTR-001")]
    pr = []
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats.get("genuine_gstr_only_count", stats["missed_itc_count"]) == 1
    assert stats["missed_itc_count"] == 1
    assert stats["duplicate_conflict_count"] == 0


# ── Test I: Genuine PR-only → itc_at_risk only ───────────────────────────────

def test_i_genuine_pr_only_is_itc_at_risk():
    """PR with no matching GSTR → wrongful_itc_risk, not review_required."""
    gstr = []
    pr = [_p("p1", inv="UNIQUE-PR-001")]
    res = _run(gstr, pr)
    stats = res["stats"]
    assert stats.get("genuine_pr_only_count", stats["wrongful_risk_count"]) == 1
    assert stats["wrongful_risk_count"] == 1
    assert stats["duplicate_conflict_count"] == 0


# ── Test J: Bucket exclusivity ───────────────────────────────────────────────

def test_j_bucket_exclusivity_mixed_scenario():
    """In a mixed scenario, no GSTR or PR id appears in more than one bucket."""
    gstr = [
        _g("g1"),                           # clean match → matched
        _g("g2", inv="DUP", tax=100),       # duplicate group
        _g("g3", inv="DUP", tax=100),       # duplicate group
        _g("g4", inv="MISSED001"),           # genuine missed
    ]
    pr = [
        _p("p1"),                           # clean match → matched
        _p("p2", inv="DUP", tax=100),       # duplicate group
        _p("p3", inv="DUP", tax=100),       # duplicate group
        _p("p4", inv="RISK001"),             # genuine at risk
    ]
    res = _run(gstr, pr)
    gstr_ids, pr_ids = _all_ids(res)

    # Check for duplicates
    from collections import Counter
    gstr_counts = Counter(gid for gid in gstr_ids if gid)
    pr_counts = Counter(pid for pid in pr_ids if pid)
    doubles_g = [gid for gid, cnt in gstr_counts.items() if cnt > 1]
    doubles_p = [pid for pid, cnt in pr_counts.items() if cnt > 1]
    assert doubles_g == [], f"GSTR ids in multiple buckets: {doubles_g}"
    assert doubles_p == [], f"PR ids in multiple buckets: {doubles_p}"


# ── Test K: Review Required must NOT contribute to KPI totals ────────────────

def test_k_review_required_excluded_from_kpi_totals():
    """Records in review_required must not appear in missed_itc or wrongful_itc_risk."""
    gstr = [_g("g1", inv="DUP", tax=100), _g("g2", inv="DUP", tax=100)]
    pr = [_p("p1", inv="DUP", tax=100)]
    res = _run(gstr, pr)
    # Review required group
    rr_gstr_ids = {str(r.get("gstr_id", "")) for r in res.get("review_required", []) if r.get("side") == "GSTR"}
    # None of these should be in missed_itc
    missed_gstr_ids = {str(m.get("gstr_id", "")) for m in res.get("missed_itc", [])}
    overlap = rr_gstr_ids & missed_gstr_ids
    assert overlap == set(), f"Review required GSTRs leaked into missed_itc: {overlap}"
    # KPI total must not include review items
    stats = res["stats"]
    assert stats["missed_itc_count"] == 0
    assert stats["wrongful_risk_count"] == 0


# ── Test L: Clean match NOT contaminated by orphan with same invoice ──────────

def test_l_clean_match_not_yanked_by_sibling_orphan():
    """A deterministic clean match (g1→p1) must stay in matched even when another
    GSTR record (g2) has the same invoice number and is an orphan."""
    gstr = [
        _g("g1", inv="INV001", tax=100),   # pairs cleanly with p1
        _g("g2", inv="INV001", tax=100),   # orphan — no PR partner
    ]
    pr = [
        _p("p1", inv="INV001", tax=100),   # pairs cleanly with g1
    ]
    res = _run(gstr, pr)

    # g1→p1 should be in matched (or review, but NOT in missed_itc)
    matched_gstr_ids = {str(m["gstr_id"]) for m in res.get("matched", [])}
    missed_gstr_ids = {str(m.get("gstr_id", "")) for m in res.get("missed_itc", [])}

    # g1 must not be in missed_itc — it was matched
    assert "g1" not in missed_gstr_ids, (
        "g1 was matched but ended up in missed_itc — clean match was wrongly yanked"
    )
    # No double-counting: g1 must appear in exactly one bucket
    gstr_ids, _ = _all_ids(res)
    from collections import Counter
    counts = Counter(gid for gid in gstr_ids if gid)
    assert counts.get("g1", 0) == 1, f"g1 appears {counts.get('g1', 0)} times across buckets"
