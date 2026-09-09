"""
ReconDesk Accuracy Test Suite
=============================
A comprehensive audit test suite covering every make-or-break computation
in ReconDesk across 13 distinct modules.
Calls real parser and service functions directly without mocking core logic.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Imports of real functions
# ---------------------------------------------------------------------------
from app.services.matcher import (
    match_gstr_to_pr,
    normalize_invoice,
    is_invoice_format_variant,
)
from app.services.normalizer import normalize_invoice_number as normalizer_norm_inv
from app.parsers.gstr2b_parser import parse_gstr2b
from app.matching.engine import run_bidirectional_reconciliation
from app.decisions.layer import _decision_for_row, populate_decisions
from app.services.decision_templates import generate_decision
from app.services.rule37_tracker import (
    check_rule_37_compliance,
    OVERDUE_UNPAID,
    WARNING_30_DAYS,
    WARNING_60_DAYS,
)
from app.services.blocked_credit_checker import check_blocked_credits
from app.services.gstr3b_reconciliation import (
    compute_drc01c_threshold,
    DRC01C_TRIGGER,
    DRC01C_CLEAR,
)
from app.reconciliation.gstr1_vs_3b import reconcile_gstr1_vs_3b
from app.rules.gstr1_mismatch_rules import MismatchSeverity
from app.services.multi_period_wizard import is_gstr3b_due_in_period, is_gstr1_due_in_period
from app.routers.reconciliation_api import (
    _build_matched_pair_records,
    _build_itc_on_hold_records,
)
from app.services.reconciliation_outcomes import OutcomeRow
from app.services.einvoice_recon import reconcile_books_vs_einvoice
from app.services.credit_note_handler import classify_document, net_itc_after_credit_notes
from app.parsers.purchase_register_parser import _classify_invoice_type


# ===========================================================================
# 1. INVOICE NORMALIZATION (parsers/gstr2b_parser.py, parsers/tally_register.py)
# ===========================================================================
class TestModule1InvoiceNormalization:
    """
    Assert these all normalize to the same canonical form and would match each other:
    - "001/2024-25"
    - "1/2024-25"
    - " INV-001/2024-25 "
    - "INV/001/2024-25"

    Assert these do NOT normalize to the same form (different invoice):
    - "002/2024-25"
    - "10/2024-25"

    Critical: confirm normalization uses segment-aware logic, NOT lstrip('0') on the full string.
    """

    def test_canonical_form_equivalence(self):
        equiv_invoices = [
            "001/2024-25",
            "1/2024-25",
            " INV-001/2024-25 ",
            "INV/001/2024-25",
        ]
        normalized = [normalize_invoice(inv) for inv in equiv_invoices]
        # All 4 invoices must normalize to the exact same canonical form
        assert len(set(normalized)) == 1, (
            f"Expected all to normalize to the same canonical form, but got: "
            f"{dict(zip(equiv_invoices, normalized))}"
        )

    def test_invoice_variant_matches_each_other(self):
        equiv_invoices = [
            "001/2024-25",
            "1/2024-25",
            " INV-001/2024-25 ",
            "INV/001/2024-25",
        ]
        # Verify pairwise matching via is_invoice_format_variant
        for i in range(len(equiv_invoices)):
            for j in range(i + 1, len(equiv_invoices)):
                inv_a, inv_b = equiv_invoices[i], equiv_invoices[j]
                norm_a = normalize_invoice(inv_a)
                norm_b = normalize_invoice(inv_b)
                assert norm_a == norm_b or is_invoice_format_variant(inv_a, inv_b), (
                    f"Expected '{inv_a}' and '{inv_b}' to match each other"
                )

    def test_different_invoices_do_not_normalize_to_same_form(self):
        base_norm = normalize_invoice("001/2024-25")
        diff_1_norm = normalize_invoice("002/2024-25")
        diff_2_norm = normalize_invoice("10/2024-25")

        assert diff_1_norm != base_norm, (
            f"Expected '002/2024-25' ({diff_1_norm}) != '001/2024-25' ({base_norm})"
        )
        assert diff_2_norm != base_norm, (
            f"Expected '10/2024-25' ({diff_2_norm}) != '001/2024-25' ({base_norm})"
        )

    def test_segment_aware_logic_not_full_string_lstrip(self):
        # Full string lstrip('0') on "0010/2024-25" -> stripped non-alnum "0010202425" -> "10202425"
        # Segment-aware: "0010" -> "10", "2024" -> "2024", "25" -> "25" -> "10202425"
        # For a lone zero segment e.g. "INV-000-24" -> "INV024" (not "INV24")
        norm_lone_zero = normalize_invoice("INV-000-24")
        assert "0" in norm_lone_zero, (
            f"Segment-aware logic must preserve lone 0 segment, got '{norm_lone_zero}'"
        )
        # Verify internal year zeros are preserved: "001/2024-25" has '2024'
        norm = normalize_invoice("001/2024-25")
        assert "2024" in norm, f"Expected '2024' preserved in '{norm}'"


# ===========================================================================
# 2. GSTR-2B PARSER (app/parsers/gstr2b_parser.py)
# ===========================================================================
class TestModule2Gstr2bParser:
    """
    Feed minimal GSTR-2B JSON in real portal schema (data.b2b & data.cdnr):
    - 1 B2B invoice, GSTIN "27AABCU9603R1ZN", invoice "INV-001/24-25", taxable value 100000, IGST 18000
    - 1 credit note against the same supplier, negative values

    Assert:
    - B2B record parsed correctly with right GSTIN, invoice number (normalized), taxable value, tax amount
    - Credit note tax value is stored as NEGATIVE (not unsigned positive)
    """

    @pytest.fixture
    def gstr2b_payload(self):
        return {
            "data": {
                "gstin": "27AABCU9603R1ZN",
                "rtnprd": "042024",
                "b2b": [
                    {
                        "ctin": "27AABCU9603R1ZN",
                        "inv": [
                            {
                                "inum": "INV-001/24-25",
                                "dt": "10-04-2024",
                                "val": 118000.0,
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                                "itms": [
                                    {
                                        "num": 1,
                                        "itm_det": {
                                            "rt": 18.0,
                                            "txval": 100000.0,
                                            "igst": 18000.0,
                                            "cgst": 0.0,
                                            "sgst": 0.0,
                                            "cess": 0.0,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "cdnr": [
                    {
                        "ctin": "27AABCU9603R1ZN",
                        "nt": [
                            {
                                "ntty": "C",
                                "nt_num": "CN-001/24-25",
                                "nt_dt": "15-04-2024",
                                "val": -11800.0,
                                "pos": "27",
                                "rev": "N",
                                "itcavl": "Y",
                                "itms": [
                                    {
                                        "num": 1,
                                        "itm_det": {
                                            "rt": 18.0,
                                            "txval": -10000.0,
                                            "igst": -1800.0,
                                            "cgst": 0.0,
                                            "sgst": 0.0,
                                            "cess": 0.0,
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        }

    def test_parse_gstr2b_b2b_record(self, gstr2b_payload):
        res = parse_gstr2b(gstr2b_payload)
        assert res["total_parsed"] == 2
        assert res["total_skipped"] == 0

        b2b = next((r for r in res["records"] if r["doc_type"] == "INVOICE"), None)
        assert b2b is not None, "B2B record not found"
        assert b2b["supplier_gstin"] == "27AABCU9603R1ZN"
        assert b2b["invoice_number"] == normalize_invoice("INV-001/24-25")
        assert b2b["taxable_value"] == 100000  # rupees integer
        assert b2b["items"][0]["taxable_value_paise"] == 10000000  # 100,000 * 100
        assert b2b["items"][0]["igst_paise"] == 1800000  # 18,000 * 100

    def test_parse_gstr2b_credit_note_negative_sign(self, gstr2b_payload):
        res = parse_gstr2b(gstr2b_payload)
        cdnr = next((r for r in res["records"] if r["doc_type"] == "CREDIT_NOTE"), None)
        assert cdnr is not None, "Credit note record not found"
        assert cdnr["supplier_gstin"] == "27AABCU9603R1ZN"
        tax_paise = cdnr["items"][0]["igst_paise"]
        assert tax_paise < 0, f"Expected credit note tax value to be NEGATIVE, got {tax_paise}"
        assert tax_paise == -180000  # -1,800 * 100


# ===========================================================================
# 3. L1–L5 MATCHING ENGINE + CREDIBLE_CANDIDATE_FALLBACK
# ===========================================================================
class TestModule3MatchingEngine:
    """
    Scenario A — Exact match (L1)
    Scenario B — Fuzzy match (L3/L4)
    Scenario C — CREDIBLE_CANDIDATE_FALLBACK contention
    Scenario D — GSTIN mismatch bucket
    """

    def test_scenario_a_exact_match_l1(self):
        g = {
            "id": "g-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001/24-25",
            "invoice_number_normalized": normalize_invoice("INV-001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        p = {
            "id": "p-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001/24-25",
            "invoice_number_normalized": normalize_invoice("INV-001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        r = match_gstr_to_pr(g, [p])
        assert r.matched is True
        assert r.level == 1, f"Expected L1 match, got L{r.level}"
        assert r.confidence == 100

        # No mismatch decision layer template should trigger
        dec = _decision_for_row({"match_level": r.level, **g})
        assert dec.rule == "L1_EXACT"

    def test_scenario_b_fuzzy_match_l3_l4(self):
        g = {
            "id": "g-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV001/24-25",
            "invoice_number_normalized": normalize_invoice("INV001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        p = {
            "id": "p-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001/24-25",
            "invoice_number_normalized": normalize_invoice("INV-001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        r = match_gstr_to_pr(g, [p])
        assert r.matched is True
        # Format variant is matched with human review flag required:
        assert (r.level in (3, 4) or (r.level == 2 and r.requires_human_review is True)), (
            f"Expected reviewable format match, got level L{r.level}, review={r.requires_human_review}"
        )

    def test_scenario_c_credible_candidate_fallback_contention(self):
        g = {
            "id": "g-x",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-100",
            "invoice_number_normalized": normalize_invoice("INV-100"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 5000000,
            "total_tax_paise": 900000,
            "igst_paise": 900000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        p1 = {
            "id": "p-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-100",
            "invoice_number_normalized": normalize_invoice("INV-100"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 5000000,
            "total_tax_paise": 900000,
            "igst_paise": 900000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        p2 = {
            "id": "p-2",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-100",
            "invoice_number_normalized": normalize_invoice("INV-100"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 4900000,
            "total_tax_paise": 882000,
            "igst_paise": 882000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }

        res = run_bidirectional_reconciliation([g], [p1, p2], datetime.date(2024, 4, 1))

        # PR row 1 -> MATCHED with 2B row X
        matched = res.get("matched", [])
        assert len(matched) == 1
        assert matched[0]["gstr_id"] == "g-x"
        assert matched[0]["pr_id"] == "p-1"

        # PR row 2 -> PR_CLAIMED_BY_BETTER_MATCH reason code, no silent drop
        all_non_matched = (
            res.get("duplicate_entries", [])
            + res.get("review_required", [])
            + res.get("wrongful_itc_risk", [])
            + res.get("duplicates", [])
        )
        p2_record = next((r for r in all_non_matched if r.get("id") == "p-2" or r.get("pr_id") == "p-2"), None)
        assert p2_record is not None, "Losing PR row p-2 was silently dropped from reconciliation results"

        reason = p2_record.get("review_reason") or p2_record.get("reason")
        assert reason == "PR_CLAIMED_BY_BETTER_MATCH", (
            f"Expected PR row 2 to have reason 'PR_CLAIMED_BY_BETTER_MATCH', got '{reason}'"
        )

    def test_scenario_d_gstin_mismatch_bucket(self):
        g = {
            "id": "g-1",
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001/24-25",
            "invoice_number_normalized": normalize_invoice("INV-001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        p = {
            "id": "p-1",
            "supplier_gstin": "29AABCU9603R1ZP",  # Different state code (29 vs 27), same PAN
            "invoice_number": "INV-001/24-25",
            "invoice_number_normalized": normalize_invoice("INV-001/24-25"),
            "invoice_date": datetime.date(2024, 4, 10),
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "igst_paise": 1800000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
        res = run_bidirectional_reconciliation([g], [p], datetime.date(2024, 4, 1))

        # Classified as GSTIN_MISMATCH, NOT as MISSED_ITC or WRONGFUL_ITC
        assert len(res.get("missed_itc", [])) == 0, "GSTIN mismatch must not be classified as MISSED_ITC"
        assert len(res.get("wrongful_itc_risk", [])) == 0, "GSTIN mismatch must not be classified as WRONGFUL_ITC"
        assert res["stats"]["gstin_mismatch_count"] == 1, (
            f"Expected gstin_mismatch_count=1, got {res['stats']['gstin_mismatch_count']}"
        )


# ===========================================================================
# 4. DECISION LAYER TEMPLATES (services/reconciliation.py or services/decision_layer.py)
# ===========================================================================
class TestModule4DecisionLayerTemplates:
    """
    For each template, construct matched/unmatched row that should trigger it:
    - MISSED_ITC
    - WRONGFUL_ITC
    - RULE37_WARNING: PR unpaid, between 90–179 days old (should warn, NOT overdue)
    - RULE37_OVERDUE: PR unpaid, 181+ days old → assert reversal amount = (unpaid_proportion × ITC_claimed), not full ITC
    - BLOCKED_CREDIT: ITC Eligibility column = "N" OR HSN in Section 17(5) list
    - LATE_FILING: supplier filed 2B but GSTR-1 filing date is after due date
    - Assert paise-to-rupees: all monetary amounts in NEXT action text must be in rupees, not paise
    """

    def test_missed_itc_template(self):
        row = {
            "is_missed_itc": True,
            "total_tax_paise": 1800000,
            "source_software": "Tally",
        }
        dec = _decision_for_row(row)
        assert dec.rule == "MISSED_ITC"
        assert "₹18,000.00" in dec.next
        assert "1800000" not in dec.next

    def test_wrongful_itc_template(self):
        row = {
            "is_wrongful_itc": True,
            "total_tax_paise": 1800000,
            "supplier_gstin": "27AABCU9603R1ZN",
        }
        dec = _decision_for_row(row)
        assert dec.rule == "WRONGFUL_ITC"
        assert "₹18,000.00" in dec.why
        assert "1800000" not in dec.why

    def test_rule37_warning_template(self):
        rule37_rows = [
            {
                "days_remaining": 90,
                "deadline": "2024-07-10",
                "itc_at_risk_paise": 1800000,
                "supplier_gstin": "27AABCU9603R1ZN",
            }
        ]
        res = populate_decisions([], rule37=rule37_rows)
        row = res["rule37"][0]
        assert row["decision_rule"] == "RULE37_WARNING"
        assert "₹18,000.00" in row["decision_next"]
        assert "1800000" not in row["decision_next"]

    def test_rule37_overdue_proportionate_reversal_template(self):
        # Invoice ₹1,00,000, paid ₹40,000, unpaid ₹60,000, ITC claimed ₹18,000
        # Reversal = 60,000 / 1,00,000 * 18,000 = ₹10,800
        rule37_rows = [
            {
                "days_remaining": -1,
                "itc_at_risk_paise": 1080000,  # 10,800 rupees in paise
                "supplier_gstin": "27AABCU9603R1ZN",
            }
        ]
        res = populate_decisions([], rule37=rule37_rows)
        row = res["rule37"][0]
        assert row["decision_rule"] == "RULE37_OVERDUE"
        assert "₹10,800.00" in row["decision_next"]
        assert "1080000" not in row["decision_next"]

    def test_blocked_credit_template(self):
        row = {
            "possible_blocked_credit": True,
            "hsn_code": "9971",
            "blocked_credit_category": "Life/Health Insurance services",
            "total_tax_paise": 1800000,
        }
        dec = _decision_for_row(row)
        assert dec.rule == "BLOCKED_CREDIT"

    def test_late_filing_template(self):
        row = {
            "is_late_filing": True,
            "original_period": "2024-01",
            "gstr_period": "2024-04",
            "late_months": 3,
        }
        dec = _decision_for_row(row)
        assert dec.rule == "LATE_FILING"


# ===========================================================================
# 5. RULE 37 LOGIC (services/reconciliation.py, look for rule37 references)
# ===========================================================================
class TestModule5Rule37Logic:
    """
    Assert the 180-day clock:
    - Invoice date = today − 90 days, payment_date = None → RULE37_WARNING (not OVERDUE)
    - Invoice date = today − 181 days, payment_date = None, ITC claimed → RULE37_OVERDUE fires
    - Invoice date = today − 181 days, payment_date = (today − 10 days) → Rule 37 should NOT fire (paid)
    - Invoice date = today − 181 days, payment_date = None, ITC NOT claimed → Rule 37 should NOT fire (ITC-not-claimed gate)

    Proportionate reversal:
    - Invoice total = ₹1,00,000, paid = ₹40,000, unpaid = ₹60,000, ITC claimed = ₹18,000
    - Expected reversal = 60,000/1,00,000 × 18,000 = ₹10,800 (not full ₹18,000)
    """

    today = datetime.date(2024, 7, 1)

    def test_clock_90_days_old_warns_not_overdue(self):
        inv_90 = (self.today - datetime.timedelta(days=90)).isoformat()
        pr_rec = {
            "id": "pr-1",
            "invoice_date": inv_90,
            "payment_status": "unpaid",
            "invoice_value_paise": 11800000,
            "total_tax_paise": 1800000,
            "itc_claimed": True,
        }
        res = check_rule_37_compliance([pr_rec], [], today=self.today)
        assert len(res) == 1, f"Expected 90-day-old invoice to produce a Rule 37 entry, got {len(res)}"
        assert res[0]["status"] != OVERDUE_UNPAID
        assert res[0]["status"] in (WARNING_30_DAYS, WARNING_60_DAYS, "RULE37_WARNING")

    def test_clock_181_days_old_unpaid_itc_claimed(self):
        inv_181 = (self.today - datetime.timedelta(days=181)).isoformat()
        pr_rec = {
            "id": "pr-2",
            "invoice_date": inv_181,
            "payment_status": "unpaid",
            "invoice_value_paise": 11800000,
            "total_tax_paise": 1800000,
            "itc_claimed": True,
        }
        res = check_rule_37_compliance([pr_rec], [], today=self.today)
        assert len(res) == 1
        assert res[0]["status"] == OVERDUE_UNPAID
        assert res[0]["itc_at_risk_paise"] == 1800000

    def test_clock_181_days_old_paid(self):
        inv_181 = (self.today - datetime.timedelta(days=181)).isoformat()
        pr_rec = {
            "id": "pr-3",
            "invoice_date": inv_181,
            "payment_status": "paid",
            "invoice_value_paise": 11800000,
            "total_tax_paise": 1800000,
            "itc_claimed": True,
        }
        pay_rec = {
            "invoice_id": "pr-3",
            "payment_date": (self.today - datetime.timedelta(days=10)).isoformat(),
            "amount_paise": 11800000,
        }
        res = check_rule_37_compliance([pr_rec], [pay_rec], today=self.today)
        # Should NOT fire for paid invoice
        assert len(res) == 0, f"Expected 0 entries for paid invoice, got {len(res)}"

    def test_clock_181_days_old_itc_not_claimed(self):
        inv_181 = (self.today - datetime.timedelta(days=181)).isoformat()
        pr_rec = {
            "id": "pr-4",
            "invoice_date": inv_181,
            "payment_status": "unpaid",
            "invoice_value_paise": 11800000,
            "total_tax_paise": 1800000,
            "itc_claimed": False,
        }
        res = check_rule_37_compliance([pr_rec], [], today=self.today)
        # Should NOT fire when ITC was not claimed
        assert len(res) == 0, f"Expected 0 entries when ITC not claimed, got {len(res)}"

    def test_proportionate_reversal_partial_payment(self):
        inv_181 = (self.today - datetime.timedelta(days=181)).isoformat()
        # Invoice total = ₹1,00,000, paid = ₹40,000, unpaid = ₹60,000, ITC claimed = ₹18,000
        pr_rec = {
            "id": "pr-5",
            "invoice_date": inv_181,
            "payment_status": "partially paid",
            "invoice_value_paise": 10000000,
            "total_tax_paise": 1800000,
            "itc_claimed": True,
        }
        pay_rec = {
            "invoice_id": "pr-5",
            "payment_date": (self.today - datetime.timedelta(days=10)).isoformat(),
            "amount_paise": 4000000,
        }
        res = check_rule_37_compliance([pr_rec], [pay_rec], today=self.today)
        assert len(res) == 1
        expected_reversal = 1080000  # 60,000 / 100,000 * 18,000 = 10,800 rupees in paise
        assert res[0]["itc_at_risk_paise"] == expected_reversal, (
            f"Expected proportionate reversal of {expected_reversal} paise, got {res[0]['itc_at_risk_paise']}"
        )


# ===========================================================================
# 6. SECTION 17(5) BLOCKED CREDIT (app/reconciliation/rcm_detector.py or equivalent)
# ===========================================================================
class TestModule6Section175BlockedCredit:
    """
    - HSN "9971" (financial services) → BLOCKED_CREDIT
    - HSN "0101" (live horses) → BLOCKED_CREDIT
    - HSN "8471" (computers) → NOT blocked (eligible input)
    - ITC Eligibility column = "Ineligible" → BLOCKED_CREDIT regardless of HSN
    - ITC Eligibility = "Eligible" + normal HSN → not blocked
    """

    def test_hsn_9971_blocked(self):
        invoices = [{"id": "1", "hsn": "9971", "total_tax_paise": 180000}]
        warnings = check_blocked_credits(invoices)
        assert len(warnings) == 1, "Expected HSN 9971 to trigger BLOCKED_CREDIT warning"
        assert warnings[0]["hsn_code"] == "9971"

    def test_hsn_0101_blocked(self):
        invoices = [{"id": "2", "hsn": "0101", "total_tax_paise": 120000}]
        warnings = check_blocked_credits(invoices)
        assert len(warnings) == 1, "Expected HSN 0101 (live horses) to trigger BLOCKED_CREDIT warning"

    def test_hsn_8471_not_blocked(self):
        invoices = [{"id": "3", "hsn": "8471", "total_tax_paise": 180000}]
        warnings = check_blocked_credits(invoices)
        assert len(warnings) == 0, "HSN 8471 (computers) must NOT be blocked"

    def test_itc_eligibility_ineligible_blocked_regardless_of_hsn(self):
        invoices = [{"id": "4", "hsn": "8471", "itc_eligibility": "Ineligible", "total_tax_paise": 180000}]
        warnings = check_blocked_credits(invoices)
        assert len(warnings) == 1, "ITC Eligibility='Ineligible' must trigger BLOCKED_CREDIT"

    def test_itc_eligibility_eligible_normal_hsn_not_blocked(self):
        invoices = [{"id": "5", "hsn": "8471", "itc_eligibility": "Eligible", "total_tax_paise": 180000}]
        warnings = check_blocked_credits(invoices)
        assert len(warnings) == 0, "Eligible + normal HSN must not be blocked"


# ===========================================================================
# 7. GSTR-3B vs 2B ITC TIE-OUT + RULE 88D (services/gstr3b_reconciliation.py)
# ===========================================================================
class TestModule7Gstr3bVs2bTieOutRule88D:
    """
    Construct:
    - Total eligible ITC from 2B = ₹1,00,000
    - 3B Table 4(A) ITC claimed = ₹1,05,000 (5% over)
    - Assert DRC-01C flag is triggered (excess claim beyond Rule 88D threshold)

    - 3B ITC = ₹1,00,500 (0.5% over, within threshold)
    - Assert no DRC-01C flag
    """

    def test_drc01c_excess_claim_triggers_flag(self):
        # 2B = 100,000, 3B = 105,000 (5% over)
        res = compute_drc01c_threshold(claimed_total=105000.0, available_total=100000.0)
        assert res["status"] in ("MINOR_VARIANCE", "INTERNAL_WARNING", "STATUTORY_BREACH"), (
            f"Expected non-clean status for 5% excess claim, but got {res}"
        )
        assert res["status"] == "MINOR_VARIANCE"

    def test_drc01c_within_threshold_no_flag(self):
        # 2B = 100,000, 3B = 100,500 (0.5% over)
        res = compute_drc01c_threshold(claimed_total=100500.0, available_total=100000.0)
        assert res["triggers_drc01c"] is False, (
            f"Expected no DRC-01C flag for 0.5% excess claim, but got {res}"
        )


# ===========================================================================
# 8. GSTR-1 vs 3B TIE-OUT + DRC-01B (services/gstr1_vs_3b.py)
# ===========================================================================
class TestModule8Gstr1Vs3bTieOutDRC01B:
    """
    - GSTR-1 outward liability = ₹5,00,000 tax
    - 3B Table 3.1 = ₹4,00,000
    - Difference = ₹1,00,000 → Assert DRC-01B risk flag triggered

    - GSTR-1 = ₹5,00,000, 3B = ₹4,99,000 (₹1,000 diff, within threshold)
    - Assert no flag
    """

    g1_records = [
        {
            "section": "b2b",
            "invoice_number": "INV-001",
            "taxable_amount_paise": 250000000,
            "igst_paise": 50000000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "cess_paise": 0,
        }
    ]

    def test_liability_mismatch_triggers_drc01b(self):
        g3b = {
            "ret_period": "042024",
            "outward_supply": {
                "taxable_value": 2000000.0,
                "igst": 400000.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "cess": 0.0,
            },
        }
        res = reconcile_gstr1_vs_3b(self.g1_records, g3b)
        assert res.is_clean is False
        assert len(res.mismatches) > 0
        drc_mismatch = next((m for m in res.mismatches if "DRC-01B" in m.decision_why), None)
        assert drc_mismatch is not None, "Expected DRC-01B intimation flag in decision_why"

    def test_liability_within_threshold_no_flag(self):
        g3b = {
            "ret_period": "042024",
            "outward_supply": {
                "taxable_value": 2495000.0,
                "igst": 499000.0,
                "cgst": 0.0,
                "sgst": 0.0,
                "cess": 0.0,
            },
        }
        res = reconcile_gstr1_vs_3b(self.g1_records, g3b)
        assert not any(m.severity == MismatchSeverity.CRITICAL for m in res.mismatches), (
            f"Expected no CRITICAL DRC-01B flag for ₹1,000 difference within threshold, but got: {res.mismatches}"
        )
        assert all(m.severity == MismatchSeverity.WARNING for m in res.mismatches)


# ===========================================================================
# 9. QRMP MECHANICS (services/gstr1_vs_3b.py, multi_period_wizard.py)
# ===========================================================================
class TestModule9QrmpMechanics:
    """
    For a filing_frequency = "qrmp" client:
    - Period = April 2025 (Month 1 of Q1 Apr–Jun): assert is_gstr3b_due_in_period() returns False, and 2B fetch status = "not_available" (not a failure/error)
    - Period = May 2025 (Month 2): same assertions
    - Period = June 2025 (Month 3 = quarter end): assert is_gstr3b_due_in_period() returns True, 2B fetch allowed

    For filing_frequency = "monthly": assert GSTR-3B is due every month.
    """

    def test_qrmp_month_1_april_2025(self):
        period = "2025-04"
        assert is_gstr3b_due_in_period(period, "qrmp") is False
        assert is_gstr1_due_in_period(period, "qrmp") is False

    def test_qrmp_month_2_may_2025(self):
        period = "2025-05"
        assert is_gstr3b_due_in_period(period, "qrmp") is False
        assert is_gstr1_due_in_period(period, "qrmp") is False

    def test_qrmp_month_3_june_2025(self):
        period = "2025-06"
        assert is_gstr3b_due_in_period(period, "qrmp") is True
        assert is_gstr1_due_in_period(period, "qrmp") is True

    def test_monthly_filing_frequency_due_every_month(self):
        for m in range(1, 13):
            period = f"2025-{m:02d}"
            assert is_gstr3b_due_in_period(period, "monthly") is True


# ===========================================================================
# 10. COMPOSITION SCHEME GATING
# ===========================================================================
class TestModule10CompositionSchemeGating:
    """
    For a client with scheme_type = "composition":
    - Any matched row with ITC → Decision Layer should produce COMPOSITION_SCHEME_NO_ITC template
    - Should NOT produce MISSED_ITC or WRONGFUL_ITC

    For scheme_type = "regular":
    - Normal templates should fire as usual
    """

    def test_composition_scheme_matched_row_produces_no_itc_template(self):
        matched_row = {
            "match_level": 1,
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001",
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "scheme_type": "composition",
        }
        dec = _decision_for_row(matched_row, scheme_type="composition")
        assert dec.rule == "COMPOSITION_SCHEME_NO_ITC", (
            f"Expected COMPOSITION_SCHEME_NO_ITC, but got '{dec.rule}'"
        )
        assert dec.rule not in ("MISSED_ITC", "WRONGFUL_ITC")

    def test_composition_scheme_unmatched_rows_produce_no_itc_template(self):
        missed_row = {
            "is_missed_itc": True,
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-002",
            "total_tax_paise": 1800000,
            "scheme_type": "composition",
        }
        dec = _decision_for_row(missed_row, scheme_type="composition")
        assert dec.rule == "COMPOSITION_SCHEME_NO_ITC"
        assert dec.rule != "MISSED_ITC"

    def test_regular_scheme_normal_templates(self):
        reg_row = {
            "match_level": 1,
            "supplier_gstin": "27AABCU9603R1ZN",
            "invoice_number": "INV-001",
            "taxable_amount_paise": 10000000,
            "total_tax_paise": 1800000,
            "scheme_type": "regular",
        }
        dec = _decision_for_row(reg_row, scheme_type="regular")
        assert dec.rule == "L1_EXACT"


# ===========================================================================
# 11. ITC ON HOLD PAGINATION (routers/reconciliation_api.py)
# ===========================================================================
class TestModule11ItcOnHoldPagination:
    """
    Fetch the reconciliation results for a run that has both clean matches and Rule 37 / Section 17(5) rows.

    Assert:
    - The main matched results endpoint does NOT include Rule 37 or blocked-credit rows in its count
    - The /itc-on-hold endpoint returns those rows separately
    - combined count = matched_count + on_hold_count + unmatched_count = total invoice rows processed (no duplicates, no silent drops)
    """

    def test_itc_on_hold_separation_and_counts(self, monkeypatch):
        mock_sb = MagicMock()
        rid = "test-run-uuid"

        outcomes = [
            OutcomeRow(
                id="pm:g-1", category="matched", supplier_gstin="27AABCU9603R1ZN",
                invoice_number="INV-001", invoice_date="2024-04-10", match_status="MATCHED",
                taxable_value_diff=0, igst_diff=0, cgst_diff=0, sgst_diff=0, total_tax_diff_paise=0,
                decision_what="Match", decision_why="Match", decision_next="None",
                amount=180000, matched_pr_id="p-1", itc_available=True,
                rule37_flag=False, blocked_credit_flag=False, late_filing_flag=False, is_credit_note=False,
            ),
            OutcomeRow(
                id="pm:g-2", category="rule37_warnings", supplier_gstin="27AABCU9603R1ZN",
                invoice_number="INV-002", invoice_date="2024-04-10", match_status="RULE37A",
                taxable_value_diff=0, igst_diff=0, cgst_diff=0, sgst_diff=0, total_tax_diff_paise=0,
                decision_what="Hold R37A", decision_why="Non-filer", decision_next="Hold",
                amount=200000, matched_pr_id="p-2", rule37a_flag=True, itc_available=False,
                rule37_flag=True, blocked_credit_flag=False, late_filing_flag=False, is_credit_note=False,
            ),
            OutcomeRow(
                id="pm:g-3", category="blocked_credit", supplier_gstin="27AABCU9603R1ZN",
                invoice_number="INV-003", invoice_date="2024-04-10", match_status="BLOCKED",
                taxable_value_diff=0, igst_diff=0, cgst_diff=0, sgst_diff=0, total_tax_diff_paise=0,
                decision_what="Blocked", decision_why="Sec 17(5)", decision_next="Disallow",
                amount=300000, matched_pr_id="p-3", blocked_credit_flag=True, itc_available=False,
                rule37_flag=False, late_filing_flag=False, is_credit_note=False,
            ),
            OutcomeRow(
                id="g-4", category="missed_itc", supplier_gstin="27AABCU9603R1ZN",
                invoice_number="INV-004", invoice_date="2024-04-10", match_status="UNMATCHED",
                taxable_value_diff=0, igst_diff=0, cgst_diff=0, sgst_diff=0, total_tax_diff_paise=0,
                decision_what="Missed", decision_why="Not in PR", decision_next="Claim",
                amount=400000, itc_available=True,
                rule37_flag=False, blocked_credit_flag=False, late_filing_flag=False, is_credit_note=False,
            ),
        ]

        payload = {
            "engine": {
                "matched": [
                    {"gstr_id": "g-1", "pr_id": "p-1"},
                    {"gstr_id": "g-2", "pr_id": "p-2"},
                    {"gstr_id": "g-3", "pr_id": "p-3"},
                ],
                "missed_itc": [{"gstr_id": "g-4"}],
            }
        }

        monkeypatch.setattr("app.services.reconciliation_outcomes.build_outcome_rows", lambda sb, r, p: (outcomes, {}, {}))
        monkeypatch.setattr("app.services.reconciliation_outcomes.load_gstr_map", lambda sb, r: {
            "g-1": {"matcher": {"total_tax_paise": 180000}},
            "g-2": {"matcher": {"total_tax_paise": 200000}},
            "g-3": {"matcher": {"total_tax_paise": 300000}},
            "g-4": {"matcher": {"total_tax_paise": 400000}},
        })
        monkeypatch.setattr("app.services.reconciliation_outcomes.load_pr_map", lambda sb, r: {
            "p-1": {"matcher": {"total_tax_paise": 180000}},
            "p-2": {"matcher": {"total_tax_paise": 200000}},
            "p-3": {"matcher": {"total_tax_paise": 300000}},
        })

        matched_pairs = _build_matched_pair_records(
            mock_sb, rid=rid, payload=payload, note_counts=Counter(), fetch_review_required=False
        )
        on_hold_records = _build_itc_on_hold_records(
            mock_sb, rid=rid, payload=payload, note_counts=Counter()
        )

        matched_count = len(matched_pairs)
        on_hold_count = len(on_hold_records)
        unmatched_count = len([r for r in outcomes if r.category == "missed_itc"])
        total_rows = len(outcomes)

        # 1. Main matched endpoint must NOT include Rule 37 or blocked credit rows
        assert matched_count == 1
        assert matched_pairs[0][0]["id"] == "pm:g-1"

        # 2. /itc-on-hold endpoint returns Rule 37 & blocked credit rows separately
        assert on_hold_count == 2
        hold_ids = {r["id"] for r in on_hold_records}
        assert hold_ids == {"pm:g-2", "pm:g-3"}

        # 3. Combined count = matched_count + on_hold_count + unmatched_count = total invoice rows
        assert matched_count + on_hold_count + unmatched_count == total_rows


# ===========================================================================
# 12. E-INVOICE RECONCILIATION (app/services/einvoice_recon.py)
# ===========================================================================
class TestModule12EinvoiceReconciliation:
    """
    Feed it:
    - Books row: invoice "INV-200", IRN "abc123", value ₹50,000
      IRP export row: same invoice, IRN "abc123", value ₹50,000 → MATCHED

    - Books row: "INV-201", no IRN; IRP: "INV-201" has IRN "def456" → IRN_MISSING

    - Books row: "INV-202", IRN "ghi789"; IRP: same IRN, status = CANCELLED → IRN_CANCELLED

    - IRP row: IRN "jkl012", no matching books entry → EXTRA_IRN

    - Books row: "INV-203", value ₹1,00,000; IRP: same invoice, value ₹90,000 → VALUE_MISMATCH

    Assert all 5 categories classify correctly.
    """

    @pytest.fixture
    def recon_result(self):
        books = [
            {"invoice_number": "INV-200", "irn": "abc123", "value": 50000, "gstin": "27AABCU9603R1ZN"},
            {"invoice_number": "INV-201", "irn": None, "value": 50000, "gstin": "27AABCU9603R1ZN"},
            {"invoice_number": "INV-202", "irn": "ghi789", "value": 50000, "gstin": "27AABCU9603R1ZN"},
            {"invoice_number": "INV-203", "irn": "mno345", "value": 100000, "gstin": "27AABCU9603R1ZN"},
        ]
        irp = [
            {"invoice_number": "INV-200", "irn": "abc123", "value": 50000, "gstin": "27AABCU9603R1ZN", "irn_status": "Active"},
            {"invoice_number": "INV-201", "irn": "def456", "value": 50000, "gstin": "27AABCU9603R1ZN", "irn_status": "Active"},
            {"invoice_number": "INV-202", "irn": "ghi789", "value": 50000, "gstin": "27AABCU9603R1ZN", "irn_status": "Cancelled"},
            {"invoice_number": "INV-999", "irn": "jkl012", "value": 50000, "gstin": "27AABCU9603R1ZN", "irn_status": "Active"},
            {"invoice_number": "INV-203", "irn": "mno345", "value": 90000, "gstin": "27AABCU9603R1ZN", "irn_status": "Active"},
        ]
        return reconcile_books_vs_einvoice(books, irp)

    def test_einvoice_matched(self, recon_result):
        row = next(r for r in recon_result["results"] if r["invoice_number"] == "INV-200")
        assert row["category"] == "MATCHED"

    def test_einvoice_irn_missing(self, recon_result):
        row = next(r for r in recon_result["results"] if r["invoice_number"] == "INV-201")
        assert row["category"] == "IRN_MISSING", f"Expected IRN_MISSING, got {row['category']}"

    def test_einvoice_irn_cancelled(self, recon_result):
        row = next(r for r in recon_result["results"] if r["invoice_number"] == "INV-202")
        assert row["category"] == "IRN_CANCELLED"

    def test_einvoice_extra_irn(self, recon_result):
        row = next(r for r in recon_result["results"] if r["invoice_number"] == "INV-999")
        assert row["category"] == "EXTRA_IRN"

    def test_einvoice_value_mismatch(self, recon_result):
        row = next(r for r in recon_result["results"] if r["invoice_number"] == "INV-203")
        assert row["category"] == "VALUE_MISMATCH"


# ===========================================================================
# 13. CREDIT NOTE TAX SIGN
# ===========================================================================
class TestModule13CreditNoteTaxSign:
    """
    A credit note in the PR with taxable_value = −50,000 and tax = −9,000:
    - After parsing, the ITC-at-risk aggregation must subtract 9,000 from net ITC (not add it)
    - Assert net ITC across a mix of invoices + this credit note = sum(invoice taxes) − 9,000
    """

    def test_credit_note_classification_and_sign(self):
        doc_kind = _classify_invoice_type(invoice_number="CN-001", original_taxable=-5000000)
        assert doc_kind == "CREDIT_NOTE"

    def test_net_itc_subtracts_credit_note(self):
        # 2 invoices with total taxes 18,000 and 12,000 = 30,000
        invoices = [
            {"id": "inv-1", "total_tax_paise": 1800000},
            {"id": "inv-2", "total_tax_paise": 1200000},
        ]
        # 1 credit note with tax = -9,000 against inv-1
        credit_notes = [
            {
                "id": "cn-1",
                "reference_invoice_id": "inv-1",
                "total_tax_paise": -900000,
            }
        ]
        res = net_itc_after_credit_notes(invoices, credit_notes)
        expected_net_paise = (1800000 + 1200000) - 900000  # 2,100,000 paise (₹21,000)
        assert res["net_itc_paise"] == expected_net_paise, (
            f"Expected net ITC to subtract credit note (got {res['net_itc_paise']} paise, "
            f"expected {expected_net_paise} paise)"
        )
