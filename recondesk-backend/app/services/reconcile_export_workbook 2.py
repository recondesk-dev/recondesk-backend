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

_HEADER_BLUE = "1F4E79"
_HEADER_GREEN = "375623"
_HEADER_RED = "C00000"
_HEADER_PURPLE = "7030A0"
_HEADER_ORANGE = "C55A11"

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


def _format_match_confidence(raw: Any) -> str:
    """Format fuzzy ``match_confidence`` as ``85%``; blank dash for L1–L4 / missing."""
    if raw is None:
        return "—"
    try:
        score = float(raw)
    except (TypeError, ValueError):
        return "—"
    # Tolerate accidental 0–100 storage without changing engine writes.
    if score > 1.0:
        score = score / 100.0
    if score < 0:
        return "—"
    return f"{int(round(score * 100))}%"


_FIELD_LABELS = {
    "gstin": "GSTIN",
    "invoice_number": "Invoice#",
    "taxable_amount": "Amount",
    "date": "Date",
    "vendor_name": "Vendor",
}


def _format_match_rationale(compared_fields: Any) -> str:
    """Flatten ``compared_fields`` into a single audit-friendly cell string."""
    if not isinstance(compared_fields, list) or not compared_fields:
        return "—"
    parts: list[str] = []
    for entry in compared_fields:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("field_name") or "").strip()
        if not name:
            continue
        label = _FIELD_LABELS.get(name, name.replace("_", " ").title())
        match_type = str(entry.get("match_type") or "not_matched").strip().replace(
            "_", " "
        )
        score = entry.get("field_score")
        if match_type == "fuzzy" and score is not None:
            try:
                parts.append(f"{label}: fuzzy {int(score)}%")
            except (TypeError, ValueError):
                parts.append(f"{label}: fuzzy")
        else:
            parts.append(f"{label}: {match_type}")
    return " | ".join(parts) if parts else "—"


def _rs_int(n: float) -> str:
    return f"Rs {int(round(float(n))):,}"


def _comma_int(n: float) -> str:
    return f"{int(round(float(n))):,}"


def _doc_type_display(doc_type: Any) -> str:
    """Return formatted document type, defaulting to 'Invoice'."""
    if not doc_type:
        return "Invoice"
    s = str(doc_type).strip().upper()
    if s in ("CREDIT_NOTE", "CREDIT"):
        return "Credit Note"
    if s in ("DEBIT_NOTE", "DEBIT"):
        return "Debit Note"
    return "Invoice"


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
    __slots__ = ("name", "row_count", "status")

    def __init__(
        self,
        name: str,
        row_count: int = 0,
        status: str = "OK",
    ) -> None:
        self.name = name
        self.row_count = row_count
        self.status = status


def _outcome_amount_rupees(row: dict[str, Any]) -> float:
    """Outcome rows store tax as paise (int); UI/API rows use rupees (float)."""
    am = row.get("amount")
    if am is None or am == "":
        return 0.0
    try:
        if isinstance(am, int):
            return float(am) / 100.0
        return float(am)
    except (TypeError, ValueError):
        return 0.0


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
    review_required_rows: list[dict[str, Any]],
    generated_at: datetime,
    generated_by_name: str,
    duplicate_rows: list[dict[str, Any]] | None = None,
    gstr3b_result: dict[str, Any] | None = None,
    followup_rows: list[dict[str, Any]] | None = None,
) -> tuple[bytes, str]:
    """Return (xlsx bytes, filename).

    Always builds every section sheet. Empty sections still get a sheet with
    headers and a status/placeholder row — never omit sheets based on UI tab.
    """
    duplicate_rows = list(duplicate_rows or [])
    followup_rows = list(followup_rows or [])
    tracks: list[_SheetTrack] = []

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
            (
                "Review Required",
                summary.get("review_required_count", len(review_required_rows)),
            ),
            (
                "Duplicate Entries",
                summary.get("duplicate_entry_count", len(duplicate_rows)),
            ),
            ("Match Rate %", summary.get("match_rate_percent", 0)),
            ("Missed ITC Count", summary.get("missed_itc_count", 0)),
            (
                "Total ITC Recoverable",
                _rs_int(float(summary.get("missed_itc_total_amount") or 0)),
            ),
            ("ITC at Risk Count", summary.get("wrongful_risk_count", 0)),
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
            "Document Type",
            "Taxable Amount",
            "Total Tax",
            "Match Level",
            "Confidence",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
            "Match Confidence",
            "Match Rationale",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_BLUE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws2.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws2.freeze_panes = "A2"
        fill_exact = PatternFill("solid", fgColor="FFFFFF")
        fill_fuzzy = PatternFill("solid", fgColor=_FILL_FUZZY)
        fill_manual = PatternFill("solid", fgColor=_FILL_MANUAL)
        fill_other = PatternFill("solid", fgColor=_FILL_OTHER)
        r = 2
        for api_row, _orow in matched_pairs:
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
                    min(100.0, max(0.0, float(api_row.get("confidence_score") or 0)))
                )
            )
            vals = (
                api_row.get("supplier_gstin", ""),
                api_row.get("invoice_number", ""),
                api_row.get("invoice_date", ""),
                _doc_type_display(api_row.get("document_type")),
                _comma_int(taxable),
                _comma_int(float(api_row.get("amount") or 0)),
                api_row.get("match_level", ""),
                f"{conf_pct}%",
                _decision_cell(api_row.get("decision_what")),
                _decision_cell(api_row.get("decision_why")),
                _decision_cell(api_row.get("decision_next")),
                _format_match_confidence(api_row.get("match_confidence")),
                _format_match_rationale(api_row.get("compared_fields")),
            )
            for col, v in enumerate(vals, 1):
                c = ws2.cell(row=r, column=col, value=v)
                c.fill = row_fill
            r += 1
        _autosize_columns(ws2)
        tracks.append(
            _SheetTrack(
                "Matched Records",
                row_count=len(matched_pairs),
                status="OK",
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
            "Document Type",
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
        r = 2
        sum_itc = 0.0
        for row in missed_rows:
            tax_amt = _taxable_from_missed_row(row)
            itc_am = float(row.get("amount") or 0)
            sum_itc += itc_am
            gstr_doc = row.get("gstr2b_data", {}).get("document_type") if isinstance(row.get("gstr2b_data"), dict) else None
            # fallback to top-level if gstr2b_data doesn't have it
            if not gstr_doc:
                gstr_doc = row.get("document_type")

            vals = (
                row.get("supplier_gstin", ""),
                row.get("invoice_number", ""),
                row.get("invoice_date", ""),
                _doc_type_display(gstr_doc),
                _comma_int(tax_amt),
                _comma_int(itc_am),
                _decision_cell(row.get("decision_what")),
                _decision_cell(row.get("decision_why")),
                _decision_cell(row.get("decision_next")),
            )
            for col, v in enumerate(vals, 1):
                ws3.cell(row=r, column=col, value=v)
            r += 1
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
            _SheetTrack("Missed ITC", row_count=len(missed_rows), status="OK")
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
            "Document Type",
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
        r = 2
        sum_risk = 0.0
        for row in risk_rows:
            am = float(row.get("amount") or 0)
            sum_risk += am
            vals = (
                row.get("supplier_gstin", ""),
                row.get("invoice_number", ""),
                row.get("invoice_date", ""),
                _doc_type_display(row.get("document_type")),
                _comma_int(am),
                _decision_cell(row.get("decision_what")),
                _decision_cell(row.get("decision_why")),
                _decision_cell(row.get("decision_next")),
            )
            for col, v in enumerate(vals, 1):
                ws4.cell(row=r, column=col, value=v)
            r += 1
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
                "Compliance Risk", row_count=len(risk_rows), status="OK"
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
        combined: list[tuple[str, dict[str, Any]]] = []
        for r in rule37_rows:
            if not isinstance(r, dict):
                continue
            typ = (
                "Rule 37A"
                if (
                    r.get("rule37a_flag")
                    or r.get("status") == "RULE37A"
                    or "37A" in str(r.get("decision_what") or "")
                    or "Non-Filer" in str(r.get("decision_what") or "")
                )
                else "Rule 37"
            )
            combined.append((typ, r))
        for r in section17_rows:
            if not isinstance(r, dict):
                continue
            # Drop blank Section 17(5) shells (every text column would be "—").
            has_identity = bool(
                str(r.get("supplier_gstin") or "").strip()
                or str(r.get("invoice_number") or "").strip()
            )
            has_decision = bool(
                str(r.get("decision_what") or "").strip()
                or str(r.get("decision_why") or "").strip()
                or str(r.get("decision_next") or "").strip()
            )
            if not has_identity or not has_decision:
                continue
            what = str(r.get("decision_what") or "")
            why = str(r.get("decision_why") or "")
            if "blocked credit: ?" in what or "HSN ?" in why:
                continue
            combined.append(("Section 17(5)", r))
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
                if typ in ("Rule 37", "Rule 37A"):
                    urg = str(row.get("rule37_urgency") or "")
                    if typ == "Rule 37A" and not urg:
                        urg = "HIGH"
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
        _autosize_columns(ws5)
        tracks.append(
            _SheetTrack(
                "Rule 37 & 17(5)",
                row_count=len(combined),
                status="OK",
            )
        )
    except Exception as e:
        _log.exception("excel rule37/s17 sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Rule 37 & 17(5)", 0, f"FAILED: {e}"))

    # --- Sheet 6 Review Required ---
    try:
        ws_rev = wb.create_sheet("Review Required")
        ws_rev.append(
            [
                "Supplier GSTIN",
                "Invoice Number",
                "Invoice Date",
                "Reason",
                "Amount",
                "Match Confidence",
                "Match Rationale",
            ]
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_ORANGE)
        for c in range(1, 8):
            ws_rev.cell(row=1, column=c).font = Font(bold=True, color="FFFFFF")
            ws_rev.cell(row=1, column=c).fill = hdr_fill
        r = 2
        for row in review_required_rows:
            ws_rev.append(
                [
                    row.get("supplier_gstin") or "—",
                    row.get("invoice_number") or "—",
                    row.get("invoice_date") or "—",
                    row.get("decision_why") or row.get("discrepancy_reason") or "—",
                    _rs_int(_outcome_amount_rupees(row) if isinstance(row.get("amount"), int) else float(row.get("amount") or 0)),
                    _format_match_confidence(row.get("match_confidence")),
                    _format_match_rationale(row.get("compared_fields")),
                ]
            )
            r += 1
        if not review_required_rows:
            ws_rev["A2"] = "No review-required records for this reconciliation run."
        _autosize_columns(ws_rev)
        tracks.append(
            _SheetTrack(
                "Review Required",
                row_count=len(review_required_rows),
                status="OK",
            )
        )
    except Exception as e:
        _log.exception("excel review required sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Review Required", 0, f"FAILED: {e}"))

    # --- Duplicate Entries ---
    try:
        ws_dup = wb.create_sheet("Duplicate Entries")
        headers = (
            "Supplier GSTIN",
            "Invoice#",
            "Date",
            "Amount",
            "Matched PR ID",
            "WHAT IS WRONG",
            "WHY",
            "WHAT TO DO NEXT",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_ORANGE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws_dup.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws_dup.freeze_panes = "A2"
        if not duplicate_rows:
            ws_dup["A2"] = "No duplicate entries for this reconciliation run."
        else:
            r = 2
            for row in duplicate_rows:
                vals = (
                    row.get("supplier_gstin") or "—",
                    row.get("invoice_number") or "—",
                    row.get("invoice_date") or "—",
                    _comma_int(_outcome_amount_rupees(row)),
                    row.get("matched_pr_id") or "—",
                    _decision_cell(row.get("decision_what")),
                    _decision_cell(row.get("decision_why")),
                    _decision_cell(row.get("decision_next")),
                )
                for col, v in enumerate(vals, 1):
                    ws_dup.cell(row=r, column=col, value=v)
                r += 1
        _autosize_columns(ws_dup)
        tracks.append(
            _SheetTrack(
                "Duplicate Entries",
                row_count=len(duplicate_rows),
                status="OK",
            )
        )
    except Exception as e:
        _log.exception("excel duplicate entries sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Duplicate Entries", 0, f"FAILED: {e}"))

    # --- GSTR-3B Check ---
    try:
        ws_g3b = wb.create_sheet("GSTR-3B Check")
        headers = (
            "Tax Head",
            "GSTR-2B Available",
            "GSTR-3B Claimed",
            "Difference",
            "Status",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_BLUE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws_g3b.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws_g3b.freeze_panes = "A2"

        def _g3b_f(key: str) -> float:
            try:
                return round(float((gstr3b_result or {}).get(key) or 0), 2)
            except (TypeError, ValueError):
                return 0.0

        if not gstr3b_result:
            ws_g3b["A2"] = "GSTR-3B not uploaded for this reconciliation run."
            g3b_rows = 0
        else:
            ws_g3b["A2"] = (
                f"Period: {gstr3b_result.get('tax_period') or '—'}  |  "
                f"Overall: {gstr3b_result.get('overall_status') or '—'}"
            )
            heads = (
                (
                    "IGST",
                    _g3b_f("gstr2b_igst_available"),
                    _g3b_f("gstr3b_igst_claimed"),
                    _g3b_f("igst_difference"),
                    str(gstr3b_result.get("igst_status") or "—"),
                ),
                (
                    "CGST",
                    _g3b_f("gstr2b_cgst_available"),
                    _g3b_f("gstr3b_cgst_claimed"),
                    _g3b_f("cgst_difference"),
                    str(gstr3b_result.get("cgst_status") or "—"),
                ),
                (
                    "SGST",
                    _g3b_f("gstr2b_sgst_available"),
                    _g3b_f("gstr3b_sgst_claimed"),
                    _g3b_f("sgst_difference"),
                    str(gstr3b_result.get("sgst_status") or "—"),
                ),
            )
            r = 3
            for head, g2b, g3b, diff, st in heads:
                vals = (head, _rs_int(g2b), _rs_int(g3b), _rs_int(diff), st)
                for col, v in enumerate(vals, 1):
                    ws_g3b.cell(row=r, column=col, value=v)
                r += 1
            tot_g2b = sum(h[1] for h in heads)
            tot_g3b = sum(h[2] for h in heads)
            tot_diff = sum(h[3] for h in heads)
            for col, v in enumerate(
                (
                    "Total",
                    _rs_int(tot_g2b),
                    _rs_int(tot_g3b),
                    _rs_int(tot_diff),
                    str(gstr3b_result.get("overall_status") or "—"),
                ),
                1,
            ):
                c = ws_g3b.cell(row=r, column=col, value=v)
                c.font = Font(bold=True)
            g3b_rows = 4
        _autosize_columns(ws_g3b)
        tracks.append(_SheetTrack("GSTR-3B Check", row_count=g3b_rows, status="OK"))
    except Exception as e:
        _log.exception("excel gstr3b sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("GSTR-3B Check", 0, f"FAILED: {e}"))

    # --- Follow-up Log ---
    try:
        ws_fu = wb.create_sheet("Follow-up Log")
        headers = (
            "Supplier Name",
            "Supplier GSTIN",
            "Invoice #",
            "Status",
            "Generated By",
            "Date & Time",
            "Template",
            "Letter Body",
        )
        hdr_fill = PatternFill("solid", fgColor=_HEADER_BLUE)
        hdr_font = Font(bold=True, color="FFFFFF")
        for col, h in enumerate(headers, 1):
            c = ws_fu.cell(row=1, column=col, value=h)
            c.font = hdr_font
            c.fill = hdr_fill
        ws_fu.freeze_panes = "A2"
        if not followup_rows:
            ws_fu["A2"] = "No supplier follow-up letters for this reconciliation run."
        else:
            r = 2
            for row in followup_rows:
                vals = (
                    row.get("supplier_name_display") or "—",
                    row.get("supplier_gstin") or "—",
                    row.get("invoice_numbers_display") or "—",
                    row.get("status") or "—",
                    row.get("generated_by_name") or "—",
                    row.get("generated_at") or "—",
                    row.get("template_type") or "—",
                    row.get("letter_body") or "",
                )
                for col, v in enumerate(vals, 1):
                    ws_fu.cell(row=r, column=col, value=v)
                r += 1
        _autosize_columns(ws_fu)
        tracks.append(
            _SheetTrack("Follow-up Log", row_count=len(followup_rows), status="OK")
        )
    except Exception as e:
        _log.exception("excel follow-up sheet failed run=%s", run_id)
        tracks.append(_SheetTrack("Follow-up Log", 0, f"FAILED: {e}"))

    # --- Export Notes ---
    ws6 = wb.create_sheet("Export Notes")
    ws6["A1"] = "Export Notes"
    ws6["A1"].font = Font(bold=True, size=14)
    ws6["A3"] = "Generated At:"
    ws6["B3"] = generated_at.strftime("%Y-%m-%d %H:%M:%S UTC")
    ws6["A4"] = "Generated By:"
    ws6["B4"] = generated_by_name or "—"
    ws6["A5"] = "Run ID:"
    ws6["B5"] = run_id
    ws6["A6"] = "Scope:"
    ws6["B6"] = "Full reconciliation workbook (all sections)"
    r = 8
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
        "Review Required": "Review Required",
        "Duplicate Entries": "Duplicate Entries",
        "GSTR-3B Check": "GSTR-3B Check",
        "Follow-up Log": "Follow-up Log",
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
    ws6.column_dimensions["A"].width = 40
    ws6.column_dimensions["B"].width = 16
    ws6.column_dimensions["C"].width = 50

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fn = f"ReconDesk_{_safe_filename_part(client_trade_name)}_{_safe_filename_part(period_raw)}.xlsx"
    return buf.getvalue(), fn
