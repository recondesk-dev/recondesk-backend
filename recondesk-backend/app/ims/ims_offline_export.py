"""GSTN IMS Offline Export & Batch File Generator.

Generates:
1. Official GST Portal IMS Offline Utility JSON files (act: A/R/P, grouped by section).
2. CA-Grade IMS Action Audit Workpapers in multi-sheet Excel (.xlsx).
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

_log = logging.getLogger(__name__)

# Colors for Excel Workpaper
_NAVY_HEADER = "1B365D"
_STEEL_BLUE = "2E5B88"
_WHITE = "FFFFFF"
_BORDER_GRAY = "CBD5E1"
_LIGHT_GRAY = "F8FAFC"
_CARD_BG = "F1F5F9"

# Action fills
_FILL_ACCEPT = "E2EFDA"      # Soft green
_FONT_ACCEPT = "276A3C"
_FILL_REJECT = "FCE4D6"      # Soft red
_FONT_REJECT = "991B1B"
_FILL_HOLD = "FFF2CC"        # Soft amber
_FONT_HOLD = "854D0E"

_font_title = Font(name="Calibri", size=14, bold=True, color=_NAVY_HEADER)
_font_subtitle = Font(name="Calibri", size=10, italic=True, color="475569")
_font_hdr = Font(name="Calibri", size=10, bold=True, color=_WHITE)
_font_bold = Font(name="Calibri", size=10, bold=True, color="0F172A")
_font_regular = Font(name="Calibri", size=9, color="1E293B")
_font_mono = Font(name="Consolas", size=9, color="1E293B")
_font_footnote = Font(name="Calibri", size=8, italic=True, color="64748B")

_fill_hdr = PatternFill("solid", fgColor=_NAVY_HEADER)
_fill_subhdr = PatternFill("solid", fgColor=_STEEL_BLUE)
_fill_zebra = PatternFill("solid", fgColor="F8FAFC")

_thin_side = Side(border_style="thin", color=_BORDER_GRAY)
_border_cell = Border(left=_thin_side, right=_thin_side, top=_thin_side, bottom=_thin_side)
_border_total = Border(
    left=_thin_side,
    right=_thin_side,
    top=Side(border_style="thin", color="000000"),
    bottom=Side(border_style="double", color="000000"),
)

_ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
_ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
_ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")


def format_gstn_date(d: Any) -> str:
    """Format any date string or object to DD-MM-YYYY for GST Portal."""
    if not d:
        return ""
    s = str(d).strip()
    if not s:
        return ""
    # Strip time if ISO datetime
    if "T" in s:
        s = s.split("T", 1)[0]
    elif " " in s:
        s = s.split(" ", 1)[0]
    # YYYY-MM-DD
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        parts = s.split("-")
        return f"{parts[2]}-{parts[1]}-{parts[0]}"
    # DD/MM/YYYY or MM/DD/YYYY
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3:
            if len(parts[2]) == 4:
                return f"{parts[0].zfill(2)}-{parts[1].zfill(2)}-{parts[2]}"
            elif len(parts[0]) == 4:
                return f"{parts[2].zfill(2)}-{parts[1].zfill(2)}-{parts[0]}"
    return s


def format_gstn_period(period: Any) -> str:
    """Format period as MMYYYY (e.g., '2024-10' -> '102024')."""
    s = re.sub(r"[^\w]", "", str(period or "").strip())
    if len(s) == 6:
        # Check if YYYYMM (e.g. 202410)
        if s[:4].isdigit() and int(s[:4]) >= 2017:
            return f"{s[4:6]}{s[:4]}"
        # MMYYYY
        return s
    # YYYY-MM
    p_str = str(period or "").strip()
    if "-" in p_str:
        parts = p_str.split("-")
        if len(parts) >= 2:
            if len(parts[0]) == 4 and len(parts[1]) <= 2:
                return f"{parts[1].zfill(2)}{parts[0]}"
            if len(parts[1]) == 4 and len(parts[0]) <= 2:
                return f"{parts[0].zfill(2)}{parts[1]}"
    now = datetime.now()
    return f"{now.month:02d}{now.year}"


def ca_action_to_gstn_act(action: str | None) -> tuple[str, str]:
    """Map CA action ('accept'|'reject'|'hold'|'pending') to ('Accept'|'Reject'|'Pending', 'A'|'R'|'P')."""
    a = (action or "").strip().lower()
    if a in ("accept", "accepted", "a"):
        return "Accept", "A"
    if a in ("reject", "rejected", "r"):
        return "Reject", "R"
    return "Pending", "P"


def normalize_export_item(item: Any) -> dict[str, Any]:
    """Normalize any recommendation or action row into a unified dict."""
    if hasattr(item, "as_dict"):
        d = item.as_dict()
    elif isinstance(item, dict):
        d = dict(item)
    else:
        d = {}

    rec_act = str(d.get("recommended_action") or "").strip().lower() or "hold"
    chosen_act = str(d.get("chosen_action") or rec_act).strip().lower() or rec_act
    action_label, act_code = ca_action_to_gstn_act(chosen_act)

    wb = d.get("writeback_payload") if isinstance(d.get("writeback_payload"), dict) else {}

    gstin = str(d.get("supplier_gstin") or wb.get("stin") or d.get("stin") or "").strip().upper()
    inum = str(d.get("invoice_number") or wb.get("inum") or d.get("inum") or "").strip()
    idt = str(d.get("invoice_date") or wb.get("idt") or d.get("idt") or "").strip()

    # Tax numbers
    txval = wb.get("txval")
    iamt = wb.get("iamt")
    camt = wb.get("camt")
    samt = wb.get("samt")
    cess = wb.get("cess") or wb.get("csamt")

    amount_paise = d.get("amount_paise") or d.get("amount")
    tot_tax = 0.0
    if iamt is not None or camt is not None or samt is not None:
        tot_tax = round(float(iamt or 0) + float(camt or 0) + float(samt or 0) + float(cess or 0), 2)
    elif amount_paise is not None:
        try:
            tot_tax = round(float(amount_paise) / 100.0, 2)
        except (TypeError, ValueError):
            tot_tax = 0.0

    if txval is not None:
        try:
            txval = round(float(txval), 2)
        except (TypeError, ValueError):
            txval = 0.0
    else:
        txval = 0.0

    val = wb.get("val")
    if val is not None:
        try:
            val = round(float(val), 2)
        except (TypeError, ValueError):
            val = round(txval + tot_tax, 2)
    else:
        val = round(txval + tot_tax, 2)

    pos = str(wb.get("pos") or d.get("pos") or "27").strip()
    rchrg = "Y" if (wb.get("rchrg") in ("Y", True) or d.get("is_rcm")) else "N"
    inv_typ = str(wb.get("inv_typ") or "R").strip() or "R"

    section = str(d.get("section") or wb.get("section") or "b2b").strip().lower()
    if section in ("cn", "cna", "cdnr", "cdnra", "credit_note", "debit_note"):
        section = "cdnr"
    elif section in ("b2ba", "amended_b2b"):
        section = "b2ba"
    else:
        section = "b2b"

    note_type = "C" if (section == "cdnr" and "debit" not in str(d.get("document_type") or "").lower()) else "D"
    if d.get("note_type"):
        note_type = "C" if str(d.get("note_type")).upper().startswith("C") else "D"

    reason_codes = d.get("reason_codes") or []
    if isinstance(reason_codes, (list, tuple)):
        reason_str = " · ".join(str(c) for c in reason_codes)
    else:
        reason_str = str(reason_codes)

    return {
        "invoice_id": str(d.get("invoice_id") or d.get("id") or ""),
        "supplier_gstin": gstin,
        "supplier_name": str(d.get("supplier_name") or wb.get("cpty") or "").strip(),
        "invoice_number": inum,
        "invoice_date": format_gstn_date(idt),
        "section": section,
        "recommended_action": rec_act,
        "chosen_action": chosen_act,
        "action_label": action_label,
        "act_code": act_code,
        "is_override": rec_act != chosen_act,
        "category": str(d.get("category") or "").strip().lower(),
        "confidence_score": d.get("confidence_score") or d.get("match_confidence"),
        "reason_codes": reason_str,
        "why": str(d.get("human_readable_why") or d.get("why") or "").strip(),
        "val": val,
        "txval": txval,
        "iamt": float(iamt or 0),
        "camt": float(camt or 0),
        "samt": float(samt or 0),
        "cess": float(cess or 0),
        "total_tax": tot_tax,
        "pos": pos,
        "rchrg": rchrg,
        "inv_typ": inv_typ,
        "note_type": note_type,
        "original_inum": str(d.get("original_invoice_number") or inum),
        "original_idt": format_gstn_date(d.get("original_invoice_date") or idt),
    }


def build_ims_offline_json(
    buyer_gstin: str,
    period: str,
    items: Sequence[Any],
) -> dict[str, Any]:
    """Generate official GSTN IMS Offline Utility compliant JSON structure."""
    fp = format_gstn_period(period)
    gstin_clean = str(buyer_gstin or "").strip().upper()

    b2b_by_ctin: dict[str, dict[str, Any]] = {}
    cdnr_by_ctin: dict[str, dict[str, Any]] = {}
    b2ba_by_ctin: dict[str, dict[str, Any]] = {}
    cdnra_by_ctin: dict[str, dict[str, Any]] = {}

    for raw in items:
        item = normalize_export_item(raw)
        ctin = item["supplier_gstin"]
        if not ctin or not item["invoice_number"]:
            continue

        sec = item["section"]
        cpty = item["supplier_name"] or None

        # Build standard GSTN line item
        itms = [
            {
                "num": 1,
                "itc_typ": "T",
                "txval": round(item["txval"], 2),
                "iamt": round(item["iamt"], 2),
                "camt": round(item["camt"], 2),
                "samt": round(item["samt"], 2),
                "csamt": round(item["cess"], 2),
            }
        ]

        if sec in ("b2b", "b2ba"):
            inv_entry = {
                "inum": item["invoice_number"],
                "idt": item["invoice_date"],
                "val": round(item["val"], 2),
                "pos": item["pos"],
                "rchrg": item["rchrg"],
                "inv_typ": item["inv_typ"],
                "action": item["action_label"],
                "act": item["act_code"],
                "itms": itms,
            }
            target_map = b2ba_by_ctin if sec == "b2ba" else b2b_by_ctin
            if ctin not in target_map:
                target_map[ctin] = {"ctin": ctin, "cpty": cpty, "inv": []}
            target_map[ctin]["inv"].append(inv_entry)

        elif sec in ("cdnr", "cdnra"):
            nt_entry = {
                "nt_num": item["invoice_number"],
                "nt_dt": item["invoice_date"],
                "ntty": item["note_type"],
                "inum": item["original_inum"],
                "idt": item["original_idt"],
                "val": round(item["val"], 2),
                "pos": item["pos"],
                "rchrg": item["rchrg"],
                "action": item["action_label"],
                "act": item["act_code"],
                "itms": itms,
            }
            target_map = cdnra_by_ctin if sec == "cdnra" else cdnr_by_ctin
            if ctin not in target_map:
                target_map[ctin] = {"ctin": ctin, "cpty": cpty, "nt": []}
            target_map[ctin]["nt"].append(nt_entry)

    return {
        "gstin": gstin_clean,
        "fp": fp,
        "version": "1.0",
        "b2b": list(b2b_by_ctin.values()),
        "cdnr": list(cdnr_by_ctin.values()),
        "b2ba": list(b2ba_by_ctin.values()),
        "cdnra": list(cdnra_by_ctin.values()),
    }


def build_ims_workpaper_excel(
    buyer_gstin: str,
    period: str,
    items: Sequence[Any],
    *,
    client_name: str = "",
    firm_name: str = "",
    generated_by: str = "",
) -> tuple[bytes, str]:
    """Generate multi-sheet CA-Grade IMS Action Audit Workpaper (.xlsx)."""
    norm_items = [normalize_export_item(x) for x in items if x]

    wb = Workbook()
    ws_default = wb.active
    wb.remove(ws_default)

    period_disp = period or "—"
    gstin_disp = (buyer_gstin or "—").upper()
    now_dt = datetime.now(timezone.utc)
    date_disp = now_dt.strftime("%d-%b-%Y %H:%M UTC")

    # ──────────────────────────────────────────────────────────────────────────
    # SHEET 1: IMS Summary
    # ──────────────────────────────────────────────────────────────────────────
    ws1 = wb.create_sheet("IMS Summary", 0)
    ws1.views.sheetView[0].showGridLines = True

    # Title & Metadata
    ws1["A1"] = "ReconDesk — GSTN IMS Action Audit Workpaper"
    ws1["A1"].font = _font_title
    ws1["A2"] = (
        f"Client: {client_name or 'Client'} ({gstin_disp}) | Period: {period_disp} | "
        f"Generated: {date_disp} | CA Firm: {firm_name or 'Statutory Auditor'}"
    )
    ws1["A2"].font = _font_subtitle

    # Compute Statistics
    total_count = len(norm_items)
    accept_items = [x for x in norm_items if x["act_code"] == "A"]
    reject_items = [x for x in norm_items if x["act_code"] == "R"]
    hold_items = [x for x in norm_items if x["act_code"] == "P"]
    overrides = [x for x in norm_items if x["is_override"]]

    tot_txval = sum(x["txval"] for x in norm_items)
    tot_tax = sum(x["total_tax"] for x in norm_items)

    acc_txval = sum(x["txval"] for x in accept_items)
    acc_tax = sum(x["total_tax"] for x in accept_items)

    rej_txval = sum(x["txval"] for x in reject_items)
    rej_tax = sum(x["total_tax"] for x in reject_items)

    hld_txval = sum(x["txval"] for x in hold_items)
    hld_tax = sum(x["total_tax"] for x in hold_items)

    # Risk Rule Discrepancy Breakdown
    rcm_conflict_items = [
        x for x in norm_items if "RCM_FLAG_CONFLICT" in x["reason_codes"] or "rcm" in x["why"].lower()
    ]
    tax_head_mismatch_items = [
        x for x in norm_items if "TAX_HEAD_MISMATCH" in x["reason_codes"] or "tax head" in x["why"].lower()
    ]
    rule37_items = [
        x for x in norm_items if "RULE37_BREACH" in x["reason_codes"] or "180" in x["why"]
    ]
    rule37a_items = [
        x for x in norm_items if "RULE37A" in x["reason_codes"] or "37a" in x["why"].lower()
    ]
    s175_items = [
        x for x in norm_items if "BLOCKED_ITC" in x["reason_codes"] or "17(5)" in x["why"]
    ]
    unmatched_items = [
        x for x in norm_items if "NOT_IN_BOOKS" in x["reason_codes"] or x["category"] == "missed_itc"
    ]

    # Section 1 Header: Action Summary Table
    ws1["A4"] = "1. Proposed IMS Actions & Tax Impact"
    ws1["A4"].font = Font(name="Calibri", size=11, bold=True, color=_NAVY_HEADER)

    summary_headers = [
        "IMS Action Code",
        "Action Status",
        "Invoice Count",
        "% Count",
        "Taxable Value (₹)",
        "Total Tax / ITC (₹)",
        "Audit Disposition & Compliance Impact",
    ]
    for col_idx, h in enumerate(summary_headers, start=1):
        cell = ws1.cell(row=5, column=col_idx, value=h)
        cell.font = _font_hdr
        cell.fill = _fill_hdr
        cell.alignment = _ALIGN_CENTER
        cell.border = _border_cell

    summary_rows_data = [
        (
            "A",
            "ACCEPT",
            len(accept_items),
            f"{(len(accept_items)/total_count*100):.1f}%" if total_count else "0.0%",
            acc_txval,
            acc_tax,
            "Clean matches with Purchase Register. Flow to GSTR-3B Table 4(A)(5).",
            _FILL_ACCEPT,
            _FONT_ACCEPT,
        ),
        (
            "R",
            "REJECT",
            len(reject_items),
            f"{(len(reject_items)/total_count*100):.1f}%" if total_count else "0.0%",
            rej_txval,
            rej_tax,
            "Section 17(5) blocked credit, non-business, or permanent disallowance.",
            _FILL_REJECT,
            _FONT_REJECT,
        ),
        (
            "P",
            "PENDING / HOLD",
            len(hold_items),
            f"{(len(hold_items)/total_count*100):.1f}%" if total_count else "0.0%",
            hld_txval,
            hld_tax,
            "Amount differences, RCM conflicts, tax head mismatches, Rule 37 180-days delay, or unbooked.",
            _FILL_HOLD,
            _FONT_HOLD,
        ),
    ]

    curr_row = 6
    for code, lbl, cnt, pct, tx_v, tot_t, note, fill_c, font_c in summary_rows_data:
        ws1.cell(row=curr_row, column=1, value=code).alignment = _ALIGN_CENTER
        c_lbl = ws1.cell(row=curr_row, column=2, value=lbl)
        c_lbl.font = Font(name="Calibri", size=10, bold=True, color=font_c)
        c_lbl.fill = PatternFill("solid", fgColor=fill_c)
        c_lbl.alignment = _ALIGN_CENTER

        ws1.cell(row=curr_row, column=3, value=cnt).alignment = _ALIGN_RIGHT
        ws1.cell(row=curr_row, column=4, value=pct).alignment = _ALIGN_CENTER

        c_tx = ws1.cell(row=curr_row, column=5, value=f"{tx_v:,.2f}")
        c_tx.alignment = _ALIGN_RIGHT
        c_tx.font = _font_mono

        c_tax = ws1.cell(row=curr_row, column=6, value=f"{tot_t:,.2f}")
        c_tax.alignment = _ALIGN_RIGHT
        c_tax.font = _font_mono

        c_note = ws1.cell(row=curr_row, column=7, value=note)
        c_note.font = _font_regular

        for c_idx in range(1, 8):
            ws1.cell(row=curr_row, column=c_idx).border = _border_cell
        curr_row += 1

    # Total Row
    ws1.cell(row=curr_row, column=1, value="—").alignment = _ALIGN_CENTER
    c_tot = ws1.cell(row=curr_row, column=2, value="TOTAL")
    c_tot.font = _font_bold
    c_tot.alignment = _ALIGN_CENTER
    ws1.cell(row=curr_row, column=3, value=total_count).alignment = _ALIGN_RIGHT
    ws1.cell(row=curr_row, column=3).font = _font_bold
    ws1.cell(row=curr_row, column=4, value="100.0%").alignment = _ALIGN_CENTER
    ws1.cell(row=curr_row, column=4).font = _font_bold

    c_tx_tot = ws1.cell(row=curr_row, column=5, value=f"{tot_txval:,.2f}")
    c_tx_tot.font = _font_bold
    c_tx_tot.alignment = _ALIGN_RIGHT

    c_tax_tot = ws1.cell(row=curr_row, column=6, value=f"{tot_tax:,.2f}")
    c_tax_tot.font = _font_bold
    c_tax_tot.alignment = _ALIGN_RIGHT

    ws1.cell(row=curr_row, column=7, value=f"{len(overrides)} CA manual override(s) applied").font = _font_bold

    for c_idx in range(1, 8):
        ws1.cell(row=curr_row, column=c_idx).border = _border_total
    curr_row += 2

    # Section 2 Header: Statutory & Discrepancy Breakdown
    ws1.cell(row=curr_row, column=1, value="2. Statutory & High-Priority Review Rule Flags").font = Font(
        name="Calibri", size=11, bold=True, color=_NAVY_HEADER
    )
    curr_row += 1

    stat_headers = ["Rule / Discrepancy Category", "Statutory Provision", "Invoices", "Total Tax at Risk (₹)", "Recommended Treatment"]
    for col_idx, h in enumerate(stat_headers, start=1):
        cell = ws1.cell(row=curr_row, column=col_idx, value=h)
        cell.font = _font_hdr
        cell.fill = _fill_subhdr
        cell.alignment = _ALIGN_CENTER
        cell.border = _border_cell
    curr_row += 1

    stat_breakdown = [
        (
            "RCM Flag Conflict",
            "Section 9(3)/9(4) CGST Act",
            len(rcm_conflict_items),
            sum(x["total_tax"] for x in rcm_conflict_items),
            "Hold on IMS; verify reverse charge applicability before filing 3B.",
        ),
        (
            "Tax-Head Mismatch",
            "Section 12/13 IGST Act",
            len(tax_head_mismatch_items),
            sum(x["total_tax"] for x in tax_head_mismatch_items),
            "Hold on IMS; supplier must issue amendment or Credit Note for incorrect Place of Supply.",
        ),
        (
            "Rule 37 180-Day Payment Clock",
            "Second Proviso to Sec 16(2)",
            len(rule37_items),
            sum(x["total_tax"] for x in rule37_items),
            "Hold on IMS until supplier payment is released to prevent interest under Sec 50.",
        ),
        (
            "Rule 37A Supplier Non-Filing",
            "Rule 37A CGST Rules",
            len(rule37a_items),
            sum(x["total_tax"] for x in rule37a_items),
            "Hold on IMS; follow up with vendor to file pending GSTR-3B return.",
        ),
        (
            "Section 17(5) Blocked Credit",
            "Section 17(5) CGST Act",
            len(s175_items),
            sum(x["total_tax"] for x in s175_items),
            "Reject on IMS to officially disallow credit and alert supplier.",
        ),
        (
            "Unbooked / Not in PR (Missed in Books)",
            "Section 16(2)(a) CGST Act",
            len(unmatched_items),
            sum(x["total_tax"] for x in unmatched_items),
            "Hold on IMS; verify goods/services receipt before taking credit in accounting.",
        ),
    ]

    for cat_name, prov, count_val, tax_val, treat in stat_breakdown:
        ws1.cell(row=curr_row, column=1, value=cat_name).font = _font_bold
        ws1.cell(row=curr_row, column=2, value=prov).font = _font_regular
        ws1.cell(row=curr_row, column=3, value=count_val).alignment = _ALIGN_RIGHT
        c_amt = ws1.cell(row=curr_row, column=4, value=f"{tax_val:,.2f}")
        c_amt.font = _font_mono
        c_amt.alignment = _ALIGN_RIGHT
        ws1.cell(row=curr_row, column=5, value=treat).font = _font_regular

        for c_idx in range(1, 6):
            ws1.cell(row=curr_row, column=c_idx).border = _border_cell
        curr_row += 1

    curr_row += 2
    # CA Sign-off Block
    ws1.cell(row=curr_row, column=1, value="3. Auditor Sign-Off & Verification").font = Font(
        name="Calibri", size=11, bold=True, color=_NAVY_HEADER
    )
    curr_row += 1
    ws1.cell(row=curr_row, column=1, value="Prepared By:").font = _font_bold
    ws1.cell(row=curr_row, column=2, value=generated_by or "ReconDesk Audit Engine").font = _font_regular
    ws1.cell(row=curr_row, column=4, value="Partner Sign-off:").font = _font_bold
    ws1.cell(row=curr_row, column=5, value="____________________").font = _font_regular
    curr_row += 1
    ws1.cell(row=curr_row, column=1, value="Portal Batch File:").font = _font_bold
    ws1.cell(row=curr_row, column=2, value=f"IMS_Offline_Actions_{gstin_disp}_{format_gstn_period(period)}.json").font = _font_mono
    ws1.cell(row=curr_row, column=4, value="Upload Date:").font = _font_bold
    ws1.cell(row=curr_row, column=5, value="____-____-202___").font = _font_regular

    _auto_size_ws(ws1)

    # ──────────────────────────────────────────────────────────────────────────
    # SHEET 2: B2B Actions
    # ──────────────────────────────────────────────────────────────────────────
    b2b_list = [x for x in norm_items if x["section"] in ("b2b", "b2ba")]
    ws2 = wb.create_sheet("B2B Actions")
    ws2.views.sheetView[0].showGridLines = True

    b2b_headers = [
        "Supplier GSTIN",
        "Supplier Name",
        "Invoice#",
        "Date",
        "Section",
        "Invoice Value (₹)",
        "Taxable Value (₹)",
        "IGST (₹)",
        "CGST (₹)",
        "SGST (₹)",
        "Cess (₹)",
        "Total Tax (₹)",
        "POS",
        "RCM",
        "Recommended Action",
        "CA Chosen Action",
        "Act Code",
        "Override?",
        "Statutory Rationale & Discrepancy Reason",
    ]

    for col_idx, h in enumerate(b2b_headers, start=1):
        c = ws2.cell(row=1, column=col_idx, value=h)
        c.font = _font_hdr
        c.fill = _fill_hdr
        c.alignment = _ALIGN_CENTER
        c.border = _border_cell
    ws2.freeze_panes = "A2"

    r_idx = 2
    for item in b2b_list:
        ws2.cell(row=r_idx, column=1, value=item["supplier_gstin"]).font = _font_mono
        ws2.cell(row=r_idx, column=2, value=item["supplier_name"]).font = _font_regular
        ws2.cell(row=r_idx, column=3, value=item["invoice_number"]).font = _font_mono
        ws2.cell(row=r_idx, column=4, value=item["invoice_date"]).alignment = _ALIGN_CENTER
        ws2.cell(row=r_idx, column=5, value=item["section"].upper()).alignment = _ALIGN_CENTER

        ws2.cell(row=r_idx, column=6, value=item["val"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=7, value=item["txval"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=8, value=item["iamt"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=9, value=item["camt"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=10, value=item["samt"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=11, value=item["cess"]).number_format = "#,##0.00"
        ws2.cell(row=r_idx, column=12, value=item["total_tax"]).number_format = "#,##0.00"

        ws2.cell(row=r_idx, column=13, value=item["pos"]).alignment = _ALIGN_CENTER
        ws2.cell(row=r_idx, column=14, value=item["rchrg"]).alignment = _ALIGN_CENTER

        # Recommendations & Chosen Action
        c_rec = ws2.cell(row=r_idx, column=15, value=item["recommended_action"].upper())
        c_rec.alignment = _ALIGN_CENTER

        c_act = ws2.cell(row=r_idx, column=16, value=item["action_label"])
        c_act.alignment = _ALIGN_CENTER
        c_act.font = Font(name="Calibri", size=9, bold=True)
        if item["act_code"] == "A":
            c_act.fill = PatternFill("solid", fgColor=_FILL_ACCEPT)
            c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_ACCEPT)
        elif item["act_code"] == "R":
            c_act.fill = PatternFill("solid", fgColor=_FILL_REJECT)
            c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_REJECT)
        else:
            c_act.fill = PatternFill("solid", fgColor=_FILL_HOLD)
            c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_HOLD)

        ws2.cell(row=r_idx, column=17, value=item["act_code"]).alignment = _ALIGN_CENTER
        c_ovr = ws2.cell(row=r_idx, column=18, value="YES" if item["is_override"] else "No")
        c_ovr.alignment = _ALIGN_CENTER
        if item["is_override"]:
            c_ovr.font = Font(name="Calibri", size=9, bold=True, color="B45309")

        why_text = item["why"]
        if item["reason_codes"]:
            why_text = f"[{item['reason_codes']}] {why_text}"
        ws2.cell(row=r_idx, column=19, value=why_text).font = _font_regular

        for c_i in range(1, 20):
            ws2.cell(row=r_idx, column=c_i).border = _border_cell
        r_idx += 1

    _auto_size_ws(ws2)

    # ──────────────────────────────────────────────────────────────────────────
    # SHEET 3: CDNR Actions
    # ──────────────────────────────────────────────────────────────────────────
    cdnr_list = [x for x in norm_items if x["section"] in ("cdnr", "cdnra")]
    ws3 = wb.create_sheet("CDNR Actions")
    ws3.views.sheetView[0].showGridLines = True

    cdnr_headers = [
        "Supplier GSTIN",
        "Supplier Name",
        "Note#",
        "Note Date",
        "Note Type",
        "Original Invoice#",
        "Original Date",
        "Note Value (₹)",
        "Taxable Value (₹)",
        "IGST (₹)",
        "CGST (₹)",
        "SGST (₹)",
        "Cess (₹)",
        "Total Tax (₹)",
        "Recommended Action",
        "CA Chosen Action",
        "Act Code",
        "Override?",
        "Statutory Rationale & Discrepancy Reason",
    ]

    for col_idx, h in enumerate(cdnr_headers, start=1):
        c = ws3.cell(row=1, column=col_idx, value=h)
        c.font = _font_hdr
        c.fill = _fill_hdr
        c.alignment = _ALIGN_CENTER
        c.border = _border_cell
    ws3.freeze_panes = "A2"

    r_idx = 2
    if not cdnr_list:
        ws3.cell(row=2, column=1, value="No Credit or Debit Notes present in this reconciliation period.").font = _font_regular
    else:
        for item in cdnr_list:
            ws3.cell(row=r_idx, column=1, value=item["supplier_gstin"]).font = _font_mono
            ws3.cell(row=r_idx, column=2, value=item["supplier_name"]).font = _font_regular
            ws3.cell(row=r_idx, column=3, value=item["invoice_number"]).font = _font_mono
            ws3.cell(row=r_idx, column=4, value=item["invoice_date"]).alignment = _ALIGN_CENTER
            ws3.cell(row=r_idx, column=5, value="Credit Note" if item["note_type"] == "C" else "Debit Note").alignment = _ALIGN_CENTER

            ws3.cell(row=r_idx, column=6, value=item["original_inum"]).font = _font_mono
            ws3.cell(row=r_idx, column=7, value=item["original_idt"]).alignment = _ALIGN_CENTER

            ws3.cell(row=r_idx, column=8, value=item["val"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=9, value=item["txval"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=10, value=item["iamt"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=11, value=item["camt"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=12, value=item["samt"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=13, value=item["cess"]).number_format = "#,##0.00"
            ws3.cell(row=r_idx, column=14, value=item["total_tax"]).number_format = "#,##0.00"

            c_rec = ws3.cell(row=r_idx, column=15, value=item["recommended_action"].upper())
            c_rec.alignment = _ALIGN_CENTER

            c_act = ws3.cell(row=r_idx, column=16, value=item["action_label"])
            c_act.alignment = _ALIGN_CENTER
            if item["act_code"] == "A":
                c_act.fill = PatternFill("solid", fgColor=_FILL_ACCEPT)
                c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_ACCEPT)
            elif item["act_code"] == "R":
                c_act.fill = PatternFill("solid", fgColor=_FILL_REJECT)
                c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_REJECT)
            else:
                c_act.fill = PatternFill("solid", fgColor=_FILL_HOLD)
                c_act.font = Font(name="Calibri", size=9, bold=True, color=_FONT_HOLD)

            ws3.cell(row=r_idx, column=17, value=item["act_code"]).alignment = _ALIGN_CENTER
            ws3.cell(row=r_idx, column=18, value="YES" if item["is_override"] else "No").alignment = _ALIGN_CENTER

            why_text = item["why"]
            if item["reason_codes"]:
                why_text = f"[{item['reason_codes']}] {why_text}"
            ws3.cell(row=r_idx, column=19, value=why_text).font = _font_regular

            for c_i in range(1, 20):
                ws3.cell(row=r_idx, column=c_i).border = _border_cell
            r_idx += 1

    _auto_size_ws(ws3)

    # Save to buffer
    buf = io.BytesIO()
    wb.save(buf)
    file_bytes = buf.getvalue()
    safe_period = re.sub(r"[^\w\-]+", "_", period_disp).strip("_")
    filename = f"IMS_Action_Workpaper_{gstin_disp}_{safe_period}.xlsx"

    return file_bytes, filename


def _auto_size_ws(ws: Any, max_len_cap: int = 55) -> None:
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = cell.value
            if val is not None:
                line_max = max(len(str(line)) for line in str(val).split("\n"))
                if line_max > max_len:
                    max_len = line_max
        ws.column_dimensions[col_letter].width = min(max_len_cap, max(max_len + 3, 10))
