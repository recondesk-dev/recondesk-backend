import io
from datetime import datetime
from typing import Any, Dict, List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_reconciliation_pdf(
    job_name: str,
    summary: Dict[str, Any],
    rows: List[Dict[str, Any]],
    generated_by: str = "ReconDesk",
) -> bytes:
    """Generate a PDF report for a reconciliation job and return raw bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph(f"Reconciliation Report: {job_name}", styles["Title"]))
    story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    # Summary table
    summary_data = [
        ["Metric", "Count"],
        ["Total Rows", summary.get("total", 0)],
        ["Matched", summary.get("matched", 0)],
        ["Partial Match", summary.get("partial", 0)],
        ["Unmatched", summary.get("unmatched", 0)],
    ]
    summary_table = Table(summary_data, colWidths=[8 * cm, 4 * cm])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
            ]
        )
    )
    story.append(summary_table)
    story.append(Spacer(1, 0.8 * cm))

    # Row-level detail (first 100 rows to keep PDF manageable)
    if rows:
        story.append(Paragraph("Row Details (first 100 rows)", styles["Heading2"]))
        header = ["#", "Status", "Match Score", "Discrepancies"]
        table_data = [header]
        for row in rows[:100]:
            discrep = ", ".join(row.get("discrepancies", {}).keys()) if row.get("discrepancies") else "—"
            table_data.append(
                [
                    row.get("row_index", ""),
                    row.get("match_status", ""),
                    f"{row.get('match_score', 0):.2%}" if row.get("match_score") is not None else "—",
                    discrep,
                ]
            )
        detail_table = Table(table_data, colWidths=[1.5 * cm, 4 * cm, 3 * cm, 8 * cm])
        detail_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f9f9f9")]),
                ]
            )
        )
        story.append(detail_table)

    doc.build(story)
    return buffer.getvalue()
