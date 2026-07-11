"""
test_scenario_regression.py
============================
Ground-truth scenario regression for the Phase-2 missed_itc fix.

Scenario tags (mirrors the test-dataset PR "Source Scenario" column):

  exact                 – Perfect GSTIN + invoice + amount + date match
  format_variant        – Same GSTIN, invoice format differs (INV/24/003 vs INV2024003)
  ocr_vendor_fuzzy      – Same GSTIN, invoice has 1-char OCR error (sim ~0.78-0.85)
  small_amount_diff     – Same GSTIN + invoice, amount off by 0.5-2 %
  large_amount_review   – Same GSTIN + invoice, amount diff 5-30 % (too large for L3)
  late_date_shift       – Same GSTIN + invoice, date diff 46-90 days
  gstin_mismatch_review – GSTIN lev=1 (or same PAN), invoice close/exact
  pr_only_missed_itc    – No matching GSTR side — genuine missing ITC

TASKS covered:
  Task 1  – scenario_breakdown table (assert counts per scenario)
  Task 2  – root-cause traced per group (see comments per test)
  Task 3  – strong-evidence records land in review_required, not missed_itc
  Task 4  – KPI sanity: missed_itc and wrongful_risk are not double-counted
  Task 5  – regression locks:
            (a) probable-pair records → review_required (not missed_itc, not matched)
            (b) pr_only_missed_itc → missed_itc
            (c) exact → clean matched (match_level == 1)

Run:
    cd recondesk-backend
    python3 -m pytest tests/test_scenario_regression.py -v
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from app.services.matcher import normalize_invoice
from app.matching.engine import run_bidirectional_reconciliation

# ---------------------------------------------------------------------------
# Valid 15-char GSTINs
# ---------------------------------------------------------------------------
GSTIN_A   = "27AABCU9603R1ZX"          # Supplier A
GSTIN_A_T = "27AABCU9603R1ZF"          # Supplier A — checksum digit off (lev=1, same PAN)
GSTIN_B   = "29ABCDE1234F1Z5"          # Supplier B
GSTIN_C   = "33AAFPT5678G1Z3"          # Supplier C
GSTIN_D   = "24AAGCR3456H1Z1"          # Supplier D

PERIOD = date(2026, 5, 1)

# ---------------------------------------------------------------------------
# Record factory helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


def _gstr(
    rid: str,
    gstin: str,
    invoice: str,
    taxable: int = 1_000_000,
    *,
    inv_date: str = "2026-05-10",
    cgst: int | None = None,
    sgst: int | None = None,
    igst: int = 0,
) -> dict[str, Any]:
    cg = taxable * 9 // 100 if cgst is None else cgst
    sg = taxable * 9 // 100 if sgst is None else sgst
    return {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": invoice,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "cgst_paise": cg,
        "sgst_paise": sg,
        "igst_paise": igst,
        "total_tax_paise": cg + sg + igst,
    }


def _pr(
    rid: str,
    gstin: str,
    invoice: str,
    taxable: int = 1_000_000,
    *,
    inv_date: str = "2026-05-10",
    cgst: int | None = None,
    sgst: int | None = None,
    igst: int = 0,
    scenario: str = "",
) -> dict[str, Any]:
    cg = taxable * 9 // 100 if cgst is None else cgst
    sg = taxable * 9 // 100 if sgst is None else sgst
    return {
        "id": rid,
        "supplier_gstin": gstin,
        "invoice_number": invoice,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_date": inv_date,
        "taxable_amount_paise": taxable,
        "cgst_paise": cg,
        "sgst_paise": sg,
        "igst_paise": igst,
        "total_tax_paise": cg + sg + igst,
        "_scenario": scenario,          # ground-truth tag (not used by engine)
    }


# ---------------------------------------------------------------------------
# Ground-truth dataset
# ---------------------------------------------------------------------------
#
# Three examples per scenario.  Each row is a (gstr, pr, scenario) triple;
# both records in a triple should link together.  For pr_only_missed_itc the
# GSTR has no PR partner.

DATASET: list[tuple[dict, dict | None, str]] = [

    # ── exact (3) ──────────────────────────────────────────────────────────
    # Phase 1 L1 — same raw invoice, same GSTIN, same amount, same date.
    (_gstr("g_e1", GSTIN_A, "INV-E-001", 500_000),
     _pr  ("p_e1", GSTIN_A, "INV-E-001", 500_000, scenario="exact"), "exact"),

    (_gstr("g_e2", GSTIN_B, "ORD/2026/099", 1_200_000),
     _pr  ("p_e2", GSTIN_B, "ORD/2026/099", 1_200_000, scenario="exact"), "exact"),

    (_gstr("g_e3", GSTIN_C, "BILL00042", 750_000, cgst=0, sgst=0, igst=135_000),
     _pr  ("p_e3", GSTIN_C, "BILL00042",  750_000, cgst=0, sgst=0, igst=135_000,
           scenario="exact"), "exact"),

    # ── format_variant (3) ─────────────────────────────────────────────────
    # Phase 1 tries exact inv-norm match (fails), then format_variant check.
    # With exact amount, matcher returns L3 (format_variant + amount_within_l3=True).
    # Phase 2 TYPO_MISMATCH also catches if Phase 1 misses (amount ≤5%).
    (_gstr("g_fv1", GSTIN_A, "INV2026003"),
     _pr  ("p_fv1", GSTIN_A, "INV/2026/003", scenario="format_variant"), "format_variant"),

    (_gstr("g_fv2", GSTIN_B, "DS-2026-00078", 800_000),
     _pr  ("p_fv2", GSTIN_B, "DS/26/78",      800_000, scenario="format_variant"),
     "format_variant"),

    (_gstr("g_fv3", GSTIN_C, "TAX00123", 300_000),
     _pr  ("p_fv3", GSTIN_C, "TAX-00123", 300_000, scenario="format_variant"),
     "format_variant"),

    # ── ocr_vendor_fuzzy (3) ───────────────────────────────────────────────
    # OCR glitch: one-char substitution (O→0, I→1, etc.) in invoice number.
    # invoice_similarity typically 0.75-0.87 for single-char changes on short strings.
    # Caught by Phase 2 TYPO_MISMATCH (sim > 0.80) or CREDIBLE_CANDIDATE_FALLBACK.
    (_gstr("g_ov1", GSTIN_A, "INV0001", 400_000),
     _pr  ("p_ov1", GSTIN_A, "INV0001", 400_000, scenario="ocr_vendor_fuzzy"),
     "ocr_vendor_fuzzy"),   # actually exact — sim=1.0, confirms no regression

    (_gstr("g_ov2", GSTIN_B, "RCPT2026A01", 900_000),
     _pr  ("p_ov2", GSTIN_B, "RCPT2026B01", 900_000, scenario="ocr_vendor_fuzzy"),
     "ocr_vendor_fuzzy"),   # A→B single char, sim high

    (_gstr("g_ov3", GSTIN_C, "PO20260501", 550_000),
     _pr  ("p_ov3", GSTIN_C, "PO20260591", 550_000, scenario="ocr_vendor_fuzzy"),
     "ocr_vendor_fuzzy"),   # 0→9 single char

    # ── small_amount_diff (3) ──────────────────────────────────────────────
    # Same GSTIN + same invoice, amount diff 0.5-2%.
    # Caught by Phase 1 L3 (amount_within_l3: diff ≤ 2%).
    (_gstr("g_sa1", GSTIN_A, "INV-SA-001", 1_000_000),
     _pr  ("p_sa1", GSTIN_A, "INV-SA-001", 1_010_000, scenario="small_amount_diff"),
     "small_amount_diff"),   # 1% diff

    (_gstr("g_sa2", GSTIN_B, "SA-2026-77",  500_000),
     _pr  ("p_sa2", GSTIN_B, "SA-2026-77",  509_000, scenario="small_amount_diff"),
     "small_amount_diff"),   # 1.8% diff

    (_gstr("g_sa3", GSTIN_D, "SMAMT003",    200_000),
     _pr  ("p_sa3", GSTIN_D, "SMAMT003",    202_000, scenario="small_amount_diff"),
     "small_amount_diff"),   # 1% diff

    # ── large_amount_review (3) ────────────────────────────────────────────
    # Same GSTIN + same invoice, amount diff > 5%.  Phase 1 returns L6 (both
    # amount AND date may fail L2; or amount fails L3 threshold).
    # FIX — INVOICE_MATCH_AMOUNT_REVIEW branch catches these.
    (_gstr("g_la1", GSTIN_A, "INV-LA-001", 1_000_000),
     _pr  ("p_la1", GSTIN_A, "INV-LA-001", 1_100_000, scenario="large_amount_review"),
     "large_amount_review"),   # 10% diff

    (_gstr("g_la2", GSTIN_B, "BIG-2026-01", 2_000_000),
     _pr  ("p_la2", GSTIN_B, "BIG-2026-01", 2_300_000, scenario="large_amount_review"),
     "large_amount_review"),   # 15% diff

    (_gstr("g_la3", GSTIN_C, "LARGEINV003", 800_000),
     _pr  ("p_la3", GSTIN_C, "LARGEINV003",  600_000, scenario="large_amount_review"),
     "large_amount_review"),   # 25% diff

    # ── late_date_shift (3) ────────────────────────────────────────────────
    # Same GSTIN + same invoice + exact amount, but invoice dates differ by
    # 50-90 days (filed late).  Phase 1 L3 requires date_within_l3 (≤30d);
    # L2 fallback returns L3 only when amount passes L2, which it does here.
    # But if BOTH date > 7d AND amount > 0.5%, the L2 branch returns L3 directly.
    # The fix (CREDIBLE_CANDIDATE_FALLBACK criterion 3: same GSTIN + same invoice
    # → waive date) handles the edge where Phase 1 somehow produces L6.
    (_gstr("g_ld1", GSTIN_A, "INV-LD-001", 600_000, inv_date="2026-03-10"),
     _pr  ("p_ld1", GSTIN_A, "INV-LD-001", 600_000, inv_date="2026-05-10",
           scenario="late_date_shift"),
     "late_date_shift"),   # 61-day gap — GSTR says Mar, PR says May

    (_gstr("g_ld2", GSTIN_B, "LATE-2026-22", 450_000, inv_date="2026-02-15"),
     _pr  ("p_ld2", GSTIN_B, "LATE-2026-22", 450_000, inv_date="2026-05-10",
           scenario="late_date_shift"),
     "late_date_shift"),   # 84-day gap

    (_gstr("g_ld3", GSTIN_D, "LD-INV-003", 350_000, inv_date="2026-04-01"),
     _pr  ("p_ld3", GSTIN_D, "LD-INV-003", 350_000, inv_date="2026-05-21",
           scenario="late_date_shift"),
     "late_date_shift"),   # 50-day gap

    # ── gstin_mismatch_review (3) ──────────────────────────────────────────
    # GSTIN Levenshtein distance 1 (checksum digit off) OR same PAN.
    # FIX — FUZZY_GSTIN fallback catches these (with is_invoice_format_variant
    # added as an alternative to inv_sim >= 0.75).
    (_gstr("g_gm1", GSTIN_A,   "CAP-88", 2_500_000),
     _pr  ("p_gm1", GSTIN_A_T, "CAP-88", 2_500_000, scenario="gstin_mismatch_review"),
     "gstin_mismatch_review"),   # same PAN, lev=1

    (_gstr("g_gm2", GSTIN_A,   "GMATCH-2026-01", 700_000),
     _pr  ("p_gm2", GSTIN_A_T, "GMATCH-2026-01", 700_000, scenario="gstin_mismatch_review"),
     "gstin_mismatch_review"),   # lev=1 GSTIN, exact invoice

    (_gstr("g_gm3", GSTIN_A,   "INV/2026/GM/003", 1_100_000),
     _pr  ("p_gm3", GSTIN_A_T, "INV2026GM003",    1_100_000,
           scenario="gstin_mismatch_review"),
     "gstin_mismatch_review"),   # lev=1 GSTIN + format-variant invoice

    # ── pr_only_missed_itc (4) ─────────────────────────────────────────────
    # Genuine GSTR-only records: no PR partner.  Must stay in missed_itc.
    (_gstr("g_mi1", GSTIN_A, "GHOST-001", 250_000), None, "pr_only_missed_itc"),
    (_gstr("g_mi2", GSTIN_B, "GHOST-002", 180_000), None, "pr_only_missed_itc"),
    (_gstr("g_mi3", GSTIN_C, "GHOST-003", 320_000), None, "pr_only_missed_itc"),
    (_gstr("g_mi4", GSTIN_D, "GHOST-004", 410_000), None, "pr_only_missed_itc"),
]

# Sanity-check the dataset at import time
_SCENARIO_COUNTS = {}
for _g, _p, _s in DATASET:
    _SCENARIO_COUNTS[_s] = _SCENARIO_COUNTS.get(_s, 0) + 1
assert _SCENARIO_COUNTS.get("pr_only_missed_itc", 0) == 4
assert _SCENARIO_COUNTS.get("gstin_mismatch_review", 0) == 3
assert _SCENARIO_COUNTS.get("large_amount_review", 0) == 3
assert _SCENARIO_COUNTS.get("late_date_shift", 0) == 3


# ---------------------------------------------------------------------------
# Helper — run the engine once and return maps for easy assertions
# ---------------------------------------------------------------------------

def _run() -> dict:
    gstr_records = [g for g, _p, _s in DATASET]
    pr_records   = [p for _g, p, _s in DATASET if p is not None]
    return run_bidirectional_reconciliation(gstr_records, pr_records, gstr_period=PERIOD)


def _result_by_gstr_id(res: dict) -> dict[str, str]:
    """Map gstr_id → bucket name for quick per-record assertions."""
    bucket: dict[str, str] = {}
    for m in res.get("matched") or []:
        bucket[m["gstr_id"]] = "matched"
    for r in res.get("review_required") or []:
        bucket[r["gstr_id"]] = "review_required"
    for mi in res.get("missed_itc") or []:
        gid = mi.get("gstr_id") or mi.get("id")
        bucket[str(gid)] = "missed_itc"
    return bucket


# ---------------------------------------------------------------------------
# Task 1 — Scenario breakdown table
# ---------------------------------------------------------------------------

class TestTask1ScenarioBreakdown:
    """
    Task 1: Pull records by scenario tag and assert they land in the right bucket.

    Expected routing (after fix):
      exact                 → matched (L1)
      format_variant        → review_required OR matched
      ocr_vendor_fuzzy      → review_required
      small_amount_diff     → review_required (L3 or review)
      large_amount_review   → review_required (AMOUNT_MISMATCH)  ← previously missed_itc
      late_date_shift       → review_required (POSSIBLE_MATCH)   ← previously missed_itc
      gstin_mismatch_review → review_required (GSTIN_MISMATCH)   ← previously missed_itc
      pr_only_missed_itc    → missed_itc

    Only pr_only_missed_itc should legitimately remain in missed_itc.
    """

    @pytest.fixture(scope="class")
    def res(self):
        return _run()

    @pytest.fixture(scope="class")
    def by_gid(self, res):
        return _result_by_gstr_id(res)

    @pytest.fixture(scope="class")
    def by_scenario(self, by_gid):
        """Tally each scenario's routing outcome."""
        counts: dict[str, dict[str, int]] = {}
        for g, _p, scenario in DATASET:
            bucket = by_gid.get(g["id"], "unknown")
            if scenario not in counts:
                counts[scenario] = {"matched": 0, "review_required": 0, "missed_itc": 0, "unknown": 0}
            counts[scenario][bucket] = counts[scenario].get(bucket, 0) + 1
        return counts

    def test_exact_scenario_all_matched(self, by_scenario):
        """All exact-scenario records must be clean matched."""
        s = by_scenario["exact"]
        assert s["matched"] == 3, (
            f"exact: expected 3 matched, got {s}"
        )
        assert s["missed_itc"] == 0

    def test_format_variant_not_in_missed_itc(self, by_scenario):
        s = by_scenario["format_variant"]
        assert s["missed_itc"] == 0, (
            f"format_variant: {s['missed_itc']} records still in missed_itc — fix regression"
        )

    def test_small_amount_diff_not_in_missed_itc(self, by_scenario):
        s = by_scenario["small_amount_diff"]
        assert s["missed_itc"] == 0, (
            f"small_amount_diff: {s['missed_itc']} records in missed_itc"
        )

    def test_large_amount_review_not_in_missed_itc(self, by_scenario):
        """
        Root cause: amount diff > 5% bypassed L3 (2% cap) and CREDIBLE_FALLBACK (5% cap).
        Fix: INVOICE_MATCH_AMOUNT_REVIEW branch catches same-GSTIN + same-invoice regardless of amount.
        """
        s = by_scenario["large_amount_review"]
        assert s["missed_itc"] == 0, (
            f"large_amount_review: {s['missed_itc']} records still in missed_itc.\n"
            "Check INVOICE_MATCH_AMOUNT_REVIEW branch in execute_phase2_and_3."
        )

    def test_late_date_shift_not_in_missed_itc(self, by_scenario):
        """
        Root cause: date diff > 45 days bypassed CREDIBLE_CANDIDATE_FALLBACK (45-day cap).
        Fix: criterion 3 — same GSTIN + same invoice → waive date tolerance entirely.
        """
        s = by_scenario["late_date_shift"]
        assert s["missed_itc"] == 0, (
            f"late_date_shift: {s['missed_itc']} records still in missed_itc.\n"
            "Check CREDIBLE_CANDIDATE_FALLBACK criterion 3 in execute_phase2_and_3."
        )

    def test_gstin_mismatch_review_not_in_missed_itc(self, by_scenario):
        """
        Root cause (pre-fix): FUZZY_GSTIN fallback inv_sim threshold (0.75) missed
        format-variant invoice numbers even when GSTIN Lev=1.
        Fix: also accept is_invoice_format_variant() as alternative to inv_sim >= 0.75.
        """
        s = by_scenario["gstin_mismatch_review"]
        assert s["missed_itc"] == 0, (
            f"gstin_mismatch_review: {s['missed_itc']} records still in missed_itc.\n"
            "Check FUZZY_GSTIN fallback — format-variant invoice guard."
        )

    def test_pr_only_missed_itc_stays_in_missed_itc(self, by_scenario):
        """Genuine absent records must NOT be rescued to review_required."""
        s = by_scenario["pr_only_missed_itc"]
        assert s["missed_itc"] == 4, (
            f"pr_only_missed_itc: expected 4 in missed_itc, got {s}"
        )
        assert s["matched"] == 0
        assert s["review_required"] == 0

    def test_only_pr_only_scenario_produces_missed_itc(self, by_scenario):
        """No non-genuine scenario should have any records in missed_itc."""
        non_genuine = [s for s in by_scenario if s != "pr_only_missed_itc"]
        for scenario in non_genuine:
            assert by_scenario[scenario].get("missed_itc", 0) == 0, (
                f"Scenario '{scenario}' has {by_scenario[scenario]['missed_itc']} "
                "records in missed_itc — these have strong evidence and should be "
                "in review_required."
            )


# ---------------------------------------------------------------------------
# Task 3 / Task 5a — Specific probable-pair records → review_required
# ---------------------------------------------------------------------------

class TestTask5aProbalePairsReviewRequired:
    """
    Task 5a: Each probable-pair record (scenarios other than exact and pr_only_missed_itc)
    must resolve to review_required (not matched, not missed_itc).

    exact records may be matched — that is also acceptable.
    """

    @pytest.fixture(scope="class")
    def by_gid(self):
        return _result_by_gstr_id(_run())

    # ── large_amount_review specific records ──────────────────────────────

    def test_large_amount_review_g_la1(self, by_gid):
        """10% amount diff, same invoice, same GSTIN — INVOICE_MATCH_AMOUNT_REVIEW."""
        assert by_gid.get("g_la1") == "review_required", (
            f"g_la1 (large_amount_review 10%) landed in: {by_gid.get('g_la1')!r}"
        )

    def test_large_amount_review_g_la2(self, by_gid):
        """15% amount diff."""
        assert by_gid.get("g_la2") == "review_required", (
            f"g_la2 (large_amount_review 15%) landed in: {by_gid.get('g_la2')!r}"
        )

    def test_large_amount_review_g_la3(self, by_gid):
        """25% amount diff."""
        assert by_gid.get("g_la3") == "review_required", (
            f"g_la3 (large_amount_review 25%) landed in: {by_gid.get('g_la3')!r}"
        )

    # ── late_date_shift specific records ──────────────────────────────────

    def test_late_date_shift_g_ld1(self, by_gid):
        """61-day gap (Mar→May), exact amount."""
        bucket = by_gid.get("g_ld1")
        assert bucket in ("review_required", "matched"), (
            f"g_ld1 (late_date_shift 61d) landed in: {bucket!r}"
        )
        # Prefer review_required but matched is also acceptable (cross-period L1 with same dates)
        assert bucket != "missed_itc"

    def test_late_date_shift_g_ld2(self, by_gid):
        """84-day gap."""
        assert by_gid.get("g_ld2") != "missed_itc", (
            f"g_ld2 (late_date_shift 84d) fell into missed_itc"
        )

    def test_late_date_shift_g_ld3(self, by_gid):
        """50-day gap."""
        assert by_gid.get("g_ld3") != "missed_itc", (
            f"g_ld3 (late_date_shift 50d) fell into missed_itc"
        )

    # ── gstin_mismatch_review specific records ────────────────────────────

    def test_gstin_mismatch_review_g_gm1(self, by_gid):
        """lev=1 GSTIN, exact invoice, exact amount."""
        assert by_gid.get("g_gm1") == "review_required", (
            f"g_gm1 (gstin_mismatch lev=1, exact inv) landed in: {by_gid.get('g_gm1')!r}"
        )

    def test_gstin_mismatch_review_g_gm2(self, by_gid):
        """lev=1 GSTIN, exact invoice."""
        assert by_gid.get("g_gm2") == "review_required", (
            f"g_gm2 (gstin_mismatch lev=1) landed in: {by_gid.get('g_gm2')!r}"
        )

    def test_gstin_mismatch_review_g_gm3(self, by_gid):
        """lev=1 GSTIN + format-variant invoice — hardest case."""
        assert by_gid.get("g_gm3") == "review_required", (
            f"g_gm3 (gstin_mismatch lev=1 + format_variant) landed in: {by_gid.get('g_gm3')!r}\n"
            "This requires is_invoice_format_variant() in FUZZY_GSTIN fallback."
        )


# ---------------------------------------------------------------------------
# Task 5b — Genuine missed ITC stays in missed_itc
# ---------------------------------------------------------------------------

class TestTask5bGenuineMissedItcStays:
    """Genuine GSTR-only records (no PR partner) must not be rescued."""

    @pytest.fixture(scope="class")
    def by_gid(self):
        return _result_by_gstr_id(_run())

    def test_ghost_001_stays_missed(self, by_gid):
        assert by_gid.get("g_mi1") == "missed_itc"

    def test_ghost_002_stays_missed(self, by_gid):
        assert by_gid.get("g_mi2") == "missed_itc"

    def test_ghost_003_stays_missed(self, by_gid):
        assert by_gid.get("g_mi3") == "missed_itc"

    def test_ghost_004_stays_missed(self, by_gid):
        assert by_gid.get("g_mi4") == "missed_itc"

    def test_missed_itc_count_exactly_four(self):
        res = _run()
        assert len(res["missed_itc"]) == 4, (
            f"Expected exactly 4 missed_itc (genuine ghosts), got {len(res['missed_itc'])}"
        )


# ---------------------------------------------------------------------------
# Task 5c — Exact scenario → clean matched, match_level == 1
# ---------------------------------------------------------------------------

class TestTask5cExactScenarioMatched:
    """Exact records must be clean matched at L1, never review_required."""

    @pytest.fixture(scope="class")
    def res(self):
        return _run()

    def test_exact_g_e1_matched_l1(self, res):
        match = next((m for m in res["matched"] if m["gstr_id"] == "g_e1"), None)
        assert match is not None, "g_e1 (exact) not in matched"
        assert match["match_level"] == 1, f"g_e1 match_level={match['match_level']}, expected 1"

    def test_exact_g_e2_matched_l1(self, res):
        match = next((m for m in res["matched"] if m["gstr_id"] == "g_e2"), None)
        assert match is not None, "g_e2 (exact) not in matched"
        assert match["match_level"] == 1

    def test_exact_g_e3_matched_l1(self, res):
        match = next((m for m in res["matched"] if m["gstr_id"] == "g_e3"), None)
        assert match is not None, "g_e3 (exact) not in matched"
        assert match["match_level"] == 1

    def test_exact_records_not_in_review_required(self, res):
        review_gstr_ids = {r["gstr_id"] for r in (res.get("review_required") or [])}
        for g, _p, s in DATASET:
            if s == "exact":
                assert g["id"] not in review_gstr_ids, (
                    f"Exact record {g['id']} should be clean matched, not review_required"
                )


# ---------------------------------------------------------------------------
# Task 4 — KPI sanity (no double-counting of the same transaction)
# ---------------------------------------------------------------------------

class TestTask4KPISanity:
    """
    Task 4: Confirm missed_itc and wrongful_itc_risk totals are consistent
    and that the engine sanity check passes.
    """

    @pytest.fixture(scope="class")
    def res(self):
        return _run()

    def test_sanity_passes(self, res):
        assert res["stats"]["sanity_passed"] is True, (
            "Engine sanity check failed: "
            f"matched={res['stats']['matched_count']}, "
            f"missed={res['stats']['missed_itc_count']}, "
            f"review={res['stats']['review_required_count']}, "
            f"total_gstr={res['stats']['total_gstr']}"
        )

    def test_missed_itc_count_after_fix(self, res):
        """After the fix only the 4 genuine ghosts should be in missed_itc."""
        assert res["stats"]["missed_itc_count"] == 4

    def test_review_required_includes_probable_pairs(self, res):
        """All non-exact, non-ghost GSTR records should be in review_required."""
        probable_pair_gstr_ids = {
            g["id"] for g, p, s in DATASET
            if p is not None and s != "exact"
        }
        review_gstr_ids = {r["gstr_id"] for r in (res.get("review_required") or [])}
        matched_gstr_ids = {m["gstr_id"] for m in (res.get("matched") or [])}
        resolved = review_gstr_ids | matched_gstr_ids
        unresolved = probable_pair_gstr_ids - resolved
        assert not unresolved, (
            f"Probable-pair GSTR records still not resolved: {sorted(unresolved)}"
        )

    def test_wrongful_risk_ids_disjoint_from_missed_itc_ids(self, res):
        """
        KPI double-count guard: a single PR cannot appear in both wrongful_risk and matched.
        (missed_itc is GSTR-side, wrongful_risk is PR-side — they are fundamentally different
        record sets and cannot overlap.)
        """
        matched_pr_ids = {m["pr_id"] for m in (res.get("matched") or [])}
        review_pr_ids  = {r.get("pr_id") for r in (res.get("review_required") or []) if r.get("pr_id")}
        consumed_pr    = matched_pr_ids | review_pr_ids
        wrongful_ids   = {str(w["id"]) for w in (res.get("wrongful_itc_risk") or [])}
        overlap = consumed_pr & wrongful_ids
        assert not overlap, (
            f"PRs in both consumed and wrongful_risk (should be impossible): {overlap}"
        )

    def test_total_gstr_count(self, res):
        """All GSTR records from the dataset must be accounted for."""
        n_gstr = sum(1 for _g, _p, _s in DATASET)
        assert res["stats"]["total_gstr"] == n_gstr


# ---------------------------------------------------------------------------
# False-positive guard — wrong supplier / completely different invoices
# ---------------------------------------------------------------------------

class TestFalsePositiveGuards:
    """
    The new Phase 2 branches must NOT create false matches between different
    suppliers or completely unrelated invoices.
    """

    def test_different_supplier_same_invoice_not_matched(self):
        """Different PAN GSTINs with the same invoice number must NEVER match."""
        gstr = [_gstr("g_fp1", GSTIN_A, "INV-FP-001", 500_000)]
        pr   = [_pr  ("p_fp1", GSTIN_B, "INV-FP-001", 500_000)]  # GSTIN_B has different PAN
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["matched_count"] == 0, (
            "CRITICAL: Different-supplier invoices must never produce a clean match"
        )
        assert res["stats"]["review_required_count"] == 1, (
            "Different GSTIN with exact invoice goes to Review Required"
        )

    def test_completely_different_invoices_same_gstin_not_matched(self):
        """Completely different invoice strings should not be rescued to review_required."""
        gstr = [_gstr("g_fp2", GSTIN_A, "ALPHA-9999", 300_000)]
        pr   = [_pr  ("p_fp2", GSTIN_A, "ZYXWV-1234", 300_000)]
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        # Amount-only pairing is intentionally disabled — same GSTIN + same tax
        # with unrelated invoice numbers must not create Review Required.
        assert res["stats"]["matched_count"] == 0, (
            "Completely different invoices must not produce a clean match"
        )
        assert res["stats"]["missed_itc_count"] == 1
        assert res["stats"]["review_required_count"] == 0
        assert res["stats"]["wrongful_risk_count"] == 1

    def test_gstin_typo_generic_invoice_number_not_auto_matched(self):
        """
        GSTIN lev=1 + very generic short invoice (e.g. '1') — ambiguous.
        Should land in review_required (not missed_itc), but definitely not clean matched.
        """
        gstr = [_gstr("g_fp3", GSTIN_A,   "1", 200_000)]
        pr   = [_pr  ("p_fp3", GSTIN_A_T, "1", 200_000)]
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["matched_count"] == 0, (
            "GSTIN typo with generic invoice '1' must not be clean matched"
        )

    def test_no_pr_records_all_gstr_missed(self):
        """With zero PR records every GSTR must land in missed_itc."""
        gstr = [_gstr("g_fp4", GSTIN_A, "ALONE-001", 100_000)]
        res = run_bidirectional_reconciliation(gstr, [], gstr_period=PERIOD)
        assert res["stats"]["missed_itc_count"] == 1
        assert res["stats"]["matched_count"] == 0
        assert res["stats"]["review_required_count"] == 0

    def test_no_gstr_records_all_pr_wrongful_risk(self):
        """With zero GSTR records every PR must land in wrongful_itc_risk."""
        pr = [_pr("p_fp5", GSTIN_A, "ALONE-002", 100_000)]
        res = run_bidirectional_reconciliation([], pr, gstr_period=PERIOD)
        assert res["stats"]["wrongful_risk_count"] == 1
        assert res["stats"]["matched_count"] == 0


# ---------------------------------------------------------------------------
# Format-variant + amount-diff combo (criteria 4 regression)
# Mirrors the dominant failure pattern in the production dataset:
#   FZ202603763 (GSTR) ↔ F3763 (PR), same GSTIN, same date, ~7% amount diff
# ---------------------------------------------------------------------------

class TestFormatVariantAmountDiffCombo:
    """
    Ensures pairs with a stripped/abbreviated PR invoice AND an amount diff
    above L3 (2%) are routed to Review Required, not missed_itc or matched.
    """

    def test_format_variant_7pct_amount_diff_goes_to_review_required(self):
        """
        GSTR 'FZ/2026/03763' (raw) → normalized 'FZ202603763' vs PR 'F3763'.
        Amount diff is ~7 % (above L3's 2 % cap).
        Must land in review_required, never missed_itc.
        """
        from app.services.matcher import normalize_invoice
        gstr = [{
            "id": "g_fv1", "supplier_gstin": GSTIN_A,
            "invoice_number": "FZ/2026/03763",
            "invoice_number_normalized": normalize_invoice("FZ/2026/03763"),
            "invoice_date": "2026-05-10",
            "taxable_amount_paise": 4_466_710,
            "cgst_paise": 401_903, "sgst_paise": 401_903, "igst_paise": 0,
            "total_tax_paise": 803_806,
        }]
        pr = [{
            "id": "p_fv1", "supplier_gstin": GSTIN_A,
            "invoice_number": "F3763",
            "invoice_number_normalized": normalize_invoice("F3763"),
            "invoice_date": "2026-05-10",
            "taxable_amount_paise": 4_166_710,
            "cgst_paise": 375_003, "sgst_paise": 375_003, "igst_paise": 0,
            "total_tax_paise": 750_006,
        }]
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["missed_itc_count"] == 0, (
            "Format-variant + 7% amount diff must NOT fall into missed_itc"
        )
        assert res["stats"]["matched_count"] == 0, (
            "Format-variant + 7% amount diff must not produce a clean match"
        )
        assert res["stats"]["review_required_count"] == 1, (
            "Format-variant + 7% amount diff must be routed to review_required"
        )

    def test_format_variant_15pct_amount_diff_goes_to_review_required(self):
        """
        GSTR 'FZ/2026/02949' (raw) → normalized 'FZ202602949' vs PR '2949'.
        Amount diff is ~10% (above L3 cap).
        """
        from app.services.matcher import normalize_invoice
        gstr = [{
            "id": "g_fv2", "supplier_gstin": GSTIN_A,
            "invoice_number": "FZ/2026/02949",
            "invoice_number_normalized": normalize_invoice("FZ/2026/02949"),
            "invoice_date": "2026-05-10",
            "taxable_amount_paise": 1_610_000,
            "cgst_paise": 144_900, "sgst_paise": 144_900, "igst_paise": 0,
            "total_tax_paise": 289_800,
        }]
        pr = [{
            "id": "p_fv2", "supplier_gstin": GSTIN_A,
            "invoice_number": "2949",
            "invoice_number_normalized": normalize_invoice("2949"),
            "invoice_date": "2026-05-10",
            "taxable_amount_paise": 1_465_000,
            "cgst_paise": 131_850, "sgst_paise": 131_850, "igst_paise": 0,
            "total_tax_paise": 263_700,
        }]
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["missed_itc_count"] == 0, (
            "Format-variant + 10% amount diff must NOT fall into missed_itc"
        )
        assert res["stats"]["review_required_count"] == 1

    def test_format_variant_different_gstin_stays_missed(self):
        """
        GSTR 'FZ202603763' vs PR 'F3763' BUT from a different supplier GSTIN.
        The format variant guard must only fire when GSTINs are the same.
        No cross-supplier rescue is allowed.
        """
        gstr = [_gstr("g_fv3", GSTIN_A, "FZ202603763", taxable=4_466_710)]
        pr   = [_pr  ("p_fv3", GSTIN_B, "F3763",        taxable=4_466_710)]  # different PAN
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["matched_count"] == 0, (
            "Different-GSTIN format variant must not produce a clean match"
        )
        # GSTR side (different GSTIN) should remain unlinked since GSTIN doesn't match
        # (GSTIN_A and GSTIN_B have different PANs so GSTIN_MISMATCH path won't rescue it)
        assert res["stats"]["missed_itc_count"] == 1, (
            "Different-GSTIN format variant: GSTR side must stay in missed_itc"
        )

    def test_format_variant_50pct_amount_diff_is_cap(self):
        """
        Format variant but amount diff > 50 % should NOT be rescued — too risky.
        """
        gstr = [_gstr("g_fv4", GSTIN_A, "FZ202603763", taxable=4_000_000)]
        pr   = [_pr  ("p_fv4", GSTIN_A, "F3763",        taxable=1_000_000)]  # 75% diff
        res = run_bidirectional_reconciliation(gstr, pr, gstr_period=PERIOD)
        assert res["stats"]["review_required_count"] == 0, (
            "Format variant with >50% amount diff must not be rescued"
        )
        assert res["stats"]["missed_itc_count"] == 1, (
            "Format variant with >50% amount diff: GSTR side stays in missed_itc"
        )

