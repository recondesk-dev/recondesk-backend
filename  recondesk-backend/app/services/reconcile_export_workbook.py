"""Excel workbook builder for reconciliation run exports."""

from __future__ import annotations

import io
import logging
import re
from datetime import date, datetime
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

_log = logging.getLogger(__name__)

_EXCEL_CAP = 1000
_HEADER_BLUE = "1F4E79"
_HEADER_GREEN = "375623"
_HEADER_RED = "C00000"
_HEADER_PURPLE = "7030A0"

_FILL_FUZZY = "E2EFDA"
_FILL_MANUAL = "FFF2CC"
_FILL_OTHER = "FCE4D6"
_FILL_TOTAL_GREEN = "E2EFDA"
_FILL_TOTAL_RED = "FCE4D6"
_FILL_R37_CRIT = "FFE7E7"
_FILL_R37_HIGH = "FFF0E0"
_FILL_R37_MED = "FFFDE7"


def _decision_cell(v: Any) -> str:
    if v is None:
        return "—"
    s = str(v).strip()
    return "—" if not s else s


def _rs_int(n: float) -> str:
    return f"Rs {int(round(float(n))):,}"


def _comma_int(n: float) -> str:
    return f"{int(round(float(n))):,}"


def _period_mmm_yyyy(period: str) -> str:
    s = (period or "").strip()
    try:
        if len(s) >= 7 and s[4] == "-":
            parts = s[:7].split("-")
            y, m = int(parts[0]), int(parts[1])
            return date(y, m, 1).strftime("%b %Y")
    except (ValueError, TypeError, IndexError):
        pass
    return s or "—"


def _taxable_from_gstr_merged(gd: dict[str, Any]) -> float:
    tp = gd.get("taxable_amount_paise")
    if tp is not None and str(tp).strip() != "":
        try:
            return int(tp) / 100.0
        except (TypeError, ValueError):
            pass
    for k in ("taxable_amount", "Taxable Amount", "taxable_val", "taxable"):
        if k in gd and gd[k] not in (None, ""):
            try:
                return float(gd[k])
            except (TypeError, ValueError):
                continue
    return 0.0


def _taxable_from_missed_row(row: dict[str, Any]) -> float:
    gd = row.get("gstr2b_data")
    if isinstance(gd, dict):
        return _taxable_from_gstr_merged(gd)
    return 0.0


def _safe_filename_part(s: str) -> str:
    o = re.sub(r"[^\w\-.]+", "_", (s or "").strip())
    return (o[:80] or "client").strip("_") or "client"


def _autosize_columns(ws: Any, max_width: float = 60.0, min_width: float = 8.0) -> None:
    for col_cells in ws.iter_cols(min_row=1, max_row=ws.max_row):
        letter = get_column_letter(col_cells[0].column)
        mlen = 0
        for c in col_cells:
            if c.value is not None:
                mlen = max(mlen, len(str(c.value)))
        ws.column_dimensions[letter].width = min(max_width, max(min_width, mlen + 2))


class _SheetTrack:
    __slots__ = ("name", "row_count", "status", "capped")

    def __init__(
        self,
        name: str,
        row_count: int = 0,
        status: str = "OK",
        capped: bool = False,
    ) -> None:
        self.name = name
        self.row_count = row_count
        self.status = status
        self.capped = capped


def build_excel_workbook_bytes(
    *,
    run_id: str,
    firm_name: str,
    client_trade_name: str,
    period_raw: str,
    summary: dict[str, Any],
    matched_pairs: list[tuple[dict[str, Any], Any]],
    missed_rows: list[dict[str, Any]],
    risk_rows: list[dict[str, Any]],
    rule37_rows: list[dict[str, Any]],
    section17_rows: list[dict[str, Any]],
    generated_at: datetime,
    generated_by_name: str,
) -> tuple[bytes, str]:
    """Return (xlsx bytes, filename)."""
    tracks: list[_SheetTrack] = []
    cap_note_lines: list[str] = []

    wb = Workbook()
    # Remove default sheet; we'll add named sheets
    default_ws = wb.active
    wb.remove(default_ws)

    # --- Sheet 1 Summary ---
    ws1 = wb.create_sheet("Summary", 0)
    try:
        period_disp = _period_mmm_yyyy(period_raw)
        title_font = Font(size=16, bold=True, color=_HEADER_BLUE)
        ws1["A1"] = "Reconciliation Report"
        ws1["A1"].font = title_font
        row = 3
        labels_vals = [
            ("CA Firm Name:", firm_name or "—"),
            ("Client Name:", client_trade_name or "—"),
            ("Period:", period_disp),
            (
                "Date Generated:",
                generated_at.strftime("%d %b %Y"),
            ),
        ]
        for lab, val in labels_vals:
            ws1.cell(row=row, column=1, value=lab)
            ws1.cell(row=row, column=2, value=val)
            row += 1
        row += 1
        ws1.cell(row=row, column=1, value="Key Stats")
        ws1.cell(row=row, column=1).font = Font(bold=True)
        row += 1
        stats = [
            ("Total GSTR Records", summary.get("total_gstr_records", 0)),
            ("Matched Records", summary.get("matched_count", 0)),
            ("Match Rate %", summary.get("match_rate_percent", 0)),
            ("Missed ITC Count", summary.get("missed_itc_count", 0)),
            (
                "Total ITC Recoverable",
                _rs_int(float(summary.get("missed_itc_total_amount") or 0)),
            ),
            ("Compliance Risk Count", summary.get("wrongful_risk_count", 0)),
            (
                "Total ITC at Risk",
                _rs_int(float(summary.get("wrongful_risk_total_amount") or 0)),
            ),
        ]
        for lab, val in stats:
            c1 = ws1.cell(row=row, column=1, value=lab)
            c1.font = Font(bold=True)
            c2 = ws1.cell(row=row, column=2, value=val)
            row += 1
        ws1.column_dimensions["A"].width = 30
        ws1.column_dimensions["B"].width = 20
        tracks.append(_SheetTrack("Summary", row_count=0, status="OK"))
    except Exception as e:
        _log.exception("excel summary sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Summary", 0, f"FAILED: {e}"))
        ws1["A12"] = f"Summary generation failed: {e}"

    # --- Sheet 2 Matched ---
    ws2 = wb.create_sheet("Matched Records")
    try:
        headers = (
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "Taxable Amount",
            "Total Tax",
            "Match Level",
            "Confidence",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_BLUE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws2.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws2.freeze_panes = "A2"
        full_count = len(matched_pairs)
        capped = full_count > _EXCEL_CAP
        slice_pairs = matched_pairs[:_EXCEL_CAP]
        fill_exact = PatternFill("solid", fgColor="FFFFFF")
        fill_fuzzy = PatternFill("solid", fgColor=_FILL_FUZZY)
        fill_manual = PatternFill("solid", fgColor=_FILL_MANUAL)
        fill_other = PatternFill("solid", fgColor=_FILL_OTHER)
        r = 2
        for api_row, _orow in slice_pairs:
            lvl = str(api_row.get("match_level") or "").upper()
            if lvl == "EXACT":
                row_fill = fill_exact
            elif lvl == "FUZZY":
                row_fill = fill_fuzzy
            elif lvl == "MANUAL":
                row_fill = fill_manual
            else:
                row_fill = fill_other
            gd = api_row.get("gstr2b_data")
            taxable = (
                _taxable_from_gstr_merged(gd) if isinstance(gd, dict) else 0.0
            )
            conf_pct = int(
                round(
                    min(1.0, max(0.0, float(api_row.get("confidence_score") or 0)))
                    * 100
                )
            )
            vals = (
                api_row.get("supplier_gstin", ""),
                api_row.get("invoice_number", ""),
                api_row.get("invoice_date", ""),
                _comma_int(taxable),
                _comma_int(float(api_row.get("amount") or 0)),
                api_row.get("match_level", ""),
                f"{conf_pct}%",
                _decision_cell(api_row.get("decision_what")),
                _decision_cell(api_row.get("decision_why")),
                _decision_cell(api_row.get("decision_next")),
            )
            for col, v in enumerate(vals, 1):
                c = ws2.cell(row=r, column=col, value=v)
                c.fill = row_fill
            r += 1
        if capped:
            ws2.cell(
                row=r,
                column=1,
                value="[Note: Showing first 1,000 records. Use section CSV export for full data.]",
            )
            r += 1
            cap_note_lines.append(
                "[Matched Records]: Capped at 1,000 rows. Use CSV export for complete data."
            )
        _autosize_columns(ws2)
        tracks.append(
            _SheetTrack(
                "Matched Records",
                row_count=full_count,
                status="OK",
                capped=capped,
            )
        )
    except Exception as e:
        _log.exception("excel matched sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Matched Records", 0, f"FAILED: {e}"))

    # --- Sheet 3 Missed ITC ---
    ws3 = wb.create_sheet("Missed ITC")
    try:
        headers = (
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "Taxable Amount",
            "ITC Amount",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_GREEN)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws3.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws3.freeze_panes = "A2"
        full_count = len(missed_rows)
        capped = full_count > _EXCEL_CAP
        rows_slice = missed_rows[:_EXCEL_CAP]
        r = 2
        sum_itc = 0.0
        for row in rows_slice:
            tax_amt = _taxable_from_missed_row(row)
            itc_am = float(row.get("amount") or 0)
            sum_itc += itc_am
            vals = (
                row.get("supplier_gstin", ""),
                row.get("invoice_number", ""),
                row.get("invoice_date", ""),
                _comma_int(tax_amt),
                _comma_int(itc_am),
                _decision_cell(row.get("decision_what")),
                _decision_cell(row.get("decision_why")),
                _decision_cell(row.get("decision_next")),
            )
            for col, v in enumerate(vals, 1):
                ws3.cell(row=r, column=col, value=v)
            r += 1
        if capped:
            ws3.cell(
                row=r,
                column=1,
                value="[Note: Showing first 1,000 records. Use section CSV export for full data.]",
            )
            r += 1
            cap_note_lines.append(
                "[Missed ITC]: Capped at 1,000 rows. Use CSV export for complete data."
            )
        total_fill = PatternFill("solid", fgColor=_FILL_TOTAL_GREEN)
        bold = Font(bold=True)
        ws3.cell(row=r, column=1, value="TOTAL")
        ws3.cell(row=r, column=1).font = bold
        ws3.cell(row=r, column=1).fill = total_fill
        csum = ws3.cell(row=r, column=5, value=_comma_int(sum_itc))
        csum.font = bold
        csum.fill = total_fill
        r += 1
        _autosize_columns(ws3)
        tracks.append(
            _SheetTrack("Missed ITC", row_count=full_count, status="OK", capped=capped)
        )
    except Exception as e:
        _log.exception("excel missed itc sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Missed ITC", 0, f"FAILED: {e}"))

    # --- Sheet 4 Compliance Risk ---
    ws4 = wb.create_sheet("Compliance Risk")
    try:
        headers = (
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "ITC at Risk",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_RED)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws4.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws4.freeze_panes = "A2"
        full_count = len(risk_rows)
        capped = full_count > _EXCEL_CAP
        rows_slice = risk_rows[:_EXCEL_CAP]
        r = 2
        sum_risk = 0.0
        for row in rows_slice:
            am = float(row.get("amount") or 0)
            sum_risk += am
            vals = (
                row.get("supplier_gstin", ""),
                row.get("invoice_number", ""),
                row.get("invoice_date", ""),
                _comma_int(am),
                _decision_cell(row.get("decision_what")),
                _decision_cell(row.get("decision_why")),
                _decision_cell(row.get("decision_next")),
            )
            for col, v in enumerate(vals, 1):
                ws4.cell(row=r, column=col, value=v)
            r += 1
        if capped:
            ws4.cell(
                row=r,
                column=1,
                value="[Note: Showing first 1,000 records. Use section CSV export for full data.]",
            )
            r += 1
            cap_note_lines.append(
                "[Compliance Risk]: Capped at 1,000 rows. Use CSV export for complete data."
            )
        total_fill = PatternFill("solid", fgColor=_FILL_TOTAL_RED)
        bold = Font(bold=True)
        ws4.cell(row=r, column=1, value="TOTAL")
        ws4.cell(row=r, column=1).font = bold
        ws4.cell(row=r, column=1).fill = total_fill
        csum = ws4.cell(row=r, column=4, value=_comma_int(sum_risk))
        csum.font = bold
        csum.fill = total_fill
        r += 1
        _autosize_columns(ws4)
        tracks.append(
            _SheetTrack(
                "Compliance Risk", row_count=full_count, status="OK", capped=capped
            )
        )
    except Exception as e:
        _log.exception("excel risk sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Compliance Risk", 0, f"FAILED: {e}"))

    # --- Sheet 5 Rule 37 & Section 17(5) ---
    ws5 = wb.create_sheet("Rule 37 & Section 17-5")
    try:
        headers = (
            "Type",
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "Amount",
            "Urgency",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_PURPLE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws5.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws5.freeze_panes = "A2"
        combined: list[tuple[str, dict[str, Any]]] = [
            ("Rule 37", r) for r in rule37_rows
        ] + [("Section 17(5)", r) for r in section17_rows]
        full_count = len(combined)
        capped = full_count > _EXCEL_CAP
        combined = combined[:_EXCEL_CAP]
        r = 2
        if not combined:
            ws5["A2"] = "No Rule 37 or Section 17(5) flags found."
        else:
            fill_crit = PatternFill("solid", fgColor=_FILL_R37_CRIT)
            fill_high = PatternFill("solid", fgColor=_FILL_R37_HIGH)
            fill_med = PatternFill("solid", fgColor=_FILL_R37_MED)
            fill_white = PatternFill("solid", fgColor="FFFFFF")
            for typ, row in combined:
                urg = ""
                if typ == "Rule 37":
                    urg = str(row.get("rule37_urgency") or "")
                    u = urg.upper()
                    if u == "CRITICAL":
                        rf = fill_crit
                    elif u == "HIGH":
                        rf = fill_high
                    elif u == "MEDIUM":
                        rf = fill_med
                    else:
                        rf = fill_white
                else:
                    urg = str(row.get("section_17_5_category") or "—")
                    rf = fill_white
                vals = (
                    typ,
                    row.get("supplier_gstin", ""),
                    row.get("invoice_number", ""),
                    row.get("invoice_date", ""),
                    _comma_int(float(row.get("amount") or 0)),
                    urg or "—",
                    _decision_cell(row.get("decision_what")),
                    _decision_cell(row.get("decision_why")),
                    _decision_cell(row.get("decision_next")),
                )
                for col, v in enumerate(vals, 1):
                    c = ws5.cell(row=r, column=col, value=v)
                    c.fill = rf
                r += 1
        if capped:
            ws5.cell(
                row=r,
                column=1,
                value="[Note: Showing first 1,000 records. Use section CSV export for full data.]",
            )
            r += 1
            cap_note_lines.append(
                "[Rule 37 & S17]: Capped at 1,000 rows. Use CSV export for complete data."
            )
        _autosize_columns(ws5)
        tracks.append(
            _SheetTrack(
                "Rule 37 & 17(5)",
                row_count=full_count,
                status="OK",
                capped=capped,
            )
        )
    except Exception as e:
        _log.exception("excel rule37/s17 sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Rule 37 & 17(5)", 0, f"FAILED: {e}"))

    # --- Sheet 6 Export Notes ---
    ws6 = wb.create_sheet("Export Notes")
    ws6["A1"] = "Export Notes"
    ws6["A1"].font = Font(bold=True, size=14)
    ws6["A3"] = "Generated At:"
    ws6["B3"] = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    ws6["A4"] = "Generated By:"
    ws6["B4"] = generated_by_name or "—"
    ws6["A5"] = "Run ID:"
    ws6["B5"] = run_id
    r = 7
    ws6.cell(row=r, column=1, value="Sheet")
    ws6.cell(row=r, column=2, value="Row Count")
    ws6.cell(row=r, column=3, value="Status")
    for c in range(1, 4):
        ws6.cell(row=r, column=c).font = Font(bold=True)
    r += 1
    name_map = {
        "Summary": "Summary",
        "Matched Records": "Matched Records",
        "Missed ITC": "Missed ITC",
        "Compliance Risk": "Compliance Risk",
        "Rule 37 & 17(5)": "Rule 37 & 17(5)",
    }
    for tr in tracks:
        disp = name_map.get(tr.name, tr.name)
        rc = "—" if tr.name == "Summary" else str(tr.row_count)
        if tr.name == "Summary":
            rc = "—"
        ws6.cell(row=r, column=1, value=disp)
        ws6.cell(row=r, column=2, value=rc)
        ws6.cell(row=r, column=3, value=tr.status)
        r += 1
    r += 1
    for line in cap_note_lines:
        ws6.cell(row=r, column=1, value=line)
        r += 1
    ws6.column_dimensions["A"].width = 40
    ws6.column_dimensions["B"].width = 16
    ws6.column_dimensions["C"].width = 50

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = f"ReconDesk_{_safe_filename_part(client_trade_name)}_{_safe_filename_part(period_raw)}.xlsx"
    return buf.getvalue(), fn
