import pytest
from app.services.matcher import are_document_types_compatible, _match_gstr_to_pr_pair
from app.matching.engine import run_bidirectional_reconciliation
from app.services.amendment_handler import build_effective_gstr_records


def test_cdn_01_gstr_cn_pr_cn_clean_match():
    """GSTR CDNR (Credit Note) matches exact PR Credit Note (clean Level 1)."""
    gstr_records = [
        {
            "id": "gstr_cn_1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CRN-2023-001",
            "invoice_number_normalized": "CRN2023001",
            "invoice_date": "2023-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "table_name": "cdnr",
        }
    ]
    pr_records = [
        {
            "id": "pr_cn_1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CRN-2023-001",
            "invoice_number_normalized": "CRN2023001",
            "invoice_date": "2023-09-15",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]

    result = run_bidirectional_reconciliation(
        gstr_records=gstr_records,
        pr_records=pr_records,
        gstr_period="092023",
    )

    clean_matches = result["matched"]
    assert len(clean_matches) == 1
    m = clean_matches[0]
    assert m["gstr_id"] == "gstr_cn_1"
    assert m["pr_id"] == "pr_cn_1"
    assert m["doc_type"] == "CREDIT_NOTE"
    assert m["is_credit_note"] is True
    assert m["match_level"] == 1
    assert len(result["unmatched_notes"]) == 0
    assert len(result["missed_itc"]) == 0


def test_cdn_02_gstr_cn_pr_cn_negative_magnitude_match():
    """GSTR CDNR (+10,000) matches PR Credit Note with negative accounting sign (-10,000)."""
    gstr_records = [
        {
            "id": "gstr_cn_2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-900",
            "invoice_number_normalized": "CN900",
            "invoice_date": "2023-09-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "cgst_paise": 90000,
            "sgst_paise": 90000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
        }
    ]
    # In many ERPs (SAP/Tally), credit notes are represented as negative amounts
    pr_records = [
        {
            "id": "pr_cn_2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-900",
            "invoice_number_normalized": "CN900",
            "invoice_date": "2023-09-10",
            "taxable_amount_paise": -1000000,
            "total_tax_paise": -180000,
            "cgst_paise": -90000,
            "sgst_paise": -90000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]

    result = run_bidirectional_reconciliation(
        gstr_records=gstr_records,
        pr_records=pr_records,
        gstr_period="092023",
    )

    clean_matches = result["matched"]
    assert len(clean_matches) == 1
    m = clean_matches[0]
    assert m["taxable_diff_paise"] == 0
    assert m["amount_difference_paise"] == 0
    assert len(result["unmatched_notes"]) == 0


def test_cdn_03_gstr_cn_pr_purchase_return_buyer_debit_note():
    """GSTR CDNR matches PR recorded as Buyer Debit Note / Purchase Return (negative taxable amount)."""
    gstr_records = [
        {
            "id": "gstr_cn_3",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "PR-RET-101",
            "invoice_number_normalized": "PRRET101",
            "invoice_date": "2023-09-12",
            "taxable_amount_paise": 500000,
            "total_tax_paise": 90000,
            "doc_type": "CREDIT_NOTE",
        }
    ]
    pr_records = [
        {
            "id": "pr_dn_return",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "PR-RET-101",
            "invoice_number_normalized": "PRRET101",
            "invoice_date": "2023-09-12",
            "taxable_amount_paise": -500000,
            "total_tax_paise": -90000,
            "doc_type": "DEBIT_NOTE",  # Buyer's debit note for purchase return
            "pr_note_quarantine": True,
        }
    ]

    compat, reason = are_document_types_compatible(gstr_records[0], pr_records[0])
    assert compat is True
    assert reason in ("COMPATIBLE_CREDIT_NOTE", "COMPATIBLE_BUYER_RETURN_DEBIT_NOTE")

    result = run_bidirectional_reconciliation(
        gstr_records=gstr_records,
        pr_records=pr_records,
        gstr_period="092023",
    )
    assert len(result["matched"]) == 1
    assert result["matched"][0]["pr_id"] == "pr_dn_return"


def test_cdn_04_gstr_dn_pr_debit_note_clean_match():
    """GSTR CDNR (Debit Note) matches PR Debit Note (positive supplementary charge)."""
    gstr_records = [
        {
            "id": "gstr_dn_4",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "DN-500",
            "invoice_number_normalized": "DN500",
            "invoice_date": "2023-09-20",
            "taxable_amount_paise": 200000,
            "total_tax_paise": 36000,
            "cgst_paise": 18000,
            "sgst_paise": 18000,
            "igst_paise": 0,
            "doc_type": "DEBIT_NOTE",
        }
    ]
    pr_records = [
        {
            "id": "pr_dn_4",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "DN-500",
            "invoice_number_normalized": "DN500",
            "invoice_date": "2023-09-20",
            "taxable_amount_paise": 200000,
            "total_tax_paise": 36000,
            "cgst_paise": 18000,
            "sgst_paise": 18000,
            "igst_paise": 0,
            "doc_type": "DEBIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]

    compat, reason = are_document_types_compatible(gstr_records[0], pr_records[0])
    assert compat is True
    assert reason == "COMPATIBLE_DEBIT_NOTE"

    result = run_bidirectional_reconciliation(
        gstr_records=gstr_records,
        pr_records=pr_records,
        gstr_period="092023",
    )
    assert len(result["matched"]) == 1
    assert result["matched"][0]["doc_type"] == "DEBIT_NOTE"


def test_cdn_05_gstr_cn_vs_normal_pr_invoice_rejected():
    """GSTR Credit Note and normal PR Invoice with same number and amount MUST be rejected."""
    gstr_cn = {
        "id": "gstr_cn_5",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    pr_inv = {
        "id": "pr_inv_5",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-100",
        "invoice_number_normalized": "INV100",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "INVOICE",
    }

    compat, reason = are_document_types_compatible(gstr_cn, pr_inv)
    assert compat is False
    assert reason == "CROSS_DOCUMENT_TYPE_REJECTED"

    match_res = _match_gstr_to_pr_pair(gstr_cn, pr_inv)
    assert match_res.matched is False

    result = run_bidirectional_reconciliation(
        gstr_records=[gstr_cn],
        pr_records=[pr_inv],
        gstr_period="092023",
    )
    assert len(result["matched"]) == 0
    assert len(result["review_required"]) == 0
    # GSTR CN lands in missed_itc with credit note tags
    assert len(result["missed_itc"]) == 1
    assert result["missed_itc"][0]["is_credit_note"] is True
    # PR Invoice lands in wrongful_itc_risk (ITC at Risk)
    assert len(result["wrongful_itc_risk"]) == 1


def test_cdn_06_gstr_dn_vs_normal_pr_invoice_rejected():
    """GSTR Debit Note and normal PR Invoice with same number/amount MUST be rejected."""
    gstr_dn = {
        "id": "gstr_dn_6",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-200",
        "invoice_number_normalized": "INV200",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "DEBIT_NOTE",
    }
    pr_inv = {
        "id": "pr_inv_6",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "INV-200",
        "invoice_number_normalized": "INV200",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "INVOICE",
    }

    compat, reason = are_document_types_compatible(gstr_dn, pr_inv)
    assert compat is False
    assert reason == "CROSS_DOCUMENT_TYPE_REJECTED"


def test_cdn_07_magnitude_match_across_signs():
    """Candidate generation and diff calculation match across opposite signs."""
    gstr_cn = {
        "id": "g_7",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-777",
        "invoice_number_normalized": "CN777",
        "invoice_date": "2023-09-05",
        "taxable_amount_paise": 50000000,  # 5,00,000 Rs
        "total_tax_paise": 9000000,
        "cgst_paise": 4500000,
        "sgst_paise": 4500000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_7",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-777",
        "invoice_number_normalized": "CN777",
        "invoice_date": "2023-09-05",
        "taxable_amount_paise": -50000000,  # -5,00,000 Rs
        "total_tax_paise": -9000000,
        "cgst_paise": -4500000,
        "sgst_paise": -4500000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn], "092023")
    assert len(res["matched"]) == 1
    assert res["matched"][0]["taxable_diff_paise"] == 0


def test_cdn_08_same_gstin_same_amt_diff_note_no_no_match():
    """Same GSTIN, same amount, but completely different note numbers do not auto-clean match."""
    gstr_cn = {
        "id": "g_8",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-001",
        "invoice_number_normalized": "CN001",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_8",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-999",
        "invoice_number_normalized": "CN999",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn], "092023")
    # Must NOT be clean matched
    assert len(res["matched"]) == 0


def test_cdn_09_fuzzy_note_typo_review_required_never_clean():
    """Typo in note number (CRN-8812 vs CRN-8813) must land in REVIEW_REQUIRED, NEVER clean."""
    gstr_cn = {
        "id": "g_9",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CRN-8812",
        "invoice_number_normalized": "CRN8812",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 500000,
        "total_tax_paise": 90000,
        "cgst_paise": 45000,
        "sgst_paise": 45000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_9",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CRN-8813",
        "invoice_number_normalized": "CRN8813",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 500000,
        "total_tax_paise": 90000,
        "cgst_paise": 45000,
        "sgst_paise": 45000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn], "092023")
    # Clean matches must be ZERO
    assert len(res["matched"]) == 0
    # Review required should capture the typo match
    assert len(res["review_required"]) == 1
    rr = res["review_required"][0]
    assert rr["doc_type"] == "CREDIT_NOTE"
    assert rr["is_credit_note"] is True
    assert rr["review_reason"] == "TYPO_MISMATCH"


def test_cdn_10_format_variant_note_number():
    """Delimiter and prefix variations normalize and clean match."""
    gstr_cn = {
        "id": "g_10",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN/2023-24/001",
        "invoice_number_normalized": "CN202324001",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 200000,
        "total_tax_paise": 36000,
        "cgst_paise": 18000,
        "sgst_paise": 18000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_10",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-2023-24-001",
        "invoice_number_normalized": "CN202324001",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 200000,
        "total_tax_paise": 36000,
        "cgst_paise": 18000,
        "sgst_paise": 18000,
        "igst_paise": 0,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn], "092023")
    assert len(res["matched"]) == 1


def test_cdn_11_same_note_diff_supplier_rejected():
    """Identical note number & amount across two different suppliers must not match."""
    gstr_cn = {
        "id": "g_11",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-100",
        "invoice_number_normalized": "CN100",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_11",
        "supplier_gstin": "29XYZPA1234F1Z5",  # completely different GSTIN
        "invoice_number": "CN-100",
        "invoice_number_normalized": "CN100",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn], "092023")
    assert len(res["matched"]) == 0
    assert len(res["review_required"]) == 1
    assert res["review_required"][0]["review_reason"] == "GSTIN_MISMATCH"


def test_cdn_12_duplicate_pr_note_bookings():
    """Two PR credit notes with the same note number are flagged as duplicates."""
    gstr_cn = {
        "id": "g_12",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-1",
        "invoice_number_normalized": "CNDUP1",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn_a = {
        "id": "p_12a",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-1",
        "invoice_number_normalized": "CNDUP1",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    pr_cn_b = {
        "id": "p_12b",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-1",
        "invoice_number_normalized": "CNDUP1",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn], [pr_cn_a, pr_cn_b], "092023")
    assert len(res["matched"]) == 1
    assert len(res["duplicate_entries"]) >= 1
    assert len(res["wrongful_itc_risk"]) == 0


def test_cdn_13_duplicate_gstr_cdnr_rows():
    """Two identical GSTR CDNR rows are caught by duplicate ambiguity."""
    gstr_cn_a = {
        "id": "g_13a",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-G",
        "invoice_number_normalized": "CNDUPG",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    gstr_cn_b = {
        "id": "g_13b",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-G",
        "invoice_number_normalized": "CNDUPG",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
    }
    pr_cn = {
        "id": "p_13",
        "supplier_gstin": "27AABCU9603R1ZM",
        "invoice_number": "CN-DUP-G",
        "invoice_number_normalized": "CNDUPG",
        "invoice_date": "2023-09-01",
        "taxable_amount_paise": 100000,
        "total_tax_paise": 18000,
        "doc_type": "CREDIT_NOTE",
        "pr_note_quarantine": True,
    }
    res = run_bidirectional_reconciliation([gstr_cn_a, gstr_cn_b], [pr_cn], "092023")
    assert len(res["matched"]) == 0
    assert len(res["review_required"]) >= 2
    assert all("DUPLICATE_AMBIGUITY" in r["review_reason"] for r in res["review_required"])


def test_cdn_14_cdnra_note_renumbering():
    """CDNR original renumbered via CDNRA matches PR note carrying the amended number."""
    raw_gstr = [
        {
            "id": "cdnr_orig",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-OLD-01",
            "invoice_number_normalized": "CNOLD01",
            "invoice_date": "2023-08-10",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": False,
        },
        {
            "id": "cdnra_amend",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-NEW-01",
            "invoice_number_normalized": "CNNEW01",
            "invoice_date": "2023-09-12",
            "original_invoice_number": "CN-OLD-01",
            "original_invoice_number_normalized": "CNOLD01",
            "original_invoice_date": "2023-08-10",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": True,
            "amendment_type": "cdnra",
        },
    ]
    effective = build_effective_gstr_records(raw_gstr).effective_records
    assert len(effective) == 1
    assert effective[0]["id"] == "cdnra_amend"

    pr_records = [
        {
            "id": "pr_renumbered",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-NEW-01",
            "invoice_number_normalized": "CNNEW01",
            "invoice_date": "2023-09-12",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "cgst_paise": 9000,
            "sgst_paise": 9000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]
    res = run_bidirectional_reconciliation(effective, pr_records, "092023")
    assert len(res["matched"]) == 1
    assert res["matched"][0]["gstr_id"] == "cdnra_amend"
    assert res["matched"][0]["pr_id"] == "pr_renumbered"


def test_cdn_15_cdnra_note_amount_revision():
    """CDNR original amount revised via CDNRA matches PR updated note amount."""
    raw_gstr = [
        {
            "id": "cdnr_orig_amt",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-REV-50",
            "invoice_number_normalized": "CNREV50",
            "invoice_date": "2023-08-10",
            "taxable_amount_paise": 5000000,  # 50,000 Rs
            "total_tax_paise": 900000,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": False,
        },
        {
            "id": "cdnra_amend_amt",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-REV-50",
            "invoice_number_normalized": "CNREV50",
            "invoice_date": "2023-09-12",
            "original_invoice_number": "CN-REV-50",
            "original_invoice_number_normalized": "CNREV50",
            "original_invoice_date": "2023-08-10",
            "taxable_amount_paise": 7000000,  # revised to 70,000 Rs
            "total_tax_paise": 1260000,
            "cgst_paise": 630000,
            "sgst_paise": 630000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": True,
            "amendment_type": "cdnra",
        },
    ]
    effective = build_effective_gstr_records(raw_gstr).effective_records
    assert len(effective) == 1
    assert effective[0]["taxable_amount_paise"] == 7000000

    pr_records = [
        {
            "id": "pr_rev_70",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-REV-50",
            "invoice_number_normalized": "CNREV50",
            "invoice_date": "2023-09-12",
            "taxable_amount_paise": 7000000,
            "total_tax_paise": 1260000,
            "cgst_paise": 630000,
            "sgst_paise": 630000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]
    res = run_bidirectional_reconciliation(effective, pr_records, "092023")
    assert len(res["matched"]) == 1
    assert res["matched"][0]["gstr_id"] == "cdnra_amend_amt"


def test_cdn_16_multihop_cdnra_chain():
    """Multi-hop amendment: Original CDNR -> CDNRA 1 -> CDNRA 2."""
    raw_gstr = [
        {
            "id": "cdnr_v0",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-M-01",
            "invoice_number_normalized": "CNM01",
            "invoice_date": "2023-07-01",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": False,
        },
        {
            "id": "cdnra_v1",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-M-02",
            "invoice_number_normalized": "CNM02",
            "invoice_date": "2023-08-01",
            "original_invoice_number": "CN-M-01",
            "original_invoice_number_normalized": "CNM01",
            "original_invoice_date": "2023-07-01",
            "taxable_amount_paise": 1200000,
            "total_tax_paise": 216000,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": True,
        },
        {
            "id": "cdnra_v2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-M-03",
            "invoice_number_normalized": "CNM03",
            "invoice_date": "2023-09-01",
            "original_invoice_number": "CN-M-02",
            "original_invoice_number_normalized": "CNM02",
            "original_invoice_date": "2023-08-01",
            "taxable_amount_paise": 1500000,
            "total_tax_paise": 270000,
            "cgst_paise": 135000,
            "sgst_paise": 135000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "is_amendment": True,
        },
    ]
    effective = build_effective_gstr_records(raw_gstr).effective_records
    assert len(effective) == 1
    assert effective[0]["id"] == "cdnra_v2"
    assert effective[0]["invoice_number"] == "CN-M-03"

    pr_records = [
        {
            "id": "pr_v2",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-M-03",
            "invoice_number_normalized": "CNM03",
            "invoice_date": "2023-09-01",
            "taxable_amount_paise": 1500000,
            "total_tax_paise": 270000,
            "cgst_paise": 135000,
            "sgst_paise": 135000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]
    res = run_bidirectional_reconciliation(effective, pr_records, "092023")
    assert len(res["matched"]) == 1
    assert res["matched"][0]["gstr_id"] == "cdnra_v2"


def test_cdn_17_cross_period_note():
    """CDNR in 092023 referencing original invoice from 042023 reconciles correctly."""
    gstr_records = [
        {
            "id": "gstr_cross_period",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-CROSS-01",
            "invoice_number_normalized": "CNCROSS01",
            "invoice_date": "2023-09-15",
            "taxable_amount_paise": 800000,
            "total_tax_paise": 144000,
            "cgst_paise": 72000,
            "sgst_paise": 72000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "original_invoice_number": "INV-APR-001",
            "original_invoice_date": "2023-04-10",
        }
    ]
    pr_records = [
        {
            "id": "pr_cross_period",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-CROSS-01",
            "invoice_number_normalized": "CNCROSS01",
            "invoice_date": "2023-09-15",
            "taxable_amount_paise": 800000,
            "total_tax_paise": 144000,
            "cgst_paise": 72000,
            "sgst_paise": 72000,
            "igst_paise": 0,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records, "092023")
    assert len(res["matched"]) == 1
    assert res["matched"][0]["gstr_id"] == "gstr_cross_period"


def test_cdn_18_unmatched_gstr_credit_note_tagged():
    """Unmatched GSTR Credit Note in missed_itc carries explicit reversal tags."""
    gstr_records = [
        {
            "id": "gstr_unmatched_cn",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-UNMATCHED-99",
            "invoice_number_normalized": "CNUNMATCHED99",
            "invoice_date": "2023-09-25",
            "taxable_amount_paise": 500000,
            "total_tax_paise": 90000,
            "doc_type": "CREDIT_NOTE",
        }
    ]
    res = run_bidirectional_reconciliation(gstr_records, [], "092023")
    assert len(res["missed_itc"]) == 1
    entry = res["missed_itc"][0]
    assert entry["gstr_id"] == "gstr_unmatched_cn"
    assert entry["doc_type"] == "CREDIT_NOTE"
    assert entry["is_credit_note"] is True
    assert entry["note_kind"] == "CREDIT_NOTE"
    assert entry["mismatch_reason"] == "UNBOOKED_CREDIT_NOTE_ITC_REDUCTION_PENDING"
    assert entry["requires_reversal"] is True


def test_cdn_19_unmatched_pr_note_residual_quarantine():
    """Unmatched PR Credit Note in residual quarantine lands in unmatched_notes and NOT itc_at_risk."""
    pr_records = [
        {
            "id": "pr_unmatched_note",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-PR-ONLY-1",
            "invoice_number_normalized": "CNPRONLY1",
            "invoice_date": "2023-09-25",
            "taxable_amount_paise": 400000,
            "total_tax_paise": 72000,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        }
    ]
    res = run_bidirectional_reconciliation([], pr_records, "092023")
    assert len(res["unmatched_notes"]) == 1
    note = res["unmatched_notes"][0]
    assert note["id"] == "pr_unmatched_note"
    assert note["side"] == "PR"
    assert note["reason"] == "PR_CREDIT_NOTE_UNMATCHED_IN_2B"
    assert len(res["wrongful_itc_risk"]) == 0


def test_cdn_20_ambiguous_multiple_pr_candidates():
    """Single GSTR note matching multiple identical PR notes is flagged as duplicate/ambiguous."""
    gstr_records = [
        {
            "id": "g_20",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-AMBIG-1",
            "invoice_number_normalized": "CNAMBIG1",
            "invoice_date": "2023-09-01",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "doc_type": "CREDIT_NOTE",
        }
    ]
    pr_records = [
        {
            "id": "p_20a",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-AMBIG-1",
            "invoice_number_normalized": "CNAMBIG1",
            "invoice_date": "2023-09-01",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        },
        {
            "id": "p_20b",
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-AMBIG-1",
            "invoice_number_normalized": "CNAMBIG1",
            "invoice_date": "2023-09-01",
            "taxable_amount_paise": 100000,
            "total_tax_paise": 18000,
            "doc_type": "CREDIT_NOTE",
            "pr_note_quarantine": True,
        },
    ]
    res = run_bidirectional_reconciliation(gstr_records, pr_records, "092023")
    assert len(res["matched"]) == 1
    assert len(res["duplicate_entries"]) >= 1
    assert len(res["wrongful_itc_risk"]) == 0
