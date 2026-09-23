"""Tax invoice PDF for a payment row (ReportLab) with full B2B GST compliance."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from app.config import settings
from app.utils.inr_words import paise_total_to_words

GST_STATE_MAP = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

DEFAULT_TIER_LIMITS = {
    "free": 2,
    "solo": 25,
    "firm": 75,
    "large_firm": 150,
    "large-firm": 150,
    "starter": 25,
    "growth": 75,
    "pro": 150,
    "monthly": 25,
}


def _fmt_money_paise(paise: int) -> str:
    whole = int(abs(paise) // 100)
    frac = int(abs(paise) % 100)
    sign = "-" if paise < 0 else ""
    return f"{sign}₹{whole:,}.{frac:02d}"


def _format_invoice_date(created_at: Any) -> str:
    dt = created_at
    if isinstance(dt, str):
        try:
            t = dt.replace("Z", "+00:00")
            dt = datetime.fromisoformat(t)
        except ValueError:
            return str(dt)[:12]
    if isinstance(dt, datetime):
        return dt.strftime("%d %b %Y")
    return str(dt)


def invoice_filename_and_number(payment: dict[str, Any]) -> tuple[str, str]:
    """Return (filename, invoice_number)."""
    pid = str(payment.get("id", ""))
    prefix = pid.replace("-", "")[:8].upper()
    yyear = datetime.now().year
    try:
        ca = payment.get("created_at")
        if isinstance(ca, str) and len(ca) >= 4:
            yyear = int(ca[:4])
        elif hasattr(ca, "year"):
            yyear = int(ca.year)
    except (TypeError, ValueError):
        pass
    inv = f"RD-{yyear}-{prefix}"
    return f"ReconDesk-{inv}.pdf", inv


def build_tax_invoice_pdf(payment: dict[str, Any], bill_to: dict[str, str]) -> bytes:
    """Generate a legally compliant GST B2B tax invoice PDF (Section 31 & Rule 46)."""
    _, inv_no = invoice_filename_and_number(payment)

    plan_raw = (payment.get("plan") or "firm").strip().lower()
    cycle_raw = (payment.get("billing_cycle") or "yearly").strip().lower()
    cycle_label = "Annual" if cycle_raw in ("yearly", "annual") else "Monthly"

    gstin_limit = payment.get("gstin_limit") or DEFAULT_TIER_LIMITS.get(plan_raw, 75)
    plan_title = plan_raw.replace("_", " ").replace("-", " ").title()

    base = int(payment.get("base_amount_paise") or payment.get("amount_paise") or 0)
    gst = int(payment.get("gst_paise") or 0)
    total = int(payment.get("total_amount_paise") or payment.get("amount_paise") or (base + gst))
    if gst == 0 and total > base:
        gst = total - base

    # Recipient details
    firm = (
        bill_to.get("firm_name")
        or payment.get("customer_trade_name")
        or "Customer"
    ).strip()
    city = (
        bill_to.get("firm_city")
        or payment.get("customer_city")
        or "—"
    ).strip()
    buyer_gstin = (
        bill_to.get("firm_gstin")
        or bill_to.get("customer_gstin")
        or payment.get("customer_gstin")
        or ""
    ).strip().upper()

    # Determine state and Place of Supply (POS)
    seller_state_code = (getattr(settings, "SELLER_STATE_CODE", "") or "27").strip()
    seller_state_name = (getattr(settings, "SELLER_STATE", "") or "Maharashtra").strip()
    seller_gstin = (getattr(settings, "SELLER_GSTIN", "") or "").strip()
    seller_legal_name = getattr(settings, "SELLER_LEGAL_NAME", "ReconDesk Technologies")
    seller_trade_name = getattr(settings, "SELLER_TRADE_NAME", "ReconDesk")
    seller_address = getattr(settings, "SELLER_ADDRESS", "Hadapsar, Pune, Maharashtra 411028, India")
    sac_code = getattr(settings, "SELLER_SAC_CODE", "998314")

    buyer_state_code = ""
    if len(buyer_gstin) >= 2 and buyer_gstin[:2].isdigit():
        buyer_state_code = buyer_gstin[:2]
    elif bill_to.get("customer_state_code"):
        buyer_state_code = str(bill_to.get("customer_state_code") or "").strip()
    elif payment.get("customer_state_code"):
        buyer_state_code = str(payment.get("customer_state_code") or "").strip()
    else:
        buyer_state_code = seller_state_code  # Default to seller state if unspecified

    buyer_state_name = GST_STATE_MAP.get(buyer_state_code, "Other")
    pos_label = f"{buyer_state_code} - {buyer_state_name}" if buyer_state_code else seller_state_name

    # Determine tax type (Intra vs Inter)
    is_interstate = buyer_state_code != seller_state_code

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Watermark
    c.saveState()
    c.setFont("Helvetica-Bold", 40)
    c.setFillColorRGB(0.92, 0.92, 0.94, alpha=0.35)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "ReconDesk.in")
    c.restoreState()

    # Header
    c.setFillColorRGB(0.1, 0.1, 0.15)
    y = h - 2 * cm

    c.setFont("Helvetica-Bold", 20)
    c.drawString(2 * cm, y, seller_trade_name)

    c.setFont("Helvetica-Bold", 14)
    c.drawRightString(w - 2 * cm, y, "TAX INVOICE")

    y -= 0.6 * cm
    c.setFont("Helvetica", 9)
    c.setFillColorRGB(0.35, 0.35, 0.4)
    c.drawString(2 * cm, y, f"{seller_legal_name} · {seller_address}")
    c.drawRightString(w - 2 * cm, y, "(Original for Recipient)")

    y -= 0.45 * cm
    seller_gst_display = seller_gstin if seller_gstin else "Applied For / Unregistered"
    c.drawString(2 * cm, y, f"GSTIN: {seller_gst_display} | State: {seller_state_name} ({seller_state_code})")

    # Separator rule
    y -= 0.5 * cm
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(1)
    c.line(2 * cm, y, w - 2 * cm, y)

    # Invoice Meta & Bill To Block
    y -= 0.6 * cm
    meta_left_x = 2 * cm
    meta_right_x = w / 2 + 0.5 * cm

    # Left: Bill To
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0.15, 0.15, 0.2)
    c.drawString(meta_left_x, y, "Billed To (Recipient):")
    c.drawString(meta_right_x, y, "Invoice Details:")

    y -= 0.5 * cm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(meta_left_x, y, firm)
    c.setFont("Helvetica", 9)
    c.drawString(meta_right_x, y, f"Invoice No: {inv_no}")

    y -= 0.45 * cm
    gstin_display = buyer_gstin if buyer_gstin else "URP (Unregistered Person)"
    c.drawString(meta_left_x, y, f"GSTIN: {gstin_display}")
    c.drawString(meta_right_x, y, f"Invoice Date: {_format_invoice_date(payment.get('created_at'))}")

    y -= 0.45 * cm
    c.drawString(meta_left_x, y, f"Place of Supply (POS): {pos_label}")
    c.drawString(meta_right_x, y, "Reverse Charge (RCM): No")

    y -= 0.45 * cm
    c.drawString(meta_left_x, y, f"City / Address: {city}")
    c.drawString(meta_right_x, y, f"Supply Type: {'Inter-State (IGST)' if is_interstate else 'Intra-State (CGST+SGST)'}")

    # Line Items Table
    styles = getSampleStyleSheet()
    p_desc = ParagraphStyle(
        name="p_desc",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1E293B"),
    )
    p_sub = ParagraphStyle(
        name="p_sub",
        parent=styles["Normal"],
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor("#64748B"),
    )

    desc_content = f"<b>{plan_title} Plan — {cycle_label} Subscription</b><br/><font color='#64748B'>Full access · Capacity: {gstin_limit} GSTINs · Zero feature gating</font>"

    data = [
        ["#", "Item Description", "SAC", "Taxable (₹)", "Rate", "Amount (₹)"],
        [
            "1",
            Paragraph(desc_content, p_desc),
            sac_code,
            _fmt_money_paise(base),
            "18%",
            _fmt_money_paise(base),
        ],
    ]

    if is_interstate:
        data.extend([
            ["", "", "", "Integrated Tax (IGST)", "18%", _fmt_money_paise(gst)],
        ])
    else:
        half_gst = gst // 2
        data.extend([
            ["", "", "", "Central Tax (CGST)", "9%", _fmt_money_paise(half_gst)],
            ["", "", "", "State Tax (SGST)", "9%", _fmt_money_paise(gst - half_gst)],
        ])

    data.append([
        "",
        "",
        "",
        "Total (Inclusive of GST)",
        "",
        _fmt_money_paise(total),
    ])

    col_widths = [1 * cm, 7.5 * cm, 1.8 * cm, 3.7 * cm, 1.5 * cm, 2.5 * cm]
    t = Table(data, colWidths=col_widths)
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E293B")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 0), (2, -1), "CENTER"),
                ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                ("ALIGN", (4, 0), (4, -1), "CENTER"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
            ]
        )
    )

    y -= 0.8 * cm
    tw, th = t.wrapOn(c, w - 4 * cm, 10 * cm)
    ty = y - th
    t.drawOn(c, 2 * cm, ty)

    # Words and Remarks
    words_y = ty - 0.9 * cm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColorRGB(0.15, 0.15, 0.2)
    c.drawString(2 * cm, words_y, "Invoice Total in Words:")
    c.setFont("Helvetica-Oblique", 8.5)
    c.drawString(6 * cm, words_y, paise_total_to_words(total))

    words_y -= 0.8 * cm
    c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.line(2 * cm, words_y + 0.3 * cm, w - 2 * cm, words_y + 0.3 * cm)

    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(0.2, 0.2, 0.25)
    c.drawString(2 * cm, words_y, "Tax Compliance & Declarations:")
    words_y -= 0.45 * cm
    c.setFont("Helvetica", 7.5)
    c.setFillColorRGB(0.4, 0.4, 0.45)
    c.drawString(
        2 * cm,
        words_y,
        "1. This is a computer-generated tax invoice issued in terms of Section 31 of the CGST Act, 2017 read with Rule 46.",
    )
    words_y -= 0.4 * cm
    c.drawString(
        2 * cm,
        words_y,
        "2. Supply covered under SAC 998314 (Information technology software services). ITC eligible as per Section 16 of CGST Act.",
    )
    words_y -= 0.4 * cm
    c.drawString(
        2 * cm,
        words_y,
        "3. This transaction will be reported in GSTR-1 to enable recipient auto-population in GSTR-2B.",
    )

    # Bottom Signatory block
    sign_y = 2.5 * cm
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColorRGB(0.15, 0.15, 0.2)
    c.drawRightString(w - 2 * cm, sign_y + 0.6 * cm, f"For {seller_legal_name}")
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColorRGB(0.4, 0.4, 0.45)
    c.drawRightString(w - 2 * cm, sign_y, "Authorized Signatory (Digital Authentication)")

    c.showPage()
    c.save()
    return buf.getvalue()
