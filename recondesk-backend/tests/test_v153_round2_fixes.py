"""Production regression test suite for ReconDesk v1.5.3 Round 2 Fixes.

Covers:
- Defect 1: Document Nature parsing, alias variations, normalization, sign preservation,
            and safe rejection of unknown/ambiguous document types.
- Defect 2: Branch suffix duplicate classification guards, genuine duplicate preservation,
            competing branch invoice routing, and safety against false automatic matches.
- Defect 3: Gross value discrepancy disclosure across match levels, Match Rationale drawer,
            decision texts, and Excel exports.
"""
import datetime
import io
import openpyxl
import pytest

from app.parsers.purchase_register_parser import (
    parse_purchase_register,
    _classify_invoice_type,
)
from app.services.matcher import (
    match_gstr_to_pr,
    _match_gstr_to_pr_pair,
    are_document_types_compatible,
    is_invoice_format_variant,
    check_is_branch_variant,
    build_compared_fields,
    _extract_branch_suffix,
    _normalize_branch_suffix,
)
from app.services.reconciliation import (
    _same_canonical_invoice_identity,
    flag_fuzzy_duplicates_of_linked_prs,
    ReconState,
)
from app.services.reconcile_export_workbook import (
    _format_match_rationale,
    build_excel_workbook_bytes,
)
from app.matching.engine import run_bidirectional_reconciliation


# ===========================================================================
# Defect 1: Document Nature Parsing & Normalization
# ===========================================================================
class TestDefect1DocumentNatureParsing:
    @pytest.mark.parametrize(
        "header_alias",
        [
            "Document Nature",
            "Doc Nature",
            "Nature of Document",
            "Nature",
            "Document Type",
            "Doc Type",
            "Voucher Type",
        ],
    )
    def test_document_nature_aliases_recognized(self, header_alias: str):
        csv_content = (
            f"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,{header_alias},"
            "Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Cess Amount,Gross Amount\n"
            "29ABAGD1006F2ZY,VENDOR 007,CN/00931/26,2026-09-07,CREDIT_NOTE,"
            "89752.00,0.00,12565.28,12565.28,0.00,114882.56\n"
        ).encode("utf-8")
        result = parse_purchase_register(csv_content, filename="test_pr.csv")
        assert header_alias not in result.get("unmapped_columns", [])
        rec = result["records"][0]
        assert rec["document_type"] == "CREDIT_NOTE"
        assert rec["is_credit_note"] is True
        assert rec["taxable_amount_paise"] == -8975200
        assert rec["total_amount_paise"] == -11488256

    def test_debit_note_amounts_and_signs_preserved_positive(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Cess Amount,Gross Amount\n"
            b"29ABALD1011F1ZR,VENDOR 012,AX/01013/26,2026-09-12,DEBIT_NOTE,"
            b"31874.25,0.00,1912.45,1912.45,0.00,35699.15\n"
        )
        result = parse_purchase_register(csv_content, filename="test_pr.csv")
        assert len(result["records"]) == 1
        rec = result["records"][0]
        assert rec["document_type"] == "DEBIT_NOTE"
        assert rec["is_debit_note"] is True
        assert rec["is_credit_note"] is False
        assert rec["taxable_amount_paise"] == 3187425
        assert rec["total_tax_paise"] == 382490
        assert rec["total_amount_paise"] == 3569915

    def test_invoice_normalization(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Cess Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,VENDOR 001,INV/00100/26,2026-09-01,INVOICE,"
            b"50000.00,9000.00,0.00,0.00,0.00,59000.00\n"
        )
        result = parse_purchase_register(csv_content, filename="test_pr.csv")
        assert len(result["records"]) == 1
        rec = result["records"][0]
        assert rec["document_type"] == "INVOICE"
        assert rec["is_credit_note"] is False
        assert rec["is_debit_note"] is False
        assert rec["taxable_amount_paise"] == 5000000

    def test_reject_unknown_document_type_safely(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Cess Amount,Gross Amount\n"
            b"29ABAGD1006F2ZY,VENDOR 007,INV-001,2026-09-07,PURCHASE_ORDER,"
            b"50000.00,9000.00,0.00,0.00,0.00,59000.00\n"
        )
        result = parse_purchase_register(csv_content, filename="test_pr.csv")
        # Row must be skipped and logged in errors without crashing
        assert len(result["records"]) == 0
        assert any("unknown document type 'PURCHASE_ORDER'" in err for err in result.get("errors", []))

    def test_reject_ambiguous_document_type_safely(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Cess Amount,Gross Amount\n"
            b"29ABAGD1006F2ZY,VENDOR 007,INV-001,2026-09-07,CREDIT_DEBIT_NOTE,"
            b"50000.00,9000.00,0.00,0.00,0.00,59000.00\n"
        )
        result = parse_purchase_register(csv_content, filename="test_pr.csv")
        assert len(result["records"]) == 0
        assert any("ambiguous document type 'CREDIT_DEBIT_NOTE'" in err for err in result.get("errors", []))


# ===========================================================================
# Defect 2: Branch Suffix Duplicate Classification & Routing
# ===========================================================================
class TestDefect2BranchSuffixDuplicateClassification:
    def test_extract_and_normalize_branch_suffix(self):
        assert _extract_branch_suffix("AX45126BR1", "AX/00451/26-BR01") == "BR01"
        assert _extract_branch_suffix("AX45126BR2", "AX/00451/26-BR02") == "BR02"
        assert _extract_branch_suffix("INV100HO", "INV-100/HO") == "HO"
        assert _extract_branch_suffix("INV100", "INV-100") == ""

        assert _normalize_branch_suffix("BR01") == "BR1"
        assert _normalize_branch_suffix("BR1") == "BR1"
        assert _normalize_branch_suffix("BR02") == "BR2"
        assert _normalize_branch_suffix("UNIT02") == "UNIT2"
        assert _normalize_branch_suffix("HO") == "HO"
        assert _normalize_branch_suffix("") == ""

    def test_distinct_branches_rejected_from_canonical_identity(self):
        raw_a = "AX/00451/26-BR01"
        raw_b = "AX/00451/26-BR02"
        norm_a = "AX45126BR1"
        norm_b = "AX45126BR2"

        assert _same_canonical_invoice_identity(norm_a, norm_b, raw_a, raw_b) is False
        assert is_invoice_format_variant(norm_a, norm_b, raw_a, raw_b) is False
        assert check_is_branch_variant(norm_a, norm_b, raw_a, raw_b) is False

    def test_same_branch_duplicates_preserved(self):
        raw_1 = "AX/00451/26-BR01"
        raw_2 = "AX/00451/26-BR01"
        norm = "AX45126BR1"

        assert _same_canonical_invoice_identity(norm, norm, raw_1, raw_2) is True

    def test_branch_vs_non_branch_rejected_from_duplicate_pass(self):
        raw_branch = "AX/00451/26-BR01"
        raw_base = "AX/00451/26"
        norm_branch = "AX45126BR1"
        norm_base = "AX45126"

        # In PR duplicate sweep, an unconsumed branch invoice must not be swallowed as a clone of base invoice
        assert _same_canonical_invoice_identity(norm_branch, norm_base, raw_branch, raw_base) is False

    def test_post_match_sweep_does_not_flag_competing_branch(self):
        pr_1 = {
            "id": "pr-br01",
            "supplier_gstin": "07ABBLD1037F1ZM",
            "invoice_number": "AX/00451/26-BR01",
            "invoice_number_normalized": "AX45126BR1",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "invoice_date": "2026-09-08",
            "document_type": "INVOICE",
        }
        pr_2 = {
            "id": "pr-br02",
            "supplier_gstin": "07ABBLD1037F1ZM",
            "invoice_number": "AX/00451/26-BR02",
            "invoice_number_normalized": "AX45126BR2",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
            "invoice_date": "2026-09-08",
            "document_type": "INVOICE",
        }
        state = ReconState()
        state.clean_matched.append({"pr_id": "pr-br01", "gstr_id": "gstr-1"})
        state.consumed_pr_ids.add("pr-br01")

        flagged = flag_fuzzy_duplicates_of_linked_prs(state, [pr_1, pr_2])
        assert flagged == 0
        assert len(state.duplicate_entries) == 0

    def test_end_to_end_branch_competitor_routes_to_compliance_risk_or_review(self):
        gstin = "07ABBLD1037F1ZM"
        gstr_records = [
            {
                "id": "g-1",
                "supplier_gstin": gstin,
                "invoice_number": "AX/00451/26-BR01",
                "invoice_number_raw": "AX/00451/26-BR01",
                "invoice_number_normalized": "AX45126BR1",
                "invoice_date": datetime.date(2026, 9, 8),
                "taxable_amount_paise": 1000000,
                "total_tax_paise": 180000,
                "total_amount_paise": 1180000,
                "doc_type": "INVOICE",
            }
        ]
        pr_records = [
            {
                "id": "p-1",
                "supplier_gstin": gstin,
                "invoice_number": "AX/00451/26-BR01",
                "invoice_number_raw": "AX/00451/26-BR01",
                "invoice_number_normalized": "AX45126BR1",
                "invoice_date": datetime.date(2026, 9, 8),
                "taxable_amount_paise": 1000000,
                "total_tax_paise": 180000,
                "total_amount_paise": 1180000,
                "document_type": "INVOICE",
            },
            {
                "id": "p-2",
                "supplier_gstin": gstin,
                "invoice_number": "AX/00451/26-BR02",
                "invoice_number_raw": "AX/00451/26-BR02",
                "invoice_number_normalized": "AX45126BR2",
                "invoice_date": datetime.date(2026, 9, 8),
                "taxable_amount_paise": 1000000,
                "total_tax_paise": 180000,
                "total_amount_paise": 1180000,
                "document_type": "INVOICE",
            },
        ]
        recon = run_bidirectional_reconciliation(
            gstr_records, pr_records, gstr_period=datetime.date(2026, 9, 1)
        )
        # Competing branch invoices route to review_required with BRANCH_SUFFIX_REVIEW
        assert len(recon.get("review_required", [])) == 1
        assert recon["review_required"][0]["review_reason"] == "BRANCH_SUFFIX_REVIEW"
        # Neither record may be falsely marked as a duplicate
        dup_ids = [d["id"] for d in recon.get("duplicate_entries", [])]
        assert "p-2" not in dup_ids
        assert len(dup_ids) == 0
        # The competing unconsumed PR is retained in wrongful_itc_risk with BRANCH_ALLOCATION_RISK
        risk_ids = [r["id"] for r in recon.get("wrongful_itc_risk", [])]
        assert "p-2" in risk_ids
        p2_risk = next(r for r in recon["wrongful_itc_risk"] if r["id"] == "p-2")
        assert p2_risk.get("risk_reason") == "BRANCH_ALLOCATION_RISK"
        assert "Branch Allocation Risk" in str(p2_risk.get("decision_what"))


# ===========================================================================
# Defect 3: Gross Value Discrepancy Disclosure
# ===========================================================================
class TestDefect3GrossValueDiscrepancyDisclosure:
    def test_level1_exact_match_discloses_gross_amount_drift(self):
        gstr = {
            "supplier_gstin": "24ABAND1013F1ZV",
            "invoice_number": "AX/00739/26",
            "invoice_number_raw": "AX/00739/26",
            "invoice_date": "2026-09-25",
            "taxable_amount_paise": 6831925,
            "total_tax_paise": 1912940,
            "total_amount_paise": 8744865,  # GSTR: Rs 87,448.65
            "doc_type": "INVOICE",
            "supplier_name": "VENDOR 014",
        }
        pr = {
            "supplier_gstin": "24ABAND1013F1ZV",
            "invoice_number": "AX/00739/26",
            "invoice_number_raw": "AX/00739/26",
            "invoice_date": "2026-09-25",
            "taxable_amount_paise": 6831925,
            "total_tax_paise": 1912940,
            "total_amount_paise": 8751865,  # PR: Rs 87,518.65 (Rs 70.00 difference)
            "doc_type": "INVOICE",
            "supplier_name": "VENDOR 014",
        }
        res = match_gstr_to_pr(gstr, [pr])
        assert res is not None
        assert res.level == 1
        assert res.matched is True
        assert res.requires_human_review is False

        # Verify gross variance is surfaced in decisions
        assert "Gross Value differs" in res.decision_what
        assert "diff Rs 70.00" in res.decision_what
        assert "differs by Rs 70.00" in res.decision_why
        assert "GSTR: Rs 87448.65" in res.decision_why
        assert "PR: Rs 87518.65" in res.decision_why
        assert "Section 16(2)(aa)" in res.decision_next

        # Verify compared_fields includes gross_amount with 'differs'
        fields_by_name = {f["field_name"]: f for f in res.compared_fields}
        assert "gross_amount" in fields_by_name
        assert fields_by_name["gross_amount"]["match_type"] == "differs"
        assert "diff: Rs 70.00" in fields_by_name["gross_amount"]["detail"]

        # Verify Match Rationale format
        rationale = _format_match_rationale(res.compared_fields)
        assert "Gross Value: differs" in rationale
        assert "diff: Rs 70.00" in rationale

    def test_level1_zero_gross_diff_states_exact(self):
        gstr = {
            "supplier_gstin": "24ABAND1013F1ZV",
            "invoice_number": "AX/00739/26",
            "invoice_number_raw": "AX/00739/26",
            "invoice_date": "2026-09-25",
            "taxable_amount_paise": 6831925,
            "total_tax_paise": 1912940,
            "total_amount_paise": 8744865,
            "doc_type": "INVOICE",
            "supplier_name": "VENDOR 014",
        }
        pr = dict(gstr)
        res = match_gstr_to_pr(gstr, [pr])
        assert res is not None
        assert res.decision_what == "Exact match found"
        assert res.decision_why == "Invoice number, amount, and date align"
        rationale = _format_match_rationale(res.compared_fields)
        assert "Gross Value: exact" in rationale

    def test_excel_export_matched_sheet_preserves_gross_discrepancy(self):
        matched_pair = (
            {
                "supplier_gstin": "24ABAND1013F1ZV",
                "invoice_number": "AX/00739/26",
                "invoice_date": "2026-09-25",
                "document_type": "INVOICE",
                "amount": 19129.40,
                "match_level": "EXACT",
                "confidence_score": 100,
                "decision_what": "Matched on Taxable & Tax (Gross Value differs: GSTR Rs 87448.65 vs PR Rs 87518.65, diff Rs 70.00)",
                "decision_why": "Taxable and tax amounts align for ITC claim; gross invoice value differs by Rs 70.00",
                "decision_next": "ITC claim is safe under Section 16(2)(aa). Verify commercial terms with supplier.",
                "compared_fields": [
                    {"field_name": "gstin", "match_type": "exact"},
                    {"field_name": "invoice_number", "match_type": "exact"},
                    {"field_name": "taxable_amount", "match_type": "exact"},
                    {"field_name": "tax_amount", "match_type": "exact"},
                    {"field_name": "gross_amount", "match_type": "differs", "detail": "differs (GSTR: Rs 87448.65, PR: Rs 87518.65, diff: Rs 70.00)"},
                    {"field_name": "date", "match_type": "exact"},
                ],
                "gstr2b_data": {"taxable_amount_paise": 6831925, "invoice_value_paise": 8744865},
                "purchase_register_data": {"taxable_amount_paise": 6831925, "total_amount_paise": 8751865},
            },
            None,
        )
        wb_bytes, _ = build_excel_workbook_bytes(
            run_id="test-run-123",
            firm_name="Test CA Firm",
            client_trade_name="Test Client",
            period_raw="092026",
            summary={"total_gstr_records": 1, "gross_matched_count": 1, "clean_matched_count": 1},
            matched_pairs=[matched_pair],
            missed_rows=[],
            risk_rows=[],
            rule37_rows=[],
            section17_rows=[],
            review_required_rows=[],
            generated_at=datetime.datetime(2026, 9, 30),
            generated_by_name="Test Auditor",
        )
        wb = openpyxl.load_workbook(io.BytesIO(wb_bytes), data_only=True)
        ws = wb["Matched Records"]
        row2 = [cell.value for cell in ws[2]]
        what_val = row2[8]  # WHAT IS WRONG (col 9)
        why_val = row2[9]   # WHY (col 10)
        rationale_val = row2[14]  # Match Rationale (col 15)

        assert "Gross Value differs" in str(what_val)
        assert "diff Rs 70.00" in str(what_val)
        assert "differs by Rs 70.00" in str(why_val)
        assert "Gross Value: differs" in str(rationale_val)


# ===========================================================================
# Release Verification: Document Type Edge Cases
# ===========================================================================
class TestDocumentTypeEdgeCases:
    def test_ordinary_invoice_with_credit_in_description_remains_invoice(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Item Description,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,ABC CREDIT CO,INV-001,2026-09-01,Credit card processing terminal fees,"
            b"50000.00,9000.00,0.00,0.00,59000.00\n"
        )
        res = parse_purchase_register(csv_content, "test.csv")
        assert len(res["records"]) == 1
        rec = res["records"][0]
        assert rec["document_type"] == "INVOICE"
        assert rec["is_credit_note"] is False

    def test_missing_document_nature_falls_back_to_invoice(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,VENDOR 1,INV-002,2026-09-01,50000.00,9000.00,0.00,0.00,59000.00\n"
        )
        res = parse_purchase_register(csv_content, "test.csv")
        assert len(res["records"]) == 1
        rec = res["records"][0]
        assert rec["document_type"] == "INVOICE"
        assert rec["is_credit_note"] is False

    def test_unknown_or_conflicting_document_nature_safely_rejected(self):
        csv_unk = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,VENDOR 1,INV-003,2026-09-01,PROFORMA,50000.00,9000.00,0.00,0.00,59000.00\n"
        )
        res_unk = parse_purchase_register(csv_unk, "test.csv")
        assert len(res_unk["records"]) == 0
        assert any("unknown document type 'PROFORMA'" in err for err in res_unk.get("errors", []))

        csv_conf = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,VENDOR 1,INV-003,2026-09-01,CREDIT / DEBIT NOTE,50000.00,9000.00,0.00,0.00,59000.00\n"
        )
        res_conf = parse_purchase_register(csv_conf, "test.csv")
        assert len(res_conf["records"]) == 0
        assert any("ambiguous document type 'CREDIT / DEBIT NOTE'" in err for err in res_conf.get("errors", []))

    def test_negative_credit_note_and_positive_debit_note_amounts(self):
        csv_content = (
            b"Vendor GST No,Party Name,Voucher/Invoice No,Bill Date,Document Nature,"
            b"Assessable Amount,IGST Amount,CGST Amount,SGST Amount,Gross Amount\n"
            b"27ABAAD1000F1ZL,VENDOR 1,CN-001,2026-09-01,CREDIT_NOTE,-50000.00,-9000.00,0.00,0.00,-59000.00\n"
            b"27ABAAD1000F1ZL,VENDOR 1,DN-001,2026-09-01,DEBIT_NOTE,50000.00,9000.00,0.00,0.00,59000.00\n"
        )
        res = parse_purchase_register(csv_content, "test.csv")
        assert len(res["records"]) == 2
        cn, dn = res["records"][0], res["records"][1]
        assert cn["is_credit_note"] is True
        assert cn["taxable_amount_paise"] == -5000000
        assert cn["total_amount_paise"] == -5900000

        assert dn["is_debit_note"] is True
        assert dn["taxable_amount_paise"] == 5000000
        assert dn["total_amount_paise"] == 5900000

    def test_duplicate_notes_quarantined_correctly(self):
        pr_cns = [
            {
                "id": "cn-1",
                "supplier_gstin": "27ABAAD1000F1ZL",
                "invoice_number": "CN-001",
                "invoice_number_normalized": "CN001",
                "taxable_amount_paise": -5000000,
                "total_tax_paise": -900000,
                "document_type": "CREDIT_NOTE",
                "is_credit_note": True,
                "invoice_date": "2026-09-01",
            },
            {
                "id": "cn-2",
                "supplier_gstin": "27ABAAD1000F1ZL",
                "invoice_number": "CN-001",
                "invoice_number_normalized": "CN001",
                "taxable_amount_paise": -5000000,
                "total_tax_paise": -900000,
                "document_type": "CREDIT_NOTE",
                "is_credit_note": True,
                "invoice_date": "2026-09-01",
            },
        ]
        gstr_cn = [
            {
                "id": "gstr-cn-1",
                "supplier_gstin": "27ABAAD1000F1ZL",
                "invoice_number": "CN-001",
                "invoice_number_normalized": "CN001",
                "taxable_amount_paise": -5000000,
                "total_tax_paise": -900000,
                "document_type": "CREDIT_NOTE",
                "doc_type": "CREDIT_NOTE",
                "is_credit_note": True,
                "invoice_date": "2026-09-01",
            }
        ]
        recon = run_bidirectional_reconciliation(gstr_cn, pr_cns, gstr_period="2026-09-01")
        assert len(recon["matched"]) == 1
        assert len(recon["duplicate_entries"]) == 1

    def test_invoice_versus_note_cross_document_rejection(self):
        inv_row = {
            "supplier_gstin": "27ABAAD1000F1ZL",
            "invoice_number": "INV-001",
            "taxable_amount_paise": 5000000,
            "total_tax_paise": 900000,
            "document_type": "INVOICE",
            "doc_type": "INVOICE",
            "is_credit_note": False,
            "is_debit_note": False,
        }
        note_row = {
            "supplier_gstin": "27ABAAD1000F1ZL",
            "invoice_number": "INV-001",
            "taxable_amount_paise": 5000000,
            "total_tax_paise": 900000,
            "document_type": "CREDIT_NOTE",
            "doc_type": "CREDIT_NOTE",
            "is_credit_note": True,
            "is_debit_note": False,
        }
        compat, reason = are_document_types_compatible(inv_row, note_row)
        assert compat is False
        assert reason == "CROSS_DOCUMENT_TYPE_REJECTED"

