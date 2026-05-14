"""
test_false_positives.py
Scenario: Matches that look right but are wrong.
Run: PYTHONPATH=. pytest tests/test_false_positives.py -v
"""
import pytest
from datetime import date
from app.services.matcher import match_gstr_to_pr, normalize_invoice, _match_gstr_to_pr_pair, invoice_similarity
from app.services.reconciliation import _accept_reconciliation_pair

def make_gstr(invoice="INV001", gstin="27ABCDE1234F1Z0", invoice_date="2024-04-01",
              taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000):
    return {
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

def make_pr(invoice="INV001", gstin="27ABCDE1234F1Z0", invoice_date="2024-04-01",
            taxable_paise=100000, igst_paise=0, cgst_paise=9000, sgst_paise=9000, id="pr-001"):
    return {
        "id": id,
        "supplier_gstin": gstin,
        "invoice_number_normalized": normalize_invoice(invoice),
        "invoice_number": invoice,
        "invoice_date": date.fromisoformat(invoice_date),
        "taxable_amount_paise": taxable_paise,
        "igst_paise": igst_paise,
        "cgst_paise": cgst_paise,
        "sgst_paise": sgst_paise,
        "total_tax_paise": igst_paise + cgst_paise + sgst_paise,
    }

class TestL4SilentFailure:
    def test_invoice_format_difference_rejected_at_engine_level(self):
        g = make_gstr(invoice="INV/24/001")
        p = make_pr(invoice="INV/2024/001")
        raw = _match_gstr_to_pr_pair(g, p)
        final = match_gstr_to_pr(g, [p])
        print(f"\nRaw matcher level: {raw.level}")
        print(f"Final match level: {getattr(final,'level',None)}, matched: {getattr(final,'matched',False)}")
        if raw.level == 4:
            accepted = _accept_reconciliation_pair(g, p, raw)
            assert not accepted, (
                "L4 confirmed rejected by _accept_reconciliation_pair. "
                "CA sees L6 with no explanation. "
                "Consider surfacing L4 as needs-review instead of silent L6."
            )

    def test_l4_template_exists_but_no_ca_sees_it(self):
        from app.services.decision_templates import generate_decision
        d = generate_decision("L4_INVOICE_NUM", source_software="Tally")
        assert d.what != "" and d.next != "", "L4 template must render"
        g = make_gstr(invoice="INV001A")
        p = make_pr(invoice="INV001B")
        raw = _match_gstr_to_pr_pair(g, p)
        if raw.level == 4:
            assert _accept_reconciliation_pair(g, p, raw) is False, (
                "L4 is always rejected — no CA will ever see the L4 decision template."
            )

class TestL5FalsePositive:
    def test_consecutive_invoice_numbers_same_amount_L5_risk(self):
        g = make_gstr(invoice="INV001", taxable_paise=1000000)
        p_wrong = make_pr(invoice="INV002", taxable_paise=1000000, id="wrong")
        result = match_gstr_to_pr(g, [p_wrong])
        sim = invoice_similarity(
            normalize_invoice("INV001"),
            normalize_invoice("INV002")
        )
        print(f"\nINV001 vs INV002 similarity: {sim:.3f}, level: {getattr(result,'level',None)}")
        if result is not None and result.matched:
            assert result.level == 5, (
                f"Must be L5 at most for consecutive invoices. Got L{result.level}."
            )
            assert result.requires_human_review is True

    def test_correct_invoice_present_beats_consecutive_wrong_invoice(self):
        g = make_gstr(invoice="INV001", taxable_paise=1000000)
        p_correct = make_pr(invoice="INV001", taxable_paise=1000000, id="correct")
        p_wrong   = make_pr(invoice="INV002", taxable_paise=1000000, id="wrong")
        result = match_gstr_to_pr(g, [p_correct, p_wrong])
        assert result is not None and result.level == 1, (
            f"Correct L1 match must beat wrong L5 fuzzy. Got L{getattr(result,'level',None)}."
        )

    def test_same_invoice_different_date_still_matches(self):
        g = make_gstr(invoice="INV001", invoice_date="2024-04-01", taxable_paise=1000000)
        p = make_pr(invoice="INV001", invoice_date="2024-04-15", taxable_paise=1000000)
        result = match_gstr_to_pr(g, [p])
        print(f"\nSame invoice, 14-day gap: level={getattr(result,'level',None)}, matched={getattr(result,'matched',False)}")
        assert result is not None, (
            "Same invoice number, same amount, 14-day gap must produce some result — not None."
        )

class TestSupplierConfusion:
    def test_two_suppliers_same_invoice_picks_correct_gstin(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0", invoice="INV001")
        p_correct = make_pr(gstin="27ABCDE1234F1Z0", invoice="INV001", id="correct")
        p_wrong   = make_pr(gstin="29XYZDE1234F1Z0", invoice="INV001", id="wrong")
        result = match_gstr_to_pr(g, [p_wrong, p_correct])
        assert result is not None and result.level == 1, (
            "Must match correct GSTIN at L1, not wrong supplier."
        )

    def test_only_wrong_supplier_present_is_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0", invoice="INV001")
        p_wrong = make_pr(gstin="29XYZDE1234F1Z0", invoice="INV001", id="wrong")
        result = match_gstr_to_pr(g, [p_wrong])
        assert result is None or not result.matched, (
            "CRITICAL: Wrong supplier invoice must never match."
        )

    def test_gstin_one_char_off_is_L6(self):
        g = make_gstr(gstin="27ABCDE1234F1Z0")
        p = make_pr(gstin="27ABCDE1234F1Z1")
        result = match_gstr_to_pr(g, [p])
        assert result is None or not result.matched, (
            "One-character GSTIN difference must be L6. These are different legal entities."
        )

class TestDuplicateInvoicesInPR:
    def test_exact_duplicate_in_pr_picks_one(self):
        g = make_gstr(invoice="INV001", taxable_paise=100000)
        p1 = make_pr(invoice="INV001", taxable_paise=100000, id="pr-001")
        p2 = make_pr(invoice="INV001", taxable_paise=100000, id="pr-002")
        result = match_gstr_to_pr(g, [p1, p2])
        assert result is not None and result.level == 1, (
            "Duplicate PR entries must not crash matcher — must pick one L1 match."
        )

    def test_duplicate_with_different_amounts_picks_exact_match(self):
        g = make_gstr(invoice="INV001", taxable_paise=1000000)
        p_original = make_pr(invoice="INV001", taxable_paise=1000000, id="original")
        p_amended  = make_pr(invoice="INV001", taxable_paise=1050000, id="amended")
        result = match_gstr_to_pr(g, [p_original, p_amended])
        assert result is not None and result.level == 1, (
            "Must pick exact-amount match (L1) over amended one."
        )

class TestAmountWithoutInvoice:
    def test_same_amount_completely_different_invoice_not_L1_L2_L3(self):
        g = make_gstr(invoice="INV001", taxable_paise=100000)
        p = make_pr(invoice="PO99999", taxable_paise=100000)
        result = match_gstr_to_pr(g, [p])
        if result is not None and result.matched:
            assert result.level >= 4, (
                f"Different invoice numbers must not produce L1/L2/L3. Got L{result.level}."
            )

    def test_same_amount_no_invoice_match_requires_review(self):
        g = make_gstr(invoice="INV001", taxable_paise=100000)
        p = make_pr(invoice="ABCXYZ", taxable_paise=100050)
        result = match_gstr_to_pr(g, [p])
        if result is not None and result.matched:
            assert result.requires_human_review is True, (
                "Amount match without confirmed invoice identity must require review."
            )
