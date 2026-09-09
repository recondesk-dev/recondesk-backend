"""Official GST-Compliant Tax Invoice PDF Generator using ReportLab.

Generates a standalone PDF tax invoice with full seller/buyer blocks, line items,
tax breakdown, bank details, amount in words, and (if IRP registered) 64-char IRN,
Ack details, and a scannable QR Code. If unsubmitted, displays a clear warning notice.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing, Group

from app.data.gst_uqc import is_valid_uqc
from app.utils.inr_words import paise_total_to_words

logger = logging.getLogger(__name__)

# Official GST State Code Map
STATE_CODE_MAP = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "29": "Karnataka",
    "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu", "34": "Puducherry",
    "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh", "38": "Ladakh",
    "97": "Other Territory", "99": "Other Territory / Overseas",
}


def _get_state_name(code: Optional[str], default_name: str = "") -> str:
    if not code:
        return default_name or "N/A"
    clean = str(code).strip().zfill(2)
    return STATE_CODE_MAP.get(clean, default_name or f"State ({clean})")


def _fmt_paise(paise: Optional[int]) -> str:
    if paise is None:
        return "Rs. 0.00"
    val = float(paise) / 100.0
    return f"Rs. {val:,.2f}"


def _fmt_date(dt_str: Optional[str]) -> str:
    if not dt_str:
        return "N/A"
    try:
        clean = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%d %b %Y")
    except Exception:
        return str(dt_str)[:10]


def _derive_pan(gstin: Optional[str], pan_fallback: Optional[str] = None) -> str:
    if pan_fallback and len(pan_fallback.strip()) == 10:
        return pan_fallback.strip().upper()
    g = str(gstin or "").strip().upper()
    if len(g) >= 12 and g[2:12].isalnum():
        return g[2:12]
    return "N/A"


def _make_qr_drawing(data_str: str, desired_size: float = 110.0) -> Drawing:
    widget = QrCodeWidget(data_str)
    bounds = widget.getBounds()
    w = bounds[2] - bounds[0]
    h = bounds[3] - bounds[1]
    scale = desired_size / max(w, h, 1.0)
    g = Group()
    g.add(widget)
    g.scale(scale, scale)
    d = Drawing(desired_size, desired_size)
    d.add(g)
    return d


def build_gst_invoice_pdf(invoice_detail: Dict[str, Any]) -> bytes:
    """Generate a clean, GST-compliant printable PDF invoice from invoice_detail."""
    buffer = io.BytesIO()

    # Printable A4 document with 1.2 cm margins for rich information density
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    style_title = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0F172A"),
    )

    style_subtitle = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475569"),
    )

    style_heading = ParagraphStyle(
        "SectionHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=3,
    )

    style_body = ParagraphStyle(
        "BodyTextCustom",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11.5,
        textColor=colors.HexColor("#334155"),
    )

    style_body_bold = ParagraphStyle(
        "BodyTextBold",
        parent=style_body,
        fontName="Helvetica-Bold",
        textColor=colors.HexColor("#0F172A"),
    )

    style_table_header = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#0F172A"),
        alignment=1,  # Center
    )

    style_table_cell = ParagraphStyle(
        "TableCell",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=10.5,
        textColor=colors.HexColor("#1E293B"),
    )

    style_table_cell_num = ParagraphStyle(
        "TableCellNum",
        parent=style_table_cell,
        alignment=2,  # Right
    )

    style_table_cell_center = ParagraphStyle(
        "TableCellCenter",
        parent=style_table_cell,
        alignment=1,  # Center
    )

    company = invoice_detail.get("company_profile") or {}
    customer = invoice_detail.get("customer") or {}
    line_items = invoice_detail.get("line_items") or []

    is_cdn = ("note_type" in invoice_detail) or ("note_number" in invoice_detail)
    note_type_str = str(invoice_detail.get("note_type") or "credit").lower()

    if is_cdn:
        doc_kind = "CREDIT NOTE" if note_type_str == "credit" else "DEBIT NOTE"
    else:
        doc_kind = "TAX INVOICE"

    irp_status = str(invoice_detail.get("irp_status") or "").lower()
    irn = invoice_detail.get("irn")
    is_irp_registered = (irp_status == "irp_registered") or bool(irn)

    status_str = str(invoice_detail.get("status") or "").lower()

    story = []

    # -------------------------------------------------------------------------
    # 1. HEADER & DOCUMENT METADATA TABLE
    # -------------------------------------------------------------------------
    if is_irp_registered:
        sub_text = f"<font color='#059669'><b>E-{doc_kind} (IRP REGISTERED)</b></font>"
    elif status_str == "finalized":
        sub_text = f"<font color='#475569'><b>{doc_kind} (FINALIZED — PENDING IRP SUBMISSION)</b></font>"
    else:
        sub_text = f"<font color='#D97706'><b>DRAFT {doc_kind} (UNFINALIZED)</b></font>"

    title_p = Paragraph(f"{company.get('trade_name') or company.get('legal_name') or doc_kind}", style_title)
    subtitle_p = Paragraph(sub_text, style_subtitle)
    header_left = [title_p, Spacer(1, 2), subtitle_p]

    if is_cdn:
        doc_num = invoice_detail.get("note_number") or "CRN/DRAFT"
        doc_date = _fmt_date(invoice_detail.get("note_date"))
        num_label = "Credit Note No:" if note_type_str == "credit" else "Debit Note No:"
        date_label = "Note Date:"
    else:
        doc_num = invoice_detail.get("invoice_number") or "INV/DRAFT"
        doc_date = _fmt_date(invoice_detail.get("invoice_date"))
        num_label = "Invoice No:"
        date_label = "Invoice Date:"

    orig_inv = invoice_detail.get("original_invoice") or {}
    pos_code = str(invoice_detail.get("place_of_supply") or orig_inv.get("place_of_supply") or company.get("state_code") or "").strip()
    pos_name = _get_state_name(pos_code)

    seller_sc = str(company.get("state_code") or "").strip().zfill(2)
    buyer_sc = str(customer.get("state_code") or pos_code).strip().zfill(2)
    is_interstate = (seller_sc != buyer_sc) if (seller_sc and buyer_sc) else False
    tax_type_label = "Interstate (IGST)" if is_interstate else "Intrastate (CGST + SGST)"

    meta_data = [
        [Paragraph(f"<b>{num_label}</b>", style_body), Paragraph(f"<b>{doc_num}</b>", style_body_bold)],
        [Paragraph(f"<b>{date_label}</b>", style_body), Paragraph(doc_date, style_body)],
    ]

    if is_cdn and orig_inv.get("invoice_number"):
        meta_data.append([Paragraph("<b>Original Inv No:</b>", style_body), Paragraph(f"<b>{orig_inv.get('invoice_number')}</b>", style_body_bold)])
        meta_data.append([Paragraph("<b>Original Inv Date:</b>", style_body), Paragraph(_fmt_date(orig_inv.get("invoice_date")), style_body)])
        reason_str = str(invoice_detail.get("reason") or "1-Sales Return")
        if invoice_detail.get("reason_detail"):
            reason_str += f" ({invoice_detail.get('reason_detail')})"
        meta_data.append([Paragraph("<b>Reason:</b>", style_body), Paragraph(reason_str, style_body)])
    else:
        due_date = _fmt_date(invoice_detail.get("due_date")) if invoice_detail.get("due_date") else "N/A"
        meta_data.append([Paragraph("<b>Due Date:</b>", style_body), Paragraph(due_date, style_body)])

    meta_data.append([Paragraph("<b>Place of Supply:</b>", style_body), Paragraph(f"{pos_name} ({pos_code})", style_body)])
    meta_data.append([Paragraph("<b>Tax Regime:</b>", style_body), Paragraph(tax_type_label, style_body)])

    meta_table = Table(meta_data, colWidths=[2.8 * cm, 4.2 * cm])
    meta_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )

    top_table = Table([[header_left, meta_table]], colWidths=[11.5 * cm, 6.7 * cm])
    top_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(top_table)
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceBefore=0, spaceAfter=8))

    # -------------------------------------------------------------------------
    # 2. SELLER & BUYER ADDRESS BLOCKS (SIDE BY SIDE)
    # -------------------------------------------------------------------------
    seller_pan = _derive_pan(company.get("gstin"), company.get("pan"))
    seller_addr = ", ".join(
        filter(None, [
            company.get("address_line1"),
            company.get("address_line2"),
            company.get("city"),
            f"{_get_state_name(company.get('state_code'))} ({company.get('state_code')})" if company.get("state_code") else None,
            company.get("pincode"),
        ])
    )

    seller_lines = [
        Paragraph("<b>SELLER / SUPPLIER DETAILS</b>", style_heading),
        Paragraph(f"<b>{company.get('legal_name') or 'N/A'}</b>", style_body_bold),
        Paragraph(f"<b>GSTIN:</b> {company.get('gstin') or 'N/A'}", style_body),
        Paragraph(f"<b>PAN:</b> {seller_pan}", style_body),
        Paragraph(f"<b>Address:</b> {seller_addr or 'N/A'}", style_body),
    ]

    buyer_gstin_str = customer.get("gstin") or ("Unregistered (URP)" if not customer.get("is_b2b") else "N/A")
    buyer_addr = ", ".join(
        filter(None, [
            customer.get("address_line1"),
            customer.get("address_line2"),
            customer.get("city"),
            f"{_get_state_name(customer.get('state_code'))} ({customer.get('state_code')})" if customer.get("state_code") else None,
            customer.get("pincode"),
        ])
    )

    buyer_lines = [
        Paragraph("<b>BUYER / RECIPIENT DETAILS</b>", style_heading),
        Paragraph(f"<b>{customer.get('name') or 'N/A'}</b>", style_body_bold),
        Paragraph(f"<b>GSTIN:</b> {buyer_gstin_str}", style_body),
        Paragraph(f"<b>Address:</b> {buyer_addr or 'N/A'}", style_body),
    ]

    party_table = Table([[seller_lines, buyer_lines]], colWidths=[9.1 * cm, 9.1 * cm])
    party_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#F8FAFC")),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#F8FAFC")),
            ("BOX", (0, 0), (0, 0), 0.5, colors.HexColor("#E2E8F0")),
            ("BOX", (1, 0), (1, 0), 0.5, colors.HexColor("#E2E8F0")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(party_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 3. LINE ITEMS TABLE
    # -------------------------------------------------------------------------
    if not is_interstate:
        table_headers = ["#", "Item Description", "HSN/SAC", "Qty", "UQC", "Rate (Rs.)", "Taxable (Rs.)", "CGST (Rs.)", "SGST (Rs.)", "Total (Rs.)"]
        col_widths = [0.6 * cm, 4.1 * cm, 1.5 * cm, 1.0 * cm, 1.1 * cm, 2.0 * cm, 2.0 * cm, 1.9 * cm, 1.9 * cm, 2.3 * cm]
    else:
        table_headers = ["#", "Item Description", "HSN/SAC", "Qty", "UQC", "Rate (Rs.)", "Taxable (Rs.)", "IGST Rate", "IGST (Rs.)", "Total (Rs.)"]
        col_widths = [0.6 * cm, 4.3 * cm, 1.5 * cm, 1.0 * cm, 1.1 * cm, 2.0 * cm, 2.2 * cm, 1.4 * cm, 1.9 * cm, 2.3 * cm]

    table_data = [[Paragraph(h, style_table_header) for h in table_headers]]

    for idx, item in enumerate(line_items, start=1):
        desc = item.get("description") or "Item"
        hsn = item.get("hsn_or_sac_code") or "N/A"
        qty = item.get("quantity") or 1
        unit = (item.get("unit") or "NOS").upper()
        rate = _fmt_paise(item.get("rate_paise"))
        taxable = _fmt_paise(item.get("taxable_value_paise"))
        cgst = _fmt_paise(item.get("cgst_paise"))
        sgst = _fmt_paise(item.get("sgst_paise"))
        igst = _fmt_paise(item.get("igst_paise"))
        line_tot = _fmt_paise(item.get("line_total_paise"))
        gst_rate = f"{float(item.get('tax_rate_percent') or 0):g}%"

        if not is_interstate:
            row = [
                Paragraph(str(idx), style_table_cell_center),
                Paragraph(desc, style_table_cell),
                Paragraph(hsn, style_table_cell_center),
                Paragraph(str(qty), style_table_cell_center),
                Paragraph(unit, style_table_cell_center),
                Paragraph(rate, style_table_cell_num),
                Paragraph(taxable, style_table_cell_num),
                Paragraph(cgst, style_table_cell_num),
                Paragraph(sgst, style_table_cell_num),
                Paragraph(line_tot, style_table_cell_num),
            ]
        else:
            row = [
                Paragraph(str(idx), style_table_cell_center),
                Paragraph(desc, style_table_cell),
                Paragraph(hsn, style_table_cell_center),
                Paragraph(str(qty), style_table_cell_center),
                Paragraph(unit, style_table_cell_center),
                Paragraph(rate, style_table_cell_num),
                Paragraph(taxable, style_table_cell_num),
                Paragraph(gst_rate, style_table_cell_center),
                Paragraph(igst, style_table_cell_num),
                Paragraph(line_tot, style_table_cell_num),
            ]
        table_data.append(row)

    items_table = Table(table_data, colWidths=col_widths, repeatRows=1)
    items_table_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    for r in range(1, len(table_data)):
        if r % 2 == 0:
            items_table_style.append(("BACKGROUND", (0, r), (-1, r), colors.HexColor("#F8FAFC")))

    items_table.setStyle(TableStyle(items_table_style))
    story.append(items_table)
    story.append(Spacer(1, 8))

    # -------------------------------------------------------------------------
    # 4. BANK DETAILS & SUMMARY BREAKDOWN
    # -------------------------------------------------------------------------
    bank_info = []
    if company.get("bank_name") or company.get("bank_account_number"):
        bank_info.extend([
            Paragraph("<b>PAYMENT & BANK DETAILS</b>", style_heading),
            Paragraph(f"<b>Bank Name:</b> {company.get('bank_name') or 'N/A'}", style_body),
            Paragraph(f"<b>A/C No:</b> {company.get('bank_account_number') or 'N/A'}", style_body),
            Paragraph(f"<b>IFSC Code:</b> {company.get('bank_ifsc') or 'N/A'}", style_body),
        ])
    if invoice_detail.get("notes"):
        if bank_info:
            bank_info.append(Spacer(1, 4))
        bank_info.extend([
            Paragraph("<b>TERMS & NOTES</b>", style_heading),
            Paragraph(str(invoice_detail.get("notes")), style_body),
        ])
    if not bank_info:
        bank_info.append(Paragraph("<i>Thank you for your business!</i>", style_body))

    subtotal_paise = invoice_detail.get("subtotal_paise") or 0
    total_tax_paise = invoice_detail.get("total_tax_paise") or 0
    grand_total_paise = invoice_detail.get("total_paise") or 0
    amount_in_words = paise_total_to_words(grand_total_paise)

    summary_rows = [
        [Paragraph("Subtotal (Taxable):", style_body), Paragraph(f"<b>{_fmt_paise(subtotal_paise)}</b>", style_table_cell_num)],
    ]

    if not is_interstate:
        total_cgst = sum(i.get("cgst_paise") or 0 for i in line_items)
        total_sgst = sum(i.get("sgst_paise") or 0 for i in line_items)
        summary_rows.append([Paragraph("Total CGST:", style_body), Paragraph(_fmt_paise(total_cgst), style_table_cell_num)])
        summary_rows.append([Paragraph("Total SGST:", style_body), Paragraph(_fmt_paise(total_sgst), style_table_cell_num)])
    else:
        total_igst = sum(i.get("igst_paise") or 0 for i in line_items)
        summary_rows.append([Paragraph("Total IGST:", style_body), Paragraph(_fmt_paise(total_igst), style_table_cell_num)])

    summary_rows.append([Paragraph("<b>Grand Total:</b>", style_heading), Paragraph(f"<font size='10' color='#0F172A'><b>{_fmt_paise(grand_total_paise)}</b></font>", style_table_cell_num)])
    summary_rows.append([Paragraph("<b>Amount in Words:</b>", style_body), Paragraph(f"<i>{amount_in_words}</i>", style_body)])

    summary_subtable = Table(summary_rows, colWidths=[3.5 * cm, 4.5 * cm])
    summary_subtable.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LINEBELOW", (0, -2), (1, -2), 0.5, colors.HexColor("#CBD5E1")),
        ])
    )

    bottom_table = Table([[bank_info, summary_subtable]], colWidths=[10.2 * cm, 8.0 * cm])
    bottom_table.setStyle(
        TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ])
    )
    story.append(bottom_table)
    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 5. IRN & SIGNED QR CODE SECTION (IF REGISTERED) OR UNREGISTERED NOTICE
    # -------------------------------------------------------------------------
    if is_irp_registered:
        irn_str = str(invoice_detail.get("irn") or "N/A")
        ack_no = str(invoice_detail.get("irn_ack_number") or "N/A")
        ack_date = _fmt_date(invoice_detail.get("irn_ack_date"))
        env_label = str(invoice_detail.get("irp_environment") or "TEST/SANDBOX").upper()
        qr_data_str = str(invoice_detail.get("irn_qr_code") or irn_str)

        irn_details = [
            Paragraph("<b>E-INVOICE IRP ACKNOWLEDGEMENT & IRN</b>", style_heading),
            Paragraph(f"<b>IRN:</b> <font fontName='Courier' size='7'>{irn_str}</font>", style_body),
            Paragraph(f"<b>Ack No:</b> {ack_no}", style_body),
            Paragraph(f"<b>Ack Date:</b> {ack_date}", style_body),
            Paragraph(f"<b>Environment:</b> {env_label}", style_body),
        ]

        qr_drawing = _make_qr_drawing(qr_data_str, desired_size=105.0)

        irp_box_table = Table([[irn_details, qr_drawing]], colWidths=[14.2 * cm, 4.0 * cm])
        irp_box_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F0FDF4")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#166534")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(irp_box_table)
    else:
        unsubmitted_notice = [
            Paragraph(
                "<font color='#B45309'>⚠️ <b>NOT YET SUBMITTED TO IRP — NOT A VALID E-INVOICE</b></font>",
                style_heading,
            ),
            Paragraph(
                "This document has been generated internally but has not been registered on the Government Invoice Registration Portal (IRP). It does not contain an official IRN or Signed QR Code.",
                style_body,
            ),
        ]
        irp_box_table = Table([[unsubmitted_notice]], colWidths=[18.2 * cm])
        irp_box_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFFBEB")),
                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#D97706")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ])
        )
        story.append(irp_box_table)

    story.append(Spacer(1, 10))

    # -------------------------------------------------------------------------
    # 6. FOOTER ATTRIBUTION
    # -------------------------------------------------------------------------
    footer_p = Paragraph(
        "<font color='#94A3B8'>Generated via ReconDesk — B2B E-Invoicing & GST Reconciliation Platform (recondesk.in)</font>",
        ParagraphStyle("FooterAttr", parent=styles["Normal"], fontName="Helvetica", fontSize=7.5, alignment=1),
    )
    story.append(footer_p)

    doc.build(story)
    return buffer.getvalue()
