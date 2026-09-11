"""GSTR-3B Table 4 Workpaper Excel Export Generator.

Produces a multi-sheet audit workpaper for Chartered Accountants and tax teams:
1. GSTR-3B Table 4 Summary (Portal Grid layout)
2. Table 4A5 / Eligible Domestic Invoices Ledger
3. Table 4B Reversals & Dispositions Ledger
4. External Adjustments (Rules 42/43/38/RCM)
5. Audit Log & Workpaper Certification
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.services.gstr3b_table4_engine import (
    DISCLAIMER_TEXT,
    WORKPAPER_TITLE,
    compile_gstr3b_table4,
    get_table4_drilldown,
    load_table4_adjustments,
    paise_to_rupees,
)

# Colors
_NAVY_HEADER = "1B365D"
_STEEL_BLUE = "2E5B88"
_LIGHT_BG = "F8FAFC"
_BORDER_GRAY = "CBD5E1"
_ZEBRA_BG = "F1F5F9"
_ACCENT_GREEN = "E2EFDA"
_ACCENT_RED = "FCE4D6"
_WHITE = "FFFFFF"

_font_title = Font(name="Calibri", size=14, bold=True, color=_NAVY_HEADER)
_font_subtitle = Font(name="Calibri", size=10, italic=True, color="475569")
_font_header = Font(name="Calibri", size=11, bold=True, color=_WHITE)
_font_section = Font(name="Calibri", size=11, bold=True, color=_NAVY_HEADER)
_font_regular = Font(name="Calibri", size=10, color="1E293B")
_font_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")
_font_disclaimer = Font(name="Calibri", size=9, italic=True, color="64748B")

_fill_header = PatternFill(start_color=_NAVY_HEADER, end_color=_NAVY_HEADER, fill_type="solid")
_fill_section = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")
_fill_total = PatternFill(start_color=_ACCENT_GREEN, end_color=_ACCENT_GREEN, fill_type="solid")
_fill_reversal = PatternFill(start_color=_ACCENT_RED, end_color=_ACCENT_RED, fill_type="solid")
_fill_zebra = PatternFill(start_color=_ZEBRA_BG, end_color=_ZEBRA_BG, fill_type="solid")

_thin_border_side = Side(border_style="thin", color=_BORDER_GRAY)
_border_all = Border(left=_thin_border_side, right=_thin_border_side, top=_thin_border_side, bottom=_thin_border_side)
_border_total = Border(
    left=_thin_border_side,
    right=_thin_border_side,
    top=Side(border_style="thin", color="000000"),
    bottom=Side(border_style="double", color="000000"),
)


def _auto_fit_columns(ws, max_len_cap: int = 50) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = cell.value
            if val is not None:
                lines = str(val).split("\n")
                line_max = max(len(l) for l in lines)
                if line_max > max_len:
                    max_len = line_max
        ws.column_dimensions[col_letter].width = min(max_len_cap, max(max_len + 3, 12))


def generate_table4_excel_workpaper(sb: Any, run_id: str) -> bytes:
    """Generate the complete 5-sheet GSTR-3B Table 4 Workpaper workbook."""
    data = compile_gstr3b_table4(sb, run_id)
    wb = Workbook()

    # -----------------------------------------------------------------------
    # Sheet 1: Table 4 Summary
    # -----------------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "GSTR-3B Table 4 Summary"
    ws1.views.sheetView[0].showGridLines = True

    # Title Block
    ws1["A1"] = WORKPAPER_TITLE
    ws1["A1"].font = _font_title
    ws1["A2"] = f"Client GSTIN: {data.get('client_gstin')} | Tax Period: {data.get('tax_period')} | Status: {data.get('status')}"
    ws1["A2"].font = _font_subtitle
    ws1["A3"] = f"Audit Hash: {data.get('audit_hash') or 'PROVISIONAL DRAFT'}"
    ws1["A3"].font = _font_subtitle

    # Table Header (Row 5)
    headers = [
        "Row Code",
        "Statutory Description",
        "Voucher Count",
        "Integrated Tax (IGST)",
        "Central Tax (CGST)",
        "State/UT Tax (SGST)",
        "Cess",
        "Total Tax (INR)",
    ]
    ws1.append([])
    ws1.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws1.cell(row=5, column=col_idx)
        cell.font = _font_header
        cell.fill = _fill_header
        cell.alignment = Alignment(horizontal="center" if col_idx != 2 else "left", vertical="center")
        cell.border = _border_all

    t4 = data.get("table_4", {})
    sec4a = t4.get("section_4a", {})
    sec4b = t4.get("section_4b", {})
    sec4c = t4.get("section_4c_net_itc", {})
    sec4d = t4.get("section_4d", {})

    def _append_row(ws, code, label, d, is_total=False, is_reversal=False):
        igst = d.get("igst", 0.0)
        cgst = d.get("cgst", 0.0)
        sgst = d.get("sgst", 0.0)
        cess = d.get("cess", 0.0)
        tot = d.get("total_tax", igst + cgst + sgst + cess)
        count = d.get("count", 0)

        row_vals = [code, label, count if count else "—", igst, cgst, sgst, cess, tot]
        ws.append(row_vals)
        cur_row = ws.max_row

        for c_idx in range(1, len(row_vals) + 1):
            c = ws.cell(row=cur_row, column=c_idx)
            c.font = _font_bold if is_total else _font_regular
            c.border = _border_total if is_total else _border_all

            if is_total:
                c.fill = _fill_total
            elif is_reversal:
                c.fill = _fill_reversal

            if c_idx in (1, 3):
                c.alignment = Alignment(horizontal="center")
            elif c_idx >= 4:
                c.alignment = Alignment(horizontal="right")
                c.number_format = "#,##0.00"

    # Section 4(A) Rows
    _append_row(ws1, "4(A)(1)", "Import of Goods (ICEGATE Bill of Entry)", sec4a.get("row_4a1_import_goods", {}))
    _append_row(ws1, "4(A)(2)", "Import of Services", sec4a.get("row_4a2_import_services", {}))
    _append_row(ws1, "4(A)(3)", "Inward supplies liable to reverse charge (other than 1 & 2)", sec4a.get("row_4a3_inward_rcm", {}))
    _append_row(ws1, "4(A)(4)", "Inward supplies from Input Service Distributor (ISD)", sec4a.get("row_4a4_isd", {}))
    _append_row(ws1, "4(A)(5)", "All other ITC (Domestic B2B Inward)", sec4a.get("row_4a5_all_other_itc", {}))
    _append_row(ws1, "4(A)", "(A) Total ITC Available [Sum of 4A1 to 4A5]", sec4a.get("total_4a", {}), is_total=True)

    # Section 4(B) Rows
    _append_row(ws1, "4(B)(1)", "As per rules 38, 42 & 43 and Section 17(5) Blocked Credit", sec4b.get("row_4b1_rule38_42_43_sec175", {}), is_reversal=True)
    _append_row(ws1, "4(B)(2)", "Others (Rule 37 180-days, Rule 37A supplier non-filer)", sec4b.get("row_4b2_others_rule37_37a", {}), is_reversal=True)
    _append_row(ws1, "4(B)", "(B) Total ITC Reversed [4B1 + 4B2]", sec4b.get("total_4b", {}), is_total=True)

    # Section 4(C) Net Row
    _append_row(ws1, "4(C)", "(C) Net ITC Available [4(A) minus 4(B)]", sec4c, is_total=True)

    # Section 4(D) Other Details
    _append_row(ws1, "4(D)(1)", "ITC Reclaimed which was reversed under Table 4(B)(2) in earlier period", sec4d.get("row_4d1_reclaimed", {}))
    _append_row(ws1, "4(D)(2)", "Ineligible ITC under section 16(4) & restricted by Place of Supply", sec4d.get("row_4d2_ineligible_16_4_pos", {}))

    # Disclaimer note at bottom
    ws1.append([])
    ws1.append(["Note:", DISCLAIMER_TEXT])
    ws1.cell(row=ws1.max_row, column=2).font = _font_disclaimer
    _auto_fit_columns(ws1)

    # -----------------------------------------------------------------------
    # Sheet 2: Table 4A5 Domestic Invoices Ledger
    # -----------------------------------------------------------------------
    ws2 = wb.create_sheet(title="Table 4A5 Domestic Invoices")
    ws2.views.sheetView[0].showGridLines = True
    ws2.append([WORKPAPER_TITLE, "Sheet: Table 4(A)(5) Itemized Invoice Ledger"])
    ws2["A1"].font = _font_title
    ws2.append([])

    drill_4a5 = get_table4_drilldown(sb, run_id, "4A5", page=1, limit=5000)
    inv_headers = [
        "Voucher Type",
        "Supplier GSTIN",
        "Supplier Legal/Trade Name",
        "Invoice Number",
        "Invoice Date",
        "Taxable Value (INR)",
        "IGST (INR)",
        "CGST (INR)",
        "SGST (INR)",
        "Cess (INR)",
        "Total Tax (INR)",
        "Statutory Reason / Notes",
        "CA Disposition",
    ]
    ws2.append(inv_headers)
    hdr_row2 = ws2.max_row
    for c_idx in range(1, len(inv_headers) + 1):
        c = ws2.cell(row=hdr_row2, column=c_idx)
        c.font = _font_header
        c.fill = _fill_header
        c.border = _border_all

    for idx, r in enumerate(drill_4a5.get("records", [])):
        row_vals = [
            r.get("doc_type"),
            r.get("supplier_gstin"),
            r.get("supplier_name"),
            r.get("invoice_number"),
            r.get("invoice_date"),
            r.get("taxable_value", 0.0),
            r.get("igst", 0.0),
            r.get("cgst", 0.0),
            r.get("sgst", 0.0),
            r.get("cess", 0.0),
            r.get("total_tax", 0.0),
            r.get("statutory_reason"),
            r.get("disposition"),
        ]
        ws2.append(row_vals)
        curr = ws2.max_row
        for c_idx in range(1, len(row_vals) + 1):
            c = ws2.cell(row=curr, column=c_idx)
            c.font = _font_regular
            c.border = _border_all
            if idx % 2 == 1:
                c.fill = _fill_zebra
            if c_idx in (1, 2, 4, 5):
                c.alignment = Alignment(horizontal="center")
            elif c_idx in (6, 7, 8, 9, 10, 11):
                c.alignment = Alignment(horizontal="right")
                c.number_format = "#,##0.00"

    _auto_fit_columns(ws2)

    # -----------------------------------------------------------------------
    # Sheet 3: Table 4B Reversals & Dispositions
    # -----------------------------------------------------------------------
    ws3 = wb.create_sheet(title="Table 4B Reversals")
    ws3.views.sheetView[0].showGridLines = True
    ws3.append([WORKPAPER_TITLE, "Sheet: Table 4(B) Reversals (Sec 17(5), Rule 37, Rule 37A)"])
    ws3["A1"].font = _font_title
    ws3.append([])

    drill_4b1 = get_table4_drilldown(sb, run_id, "4B1", page=1, limit=5000)
    drill_4b2 = get_table4_drilldown(sb, run_id, "4B2", page=1, limit=5000)
    all_reversals = [
        {"table_row": "4(B)(1)", **item} for item in drill_4b1.get("records", [])
    ] + [
        {"table_row": "4(B)(2)", **item} for item in drill_4b2.get("records", [])
    ]

    rev_headers = [
        "Table 4B Row",
        "Type",
        "Supplier GSTIN",
        "Supplier Name",
        "Invoice / Ref Doc",
        "Date",
        "IGST (INR)",
        "CGST (INR)",
        "SGST (INR)",
        "Cess (INR)",
        "Total Reversal (INR)",
        "Reversal Category / Reason",
        "Audit Disposition",
    ]
    ws3.append(rev_headers)
    hdr_row3 = ws3.max_row
    for c_idx in range(1, len(rev_headers) + 1):
        c = ws3.cell(row=hdr_row3, column=c_idx)
        c.font = _font_header
        c.fill = _fill_header
        c.border = _border_all

    for idx, r in enumerate(all_reversals):
        row_vals = [
            r.get("table_row"),
            r.get("doc_type"),
            r.get("supplier_gstin"),
            r.get("supplier_name"),
            r.get("invoice_number"),
            r.get("invoice_date"),
            r.get("igst", 0.0),
            r.get("cgst", 0.0),
            r.get("sgst", 0.0),
            r.get("cess", 0.0),
            r.get("total_tax", 0.0),
            r.get("statutory_reason"),
            r.get("disposition"),
        ]
        ws3.append(row_vals)
        curr = ws3.max_row
        for c_idx in range(1, len(row_vals) + 1):
            c = ws3.cell(row=curr, column=c_idx)
            c.font = _font_regular
            c.border = _border_all
            c.fill = _fill_reversal if idx % 2 == 0 else _fill_zebra
            if c_idx in (1, 2, 3, 5, 6):
                c.alignment = Alignment(horizontal="center")
            elif c_idx in (7, 8, 9, 10, 11):
                c.alignment = Alignment(horizontal="right")
                c.number_format = "#,##0.00"

    _auto_fit_columns(ws3)

    # -----------------------------------------------------------------------
    # Sheet 4: External Adjustments
    # -----------------------------------------------------------------------
    ws4 = wb.create_sheet(title="External Adjustments")
    ws4.views.sheetView[0].showGridLines = True
    ws4.append([WORKPAPER_TITLE, "Sheet: External Adjustments (Rules 42/43/38/RCM)"])
    ws4["A1"].font = _font_title
    ws4.append([])

    adjs = load_table4_adjustments(sb, run_id)
    adj_headers = [
        "Table Row",
        "Adjustment Type",
        "Statutory Category",
        "IGST (INR)",
        "CGST (INR)",
        "SGST (INR)",
        "Cess (INR)",
        "Total Adjustment (INR)",
        "Mandatory Reason / Workpaper Ref",
        "Reference Document",
        "Created At",
    ]
    ws4.append(adj_headers)
    hdr_row4 = ws4.max_row
    for c_idx in range(1, len(adj_headers) + 1):
        c = ws4.cell(row=hdr_row4, column=c_idx)
        c.font = _font_header
        c.fill = _fill_header
        c.border = _border_all

    for idx, a in enumerate(adjs):
        ig = paise_to_rupees(a.get("igst_paise") or 0)
        cg = paise_to_rupees(a.get("cgst_paise") or 0)
        sg = paise_to_rupees(a.get("sgst_paise") or 0)
        cs = paise_to_rupees(a.get("cess_paise") or 0)
        row_vals = [
            a.get("row_id"),
            a.get("adjustment_type"),
            a.get("statutory_category"),
            ig,
            cg,
            sg,
            cs,
            round(ig + cg + sg + cs, 2),
            a.get("reason"),
            a.get("reference_doc") or "—",
            str(a.get("created_at") or "")[:19],
        ]
        ws4.append(row_vals)
        curr = ws4.max_row
        for c_idx in range(1, len(row_vals) + 1):
            c = ws4.cell(row=curr, column=c_idx)
            c.font = _font_regular
            c.border = _border_all
            if idx % 2 == 1:
                c.fill = _fill_zebra
            if c_idx in (1, 2, 3, 11):
                c.alignment = Alignment(horizontal="center")
            elif c_idx in (4, 5, 6, 7, 8):
                c.alignment = Alignment(horizontal="right")
                c.number_format = "#,##0.00"

    _auto_fit_columns(ws4)

    # -----------------------------------------------------------------------
    # Sheet 5: Audit Log & Workpaper Certification
    # -----------------------------------------------------------------------
    ws5 = wb.create_sheet(title="Audit Log & Certification")
    ws5.views.sheetView[0].showGridLines = True
    ws5.append([WORKPAPER_TITLE, "Sheet: Workpaper Integrity & Audit Log"])
    ws5["A1"].font = _font_title
    ws5.append([])

    meta_rows = [
        ("Reconciliation Run ID", str(data.get("run_id"))),
        ("Client GSTIN", str(data.get("client_gstin"))),
        ("Tax Period", str(data.get("tax_period"))),
        ("Workpaper Status", str(data.get("status"))),
        ("Is Run Locked", "YES" if data.get("is_locked") else "NO"),
        ("Finalized At", str(data.get("finalized_at") or "Not Finalized")),
        ("Finalized By User ID", str(data.get("finalized_by") or "—")),
        ("Deterministic Audit Hash (SHA-256)", str(data.get("audit_hash") or "—")),
        ("Generated On", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")),
        ("Statutory Reporting Standard", "CBIC Circular No. 170/02/2022-GST / CGST Act 2017"),
        ("Workpaper Disclaimer", DISCLAIMER_TEXT),
    ]

    for label, val in meta_rows:
        ws5.append([label, val])
        curr = ws5.max_row
        c1 = ws5.cell(row=curr, column=1)
        c2 = ws5.cell(row=curr, column=2)
        c1.font = _font_bold
        c2.font = _font_regular
        c1.border = _border_all
        c2.border = _border_all
        c1.fill = _fill_section

    _auto_fit_columns(ws5, max_len_cap=90)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
