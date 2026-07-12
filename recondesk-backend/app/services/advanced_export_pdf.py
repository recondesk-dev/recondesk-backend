"""PDF builder for Advanced Export — client-ready report via reportlab."""

from __future__ import annotations

import io
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.advanced_export_service import (
    STATUS_MATCHED,
    AdvancedExportBundle,
    AdvancedExportRow,
    export_filename,
    summarize_rows,
)


def _inr(n: float) -> str:
    return f"Rs {int(round(float(n))):,}"


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(text or "—").replace("\n", "<br/>"), style)


def build_advanced_export_pdf_bytes(
    bundle: AdvancedExportBundle,
    rows: list[AdvancedExportRow],
) -> tuple[bytes, str]:
    """Return (pdf bytes, filename)."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.6 * cm,
        rightMargin=1.6 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "AdvTitle",
        parent=styles["Title"],
        fontSize=16,
        spaceAfter=6,
        textColor=colors.HexColor("#1F4E79"),
    )
    h2 = ParagraphStyle(
        "AdvH2",
        parent=styles["Heading2"],
        fontSize=12,
        spaceBefore=10,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    body = ParagraphStyle(
        "AdvBody",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    )
    small = ParagraphStyle(
        "AdvSmall",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#444444"),
    )
    label = ParagraphStyle(
        "AdvLabel",
        parent=styles["Normal"],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#1F4E79"),
        fontName="Helvetica-Bold",
    )

    story: list[Any] = []
    story.append(Paragraph("Reconciliation Advanced Export Report", title_style))
    story.append(
        _p(f"Client: {bundle.client_name or '—'}", body)
    )
    story.append(_p(f"Period: {bundle.period or '—'}", body))
    story.append(
        _p(
            f"Generated: {bundle.generated_at.strftime('%d %b %Y %H:%M UTC')}"
            + (f" by {bundle.generated_by}" if bundle.generated_by else ""),
            small,
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    summary = summarize_rows(rows)
    story.append(Paragraph("Summary", h2))

    summary_data = [["Metric", "Value"]]
    summary_data.append(["Filtered rows", str(summary["total_rows"])])
    for status, count in summary["count_by_status"].items():
        summary_data.append([f"Status — {status}", str(count)])
    for cat, count in summary["count_by_itc_category"].items():
        summary_data.append([f"ITC eligibility — {cat}", str(count)])
    summary_data.append(
        ["Total ITC at Risk", _inr(summary["total_itc_at_risk"])]
    )
    summary_data.append(
        ["Total Missed ITC", _inr(summary["total_missed_itc"])]
    )

    summary_table = Table(summary_data, colWidths=[10 * cm, 6 * cm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f5f7fa")],
                ),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.6 * cm))

    # Flagged items: prefer non-matched; fall back to all filtered rows.
    flagged = [r for r in rows if r.status != STATUS_MATCHED]
    detail_rows = flagged if flagged else rows

    story.append(
        Paragraph(
            "Flagged Item Details" if flagged else "Filtered Item Details",
            h2,
        )
    )
    if not detail_rows:
        story.append(_p("No rows matched the selected filters.", body))
    else:
        # Cap detail blocks to keep PDFs manageable for large exports.
        max_detail = 200
        for idx, row in enumerate(detail_rows[:max_detail], 1):
            block = [
                _p(
                    f"{idx}. [{row.status}] {row.invoice_number or '—'} — "
                    f"{row.vendor_name or row.supplier_gstin or 'Unknown vendor'}",
                    label,
                ),
                _p(
                    f"GSTIN: {row.supplier_gstin or '—'}  |  Date: {row.invoice_date or '—'}  |  "
                    f"Taxable: {_inr(row.taxable_value)}  |  ITC: {_inr(row.itc_amount)}  |  "
                    f"ITC eligibility: {row.itc_eligibility_category}",
                    small,
                ),
                _p(f"WHAT: {row.decision_what or '—'}", body),
                _p(f"WHY: {row.decision_why or '—'}", body),
                _p(f"NEXT: {row.decision_next or '—'}", body),
                Spacer(1, 0.25 * cm),
            ]
            story.append(KeepTogether(block))
        if len(detail_rows) > max_detail:
            story.append(
                _p(
                    f"Showing first {max_detail} of {len(detail_rows)} items. "
                    "Export to Excel for the full list.",
                    small,
                )
            )

    doc.build(story)
    return buffer.getvalue(), export_filename(bundle, "pdf")
