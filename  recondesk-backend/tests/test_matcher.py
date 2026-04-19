import uuid

from app.services.matcher import match_gstr_to_pr

# Valid 15-char GSTINs (normalized uppercase)
GSTIN_MH = "27AABCU9603R1ZX"
GSTIN_KA = "29ABCDE1234F1Z5"
GSTIN_TN = "33AABCG1254E1Z3"


def _base_rec(
    *,
    supplier_gstin=GSTIN_MH,
    invoice_number="INV202425001",
    invoice_date="2024-07-15",
    taxable_paise=10_000_000,
):
    """taxable_paise: Rs 1,00,000.00 = 10_000_000 paise"""
    tid = str(uuid.uuid4())
    return {
        "id": tid,
        "supplier_gstin": supplier_gstin,
        "invoice_number_normalized": invoice_number,
        "invoice_date": invoice_date,
        "taxable_amount_paise": taxable_paise,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": 0,
        "total_tax_paise": 0,
    }


# --- L1 (4) ---


def test_l1_exact_match_all_fields():
    g = _base_rec()
    p = _base_rec(supplier_gstin=g["supplier_gstin"])
    r = match_gstr_to_pr(g, p)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_amount_at_upper_boundary_rs1_tolerance():
    g = _base_rec(taxable_paise=10_000_000)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=10_000_000 - 100,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_inside_tolerance_amount_99_paise_date_3_days():
    g = _base_rec(invoice_date="2024-04-01", taxable_paise=5_000_000)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-04-04",
        taxable_paise=5_000_000 - 99,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_l1_outside_amount_101_paise_becomes_l2():
    g = _base_rec(invoice_date="2024-05-10", taxable_paise=8_888_888)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=8_888_888 - 101,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


# --- L2 (4) ---


def test_l2_near_amount_difference_inside_l2_tolerance():
    g = _base_rec(
        invoice_number="B2BINV202425089",
        taxable_paise=12_345_678,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=12_345_678 - 5_432,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_near_date_four_days_invoice_matches():
    g = _base_rec(invoice_date="2024-08-01", invoice_number="CRN2024255001")
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-08-05",
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_both_near_amount_and_date():
    g = _base_rec(
        invoice_date="2024-09-10",
        invoice_number="DLINV2024/25/0142",
        taxable_paise=3_333_333,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-09-16",
        taxable_paise=3_333_333 - 8_000,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


def test_l2_boundary_amount_10000_paise_and_date_7_days():
    g = _base_rec(
        invoice_date="2024-01-01",
        invoice_number="BNK2024259001",
        taxable_paise=7_000_000,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date="2024-01-08",
        taxable_paise=7_000_000 - 10_000,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 2
    assert r.matched is True
    assert r.confidence == 90
    assert r.requires_human_review is False


# --- L3 (4) ---


def test_l3_diff_just_over_l2_within_five_percent():
    # Absolute > Rs1; relative in (1%, 5%] — not capturable by L2 (≤1% relative)
    base = 20_000_000
    diff = 500_000
    g = _base_rec(
        invoice_number="CHSINV/2024-25/0088",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


def test_l3_amount_at_4_9_percent():
    base = 1_000_000_00
    diff = int(round(0.049 * base))
    assert diff > 10_000
    g = _base_rec(
        invoice_number="HYDINV2024251200",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


def test_l3_amount_at_5_1_percent_fails_to_l6():
    base = 1_000_000_00
    diff = int(round(0.051 * base))
    g = _base_rec(
        invoice_number="PUNEINV2024253400",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 6
    assert r.matched is False
    assert r.confidence == 0
    assert r.requires_human_review is False


def test_l3_missing_date_on_pr_skips_date_and_matches_l3():
    base = 8_000_000
    diff = 100_000
    g = _base_rec(
        invoice_number="GNVINV/2024/0777",
        invoice_date="2024-03-20",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=base - diff,
    )
    del p["invoice_date"]
    r = match_gstr_to_pr(g, p)
    assert r.level == 3
    assert r.matched is True
    assert r.confidence == 75
    assert r.requires_human_review is True


# --- L4 (4) ---


def test_l4_invoice_typo_different_suffix():
    d = "2024-06-20"
    amt = 15_151_515
    g = _base_rec(
        invoice_number="MEERUTINV202425001",
        invoice_date=d,
        taxable_paise=amt,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="MEERUTINV202425002",
        invoice_date=d,
        taxable_paise=amt,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_invoice_prefix_branch_vs_parent():
    g = _base_rec(
        invoice_number="BHI/N/2024-25/001",
        invoice_date="2024-07-01",
        taxable_paise=4_200_000,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="BHI/P/2024-25/001",
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_same_taxable_different_invoice_number():
    amt = 22_222_222
    day = "2024-11-11"
    g = _base_rec(
        invoice_number="KOCHI2024257788",
        invoice_date=day,
        taxable_paise=amt,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="KOCHI2024257789",
        invoice_date=day,
        taxable_paise=amt,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


def test_l4_financial_year_marker_differs():
    g = _base_rec(
        invoice_number="IND/24-25/999",
        invoice_date="2024-12-31",
        taxable_paise=9_999_999,
    )
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number="IND/25-26/999",
        invoice_date=g["invoice_date"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 4
    assert r.matched is True
    assert r.confidence == 50
    assert r.requires_human_review is True


# --- L5 (4) ---


def test_l5_exactly_30_day_difference():
    g = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202401001",
        invoice_date="2024-01-01",
        taxable_paise=50_000_000_00,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202402001",
        invoice_date="2024-01-31",
        taxable_paise=49_000_000_00,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 5
    assert r.matched is True
    assert r.confidence == 30
    assert r.requires_human_review is True


def test_l5_31_days_becomes_l6():
    g = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202401100",
        invoice_date="2024-01-01",
        taxable_paise=50_000_000_00,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="BLRVINV202402200",
        invoice_date="2024-02-01",
        taxable_paise=49_000_000_00,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 6
    assert r.matched is False
    assert r.confidence == 0
    assert r.requires_human_review is False


def test_l5_amount_within_4_9_percent_invoice_mismatch():
    base = 80_000_000_00
    diff = int(round(0.049 * base))
    g = _base_rec(
        supplier_gstin=GSTIN_TN,
        invoice_number="CHN202425AA100",
        taxable_paise=base,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_TN,
        invoice_number="CHN202425AA200",
        taxable_paise=base - diff,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 5
    assert r.matched is True
    assert r.confidence == 30
    assert r.requires_human_review is True


def test_l5_weak_match_supplier_only_moderate_date_diff():
    g = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="NAGPUR202425001",
        invoice_date="2024-02-10",
        taxable_paise=40_000_000_00,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="NAGPUR202425999",
        invoice_date="2024-03-01",
        taxable_paise=39_200_000_00,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 5
    assert r.matched is True
    assert r.confidence == 30
    assert r.requires_human_review is True


# --- L6 (3) ---


def test_l6_completely_different_records():
    g = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number="AAA202401",
        invoice_date="2024-01-15",
        taxable_paise=1_000_000,
    )
    p = _base_rec(
        supplier_gstin=GSTIN_KA,
        invoice_number="ZZZ202499",
        invoice_date="2024-09-20",
        taxable_paise=99_999_999,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 6
    assert r.matched is False
    assert r.confidence == 0
    assert r.requires_human_review is False


def test_l6_missing_gstin_on_gstr():
    g = _base_rec(supplier_gstin="")
    p = _base_rec(
        supplier_gstin=GSTIN_MH,
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=g["taxable_amount_paise"],
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 6
    assert r.matched is False
    assert r.confidence == 0
    assert r.requires_human_review is False


def test_l6_empty_invoice_both_sides_different_gstin():
    g = _base_rec(supplier_gstin=GSTIN_MH, invoice_number="")
    p = _base_rec(supplier_gstin=GSTIN_TN, invoice_number="")
    r = match_gstr_to_pr(g, p)
    assert r.level == 6
    assert r.matched is False
    assert r.confidence == 0
    assert r.requires_human_review is False


# --- Edge (2) ---


def test_edge_missing_invoice_date_both_skips_date_l1_match():
    g = _base_rec()
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        taxable_paise=g["taxable_amount_paise"],
    )
    del g["invoice_date"]
    del p["invoice_date"]
    r = match_gstr_to_pr(g, p)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False


def test_edge_both_taxable_zero_identical():
    g = _base_rec(taxable_paise=0)
    p = _base_rec(
        supplier_gstin=g["supplier_gstin"],
        invoice_number=g["invoice_number_normalized"],
        invoice_date=g["invoice_date"],
        taxable_paise=0,
    )
    r = match_gstr_to_pr(g, p)
    assert r.level == 1
    assert r.matched is True
    assert r.confidence == 100
    assert r.requires_human_review is False
