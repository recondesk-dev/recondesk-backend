"""12 tests — one per decision template."""
from __future__ import annotations
from app.services.decision_templates import generate_decision
from app.decisions.layer import populate_decisions


def test_l1_exact():
    d = generate_decision("L1_EXACT")
    assert "Exact match" in d.what
    assert "No action" in d.next


def test_l2_normalized():
    d = generate_decision(
        "L2_NORMALIZED",
        gstr_invoice="GST/0001/26",
        pr_invoice="GST126",
    )
    assert "Normalized invoice match" in d.what
    assert "GST/0001/26" in d.what and "GST126" in d.what
    assert "normalization" in d.why.lower() or "format variant" in d.why.lower()
    assert "No action required" in d.next


def test_l2_amount_diff():
    d = generate_decision("L2_AMOUNT_DIFF", diff="₹150.00", source_software="Tally")
    assert "₹150.00" in d.what
    assert "Tally" in d.why
    assert "purchase register" in d.next


def test_l3_amount_diff():
    d = generate_decision("L3_AMOUNT_DIFF", diff="₹5,000.00", pct="3.2", source_software="Busy", supplier_gstin="27AABCU9603R1ZX")
    assert "₹5,000.00" in d.what
    assert "3.2%" in d.what
    assert "Busy" in d.why
    assert "debit/credit note" in d.next


def test_l4_invoice_num():
    d = generate_decision("L4_INVOICE_NUM", source_software="Excel")
    assert "invoice numbers do not match" in d.what
    assert "Excel" in d.why
    assert "physical invoice" in d.next


def test_l5_probable():
    d = generate_decision("L5_PROBABLE", distance=2)
    assert "2 characters" in d.what
    assert "data entry error" in d.why
    assert "purchase register" in d.next


def test_missed_itc():
    d = generate_decision("MISSED_ITC", source_software="Tally", itc_amount="₹18,000.00")
    assert "Missing in Books" in d.what or "Available in 2B" in d.what
    assert "Tally" in d.why
    assert "₹18,000.00" in d.next


def test_wrongful_itc():
    d = generate_decision("WRONGFUL_ITC", supplier_gstin="27AABCU9603R1ZX", itc_amount="₹9,000.00")
    assert "2B" in d.what or "Not Reflected" in d.what or "Supplier" in d.what
    assert "₹9,000.00" in d.why
    assert "27AABCU9603R1ZX" in d.next


def test_rule37_overdue():
    d = generate_decision("RULE37_OVERDUE", itc_amount="₹25,000.00")
    assert "180 days" in d.what
    assert "Rule 37" in d.why
    assert "₹25,000.00" in d.next
    assert "24% interest" in d.next


def test_rule37_warning():
    d = generate_decision("RULE37_WARNING", days_remaining=30, deadline_date="2024-03-15", supplier_gstin="27AABCU9603R1ZX", itc_amount="₹12,000.00")
    assert "30 days" in d.what
    assert "2024-03-15" in d.what
    assert "180 days" in d.why
    assert "2024-03-15" in d.next
    assert "₹12,000.00" in d.next


def test_blocked_credit():
    d = generate_decision("BLOCKED_CREDIT", category="personal vehicle", hsn_code="8703")
    assert "personal vehicle" in d.what
    assert "8703" in d.why
    assert "17(5)" in d.next


def test_late_filing():
    d = generate_decision("LATE_FILING", original_period="2023-10", gstr_period="2024-01", late_months=3)
    assert "2023-10" in d.what
    assert "2024-01" in d.what
    assert "3 months" in d.what
    assert "late" in d.why
    assert "GSTR-2B" in d.next


def test_populate_decisions_attaches_fields():
    rows = [
        {"match_level": 1, "supplier_gstin": "27AABCU9603R1ZX"},
        {"match_level": 2, "amount_difference_paise": 15000, "source_software": "Tally"},
        {"is_missed_itc": True, "source_software": "Busy", "total_tax_paise": 1800000},
    ]
    result = populate_decisions(rows)
    for row in result["rows"]:
        assert "decision_what" in row
        assert "decision_why" in row
        assert "decision_next" in row
        assert row["decision_what"] != ""
        assert row["decision_next"] != ""


def test_l2_fuzzy_decision_what_uses_taxable_diff_paise_not_hardcoded_zero():
    """FUZZY (match_level=2) WHAT IS WRONG must interpolate the real taxable
    delta. Reading only ``amount_difference_paise`` (often absent on clean
    matched rows) previously hard-defaulted to ₹0.00 for every FUZZY export.
    """
    from app.decisions.layer import _decision_for_row

    # Engine stores taxable_diff_paise; amount_difference_paise intentionally omitted.
    row = {
        "match_level": 2,
        "taxable_diff_paise": 12_345_00,  # ₹12,345.00
        "source_software": "Tally",
        "supplier_gstin": "27AABCU9603R1ZX",
    }
    d = _decision_for_row(row)
    assert d.rule == "L2_AMOUNT_DIFF"
    assert "₹12,345.00" in d.what, f"expected real delta in decision_what, got {d.what!r}"
    assert "₹0.00" not in d.what


def test_l2_fuzzy_zero_diff_uses_normalized_template_not_amount_differs_zero():
    """Path B: clean-matched L2 with real taxable delta 0 must NOT say
    \"amount differs by ₹0.00\". That string is reserved for a genuine delta;
    zero-discrepancy format-variant matches use L2_NORMALIZED instead.
    """
    from app.decisions.layer import _decision_for_row

    row = {
        "match_level": 2,
        "taxable_diff_paise": 0,
        "source_software": "Tally",
        "supplier_gstin": "27AABCU9603R1ZX",
        "gstr_invoice_number": "GST/0001/26",
        "pr_invoice_number": "GST126",
    }
    d = _decision_for_row(row)
    assert d.rule == "L2_NORMALIZED", f"expected L2_NORMALIZED, got {d.rule!r}"
    assert "amount differs" not in d.what.lower()
    assert "₹0.00" not in d.what
    assert "Normalized invoice match" in d.what
    assert "GST/0001/26" in d.what and "GST126" in d.what
    assert "invoice_number" in d.differed_fields


def test_l2_fuzzy_decision_what_from_live_taxable_pair():
    """When only gstr/pr taxable paise are present, compute abs(g − p)."""
    from app.decisions.layer import _decision_for_row

    row = {
        "match_level": 2,
        "gstr_taxable_amount_paise": 100_000_00,  # ₹1,00,000.00
        "pr_taxable_amount_paise": 97_500_00,  # ₹97,500.00 → delta ₹2,500.00
        "source_software": "Tally",
    }
    d = _decision_for_row(row)
    assert "₹2,500.00" in d.what, f"expected ₹2,500.00 in decision_what, got {d.what!r}"
