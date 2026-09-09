"""Multi-Period Reconciliation Excel Export Builder.

Generates a consolidated multi-sheet Excel workbook for annual (12-month) reconciliation batches.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from supabase import Client

from app.services.gstr9c_itc_fy_rollup import build_gstr9c_itc_fy_rollup
from app.services.multi_period_wizard import get_batch_with_items

logger = logging.getLogger(__name__)

_HEADER_BLUE = "1F4E79"
_HEADER_GREEN = "375623"
_HEADER_RED = "C00000"
_FILL_LIGHT_BLUE = "D9E1F2"
_FILL_LIGHT_GREEN = "E2EFDA"
_FILL_LIGHT_RED = "FCE4D6"
_FILL_LIGHT_GRAY = "F2F2F2"


def _format_inr(paise: int | float | None) -> float:
    if paise is None:
        return 0.0
    return round(float(paise) / 100.0, 2)


def build_multi_period_excel_export(sb: Client, batch_id: str) -> bytes:
    """Build multi-sheet XLSX export for an annual reconciliation batch."""
    batch = get_batch_with_items(sb, batch_id)
    client_id = batch["client_gstin_id"]
    fy = batch["financial_year"]

    rollup = build_gstr9c_itc_fy_rollup(sb, client_gstin_id=client_id, fy=fy)



    wb = Workbook()
    
    # ── Sheet 1: FY Rollup Summary ─────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "FY Summary Rollup"
    ws1.views.sheetView[0].showGridLines = True

    # Title Banner
    ws1.merge_cells("A1:E1")
    title_cell = ws1["A1"]
    title_cell.value = f"RECONDESK — FY {fy} ANNUAL RECONCILIATION ROLLUP"
    title_cell.font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    title_cell.fill = PatternFill(start_color=_HEADER_BLUE, end_color=_HEADER_BLUE, fill_type="solid")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 30

    # Client & Metadata
    ws1["A3"] = "Client ID:"
    ws1["B3"] = client_id
    ws1["A4"] = "Financial Year:"
    ws1["B4"] = fy
    ws1["A5"] = "Batch Status:"
    ws1["B5"] = batch.get("status", "unknown").upper()
    for row in range(3, 6):
        ws1[f"A{row}"].font = Font(name="Calibri", size=11, bold=True)

    # Key Metrics KPI Table
    ws1["A7"] = "Metric"
    ws1["B7"] = "Amount (₹)"
    for col in ["A7", "B7"]:
        ws1[col].font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        ws1[col].fill = PatternFill(start_color=_HEADER_BLUE, end_color=_HEADER_BLUE, fill_type="solid")

    kpis = [
        ("Total GSTR-2B Available ITC", _format_inr(rollup.get("total_gstr_itc_paise"))),
        ("Total Matched ITC", _format_inr(rollup.get("matched_itc_paise"))),
        ("Total Missed ITC (Not In Books)", _format_inr(rollup.get("missed_itc_paise"))),
        ("Total Wrongful / Risk ITC (Not In 2B)", _format_inr(rollup.get("wrongful_risk_paise"))),
    ]

    for idx, (label, val) in enumerate(kpis, start=8):
        ws1[f"A{idx}"] = label
        ws1[f"B{idx}"] = val
        ws1[f"B{idx}"].number_format = "₹#,##0.00"
        if "Matched" in label:
            ws1[f"B{idx}"].fill = PatternFill(start_color=_FILL_LIGHT_GREEN, fill_type="solid")
        elif "Risk" in label or "Wrongful" in label:
            ws1[f"B{idx}"].fill = PatternFill(start_color=_FILL_LIGHT_RED, fill_type="solid")

    # Monthly Breakdown Table Header
    ws1["A14"] = "12-MONTH PERIOD BREAKDOWN"
    ws1["A14"].font = Font(name="Calibri", size=12, bold=True)

    headers = [
        "Period",
        "Month",
        "GSTR-2B Source",
        "PR Source",
        "Item Status",
        "Run ID",
    ]
    for col_idx, h in enumerate(headers, start=1):
        cell = ws1.cell(row=15, column=col_idx, value=h)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=_HEADER_BLUE, end_color=_HEADER_BLUE, fill_type="solid")

    months_map = {
        "01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr",
        "05": "May", "06": "Jun", "07": "Jul", "08": "Aug",
        "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec",
    }

    items = batch.get("items", [])
    for idx, item in enumerate(items, start=16):
        period = str(item.get("period", ""))
        m_code = period[5:7] if len(period) >= 7 else ""
        m_name = f"{months_map.get(m_code, m_code)} {period[:4]}"

        ws1.cell(row=idx, column=1, value=period)
        ws1.cell(row=idx, column=2, value=m_name)
        ws1.cell(row=idx, column=3, value=item.get("gstr2b_source") or "—")
        ws1.cell(row=idx, column=4, value=item.get("pr_source") or "—")
        ws1.cell(row=idx, column=5, value=item.get("status", "pending"))
        ws1.cell(row=idx, column=6, value=item.get("reconciliation_run_id") or "—")

    # ── Sheet 2: Items & Run Status ────────────────────────────────────────────
    ws2 = wb.create_sheet(title="Monthly Batch Items")
    ws2.views.sheetView[0].showGridLines = True

    ws2_headers = [
        "Item ID",
        "Period",
        "GSTR-2B Path",
        "PR Path",
        "Run ID",
        "Status",
        "Error Message",
    ]
    for col_idx, h in enumerate(ws2_headers, start=1):
        cell = ws2.cell(row=1, column=col_idx, value=h)
        cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color=_HEADER_BLUE, end_color=_HEADER_BLUE, fill_type="solid")

    for idx, item in enumerate(items, start=2):
        ws2.cell(row=idx, column=1, value=item.get("id"))
        ws2.cell(row=idx, column=2, value=item.get("period"))
        ws2.cell(row=idx, column=3, value=item.get("gstr2b_file_path") or "—")
        ws2.cell(row=idx, column=4, value=item.get("pr_file_path") or "—")
        ws2.cell(row=idx, column=5, value=item.get("reconciliation_run_id") or "—")
        ws2.cell(row=idx, column=6, value=item.get("status"))
        ws2.cell(row=idx, column=7, value=item.get("error_message") or "—")

    # Auto-adjust column widths
    for sheet in [ws1, ws2]:
        for col in sheet.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = get_column_letter(col[0].column)
            sheet.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
