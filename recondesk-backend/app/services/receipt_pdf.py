"""Tax invoice PDF for a payment row (ReportLab)."""

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

from app.utils.inr_words import paise_total_to_words

# When registered, replace via env or config
GSTIN_PLACEHOLDER = "[YOUR_GSTIN_PLACEHOLDER]"
SELLER_ADDRESS = "Hadapsar, Pune, India — recondesk.in"


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
    """*payment* from DB; *bill_to* has firm_name, firm_city."""
    _, inv_no = invoice_filename_and_number(payment)

    plan_raw = (payment.get("plan") or "starter").strip().lower()
    runs = int(payment.get("runs_purchased") or 0)
    base = int(payment.get("base_amount_paise") or payment.get("amount_paise") or 0)
    gst = int(payment.get("gst_paise") or 0)
    total = int(payment.get("total_amount_paise") or payment.get("amount_paise") or base + gst)
    if gst == 0 and total > base:
        gst = total - base
    half_gst = gst // 2

    firm = (bill_to.get("firm_name") or "Customer").strip()
    city = (bill_to.get("firm_city") or "—").strip()

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    # Watermark
    c.saveState()
    c.setFont("Helvetica-Bold", 44)
    c.setFillColorRGB(0.9, 0.9, 0.9, alpha=0.35)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "ReconDesk.in")
    c.restoreState()

    c.setFillColorRGB(0, 0, 0)
    y = h - 2 * cm
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, y, "ReconDesk")
    y -= 0.7 * cm
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, y, "Tax Invoice")
    y -= 1 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, SELLER_ADDRESS)
    y -= 0.45 * cm
    c.drawString(2 * cm, y, f"GSTIN: {GSTIN_PLACEHOLDER}")
    y -= 0.8 * cm
    c.drawString(2 * cm, y, f"Invoice number: {inv_no}")
    y -= 0.45 * cm
    c.drawString(
        2 * cm,
        y,
        f"Invoice date: {_format_invoice_date(payment.get('created_at'))}",
    )
    y -= 1 * cm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, y, "Bill to")
    y -= 0.45 * cm
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, y, firm)
    y -= 0.4 * cm
    c.drawString(2 * cm, y, city)

    # Line items as platypus table on overlay — simpler: draw table with reportlab Table in separate flowable
    styles = getSampleStyleSheet()
    p_small = ParagraphStyle(
        name="small",
        parent=styles["Normal"],
        fontSize=9,
        leading=11,
    )

    desc = f"GSTR-2B Reconciliation Runs — {plan_raw.title()} Plan ({runs} runs)"
    data = [
        ["Description", "HSN/SAC", "Amount (₹)"],
        [Paragraph(desc, p_small), "998314", _fmt_money_paise(base)],
        ["", "CGST 9%", _fmt_money_paise(half_gst)],
        ["", "SGST 9%", _fmt_money_paise(gst - half_gst)],
        ["", "Total (incl. GST)", _fmt_money_paise(total)],
    ]
    t = Table(data, colWidths=[8.5 * cm, 3 * cm, 4 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ]
        )
    )
    tw, th = t.wrapOn(c, w - 4 * cm, 10 * cm)
    ty = h - 10 * cm - th
    t.drawOn(c, 2 * cm, ty)

    words_y = ty - 1 * cm
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(
        2 * cm,
        words_y,
        f"Amount in words: {paise_total_to_words(total)}",
    )
    words_y -= 0.7 * cm
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.25, 0.25, 0.25)
    c.drawString(
        2 * cm,
        words_y,
        "Runs valid for 6 months from purchase date. Unused runs are non-refundable.",
    )
    words_y -= 0.6 * cm
    c.drawString(
        2 * cm,
        words_y,
        "Computer-generated invoice — no signature required",
    )

    c.showPage()
    c.save()
    return buf.getvalue()
