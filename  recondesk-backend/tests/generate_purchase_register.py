"""
Purchase Register test file generator.

Builds a synthetic Purchase Register Excel workbook whose rows are tagged by
reconciliation scenario. Column headers match the aliases recognised by
``app/parsers/purchase_register_parser.py`` so the output is directly parseable.

Payment columns ("Payment Status" / "Payment Date") are derived from each row's
scenario:

    CLEAN_MATCH     -> Paid,   Payment Date = invoice_date + random(10..60) days
    BLOCKED_CREDIT  -> Paid,   Payment Date = invoice_date + random(10..60) days
    WRONGFUL_ITC    -> Paid,   Payment Date = invoice_date + random(10..60) days
    RULE37          -> Unpaid, Payment Date = blank

Run:
    python tests/generate_purchase_register.py
"""
import random
from datetime import date, timedelta

import openpyxl

OUTPUT_PATH = "tests/synthetic_purchase_register.xlsx"

# Deterministic output so regenerating the fixture produces a stable diff.
random.seed(20260607)

# Column order. "Payment Status" and "Payment Date" are inserted immediately
# after "Total Invoice Value", and their headers match the parser aliases
# ("payment status" / "payment date").
HEADERS = [
    "Supplier GSTIN",
    "Supplier Name",
    "Invoice No",
    "Invoice Date",
    "Taxable Value",
    "IGST",
    "CGST",
    "SGST",
    "Total Invoice Value",
    "Payment Status",
    "Payment Date",
]

# Scenario constants.
CLEAN_MATCH = "CLEAN_MATCH"
BLOCKED_CREDIT = "BLOCKED_CREDIT"
WRONGFUL_ITC = "WRONGFUL_ITC"
RULE37 = "RULE37"

# Scenarios whose invoices are treated as paid (payment date populated).
_PAID_SCENARIOS = frozenset({CLEAN_MATCH, BLOCKED_CREDIT, WRONGFUL_ITC})


# Each invoice carries its scenario tag; payment columns are derived from it.
PR_RECORDS = [
    {"scenario": CLEAN_MATCH, "supplier_gstin": "27AAACR5055K1Z7",
     "supplier_name": "Reliable Office Supplies Pvt Ltd", "invoice_no": "INV-001",
     "invoice_date": date(2026, 4, 3), "taxable": 10000, "igst": 0, "cgst": 900, "sgst": 900},
    {"scenario": CLEAN_MATCH, "supplier_gstin": "27AADCS0472N1Z1",
     "supplier_name": "Shree Tech Services", "invoice_no": "INV-002",
     "invoice_date": date(2026, 4, 5), "taxable": 5000, "igst": 0, "cgst": 450, "sgst": 450},
    {"scenario": CLEAN_MATCH, "supplier_gstin": "27AAECS1234F1Z2",
     "supplier_name": "Metro Cloud Solutions", "invoice_no": "INV-003",
     "invoice_date": date(2026, 4, 7), "taxable": 20000, "igst": 3600, "cgst": 0, "sgst": 0},

    {"scenario": BLOCKED_CREDIT, "supplier_gstin": "27AAHCR8765L1Z9",
     "supplier_name": "Royal Motors Garage", "invoice_no": "INV-008",
     "invoice_date": date(2026, 4, 16), "taxable": 40000, "igst": 0, "cgst": 3600, "sgst": 3600},

    {"scenario": WRONGFUL_ITC, "supplier_gstin": "27AAFP9999X1Z1",
     "supplier_name": "PR Only Stationery Mart", "invoice_no": "INV-006",
     "invoice_date": date(2026, 4, 15), "taxable": 2500, "igst": 0, "cgst": 225, "sgst": 225},
    {"scenario": WRONGFUL_ITC, "supplier_gstin": "27AABCT3518Q1ZX",
     "supplier_name": "Tally Data Processors", "invoice_no": "INV-012",
     "invoice_date": date(2026, 4, 18), "taxable": 12000, "igst": 0, "cgst": 1080, "sgst": 1080},

    {"scenario": RULE37, "supplier_gstin": "27AAICP2468D1ZA",
     "supplier_name": "Prime Office Interiors", "invoice_no": "INV-009",
     "invoice_date": date(2025, 9, 15), "taxable": 11000, "igst": 0, "cgst": 990, "sgst": 990},
    {"scenario": RULE37, "supplier_gstin": "27AAKFC3210M1Z4",
     "supplier_name": "Carbon Fuels Corporation", "invoice_no": "INV-011",
     "invoice_date": date(2025, 10, 2), "taxable": 40000, "igst": 7200, "cgst": 0, "sgst": 0},
]


def _payment_fields(scenario: str, invoice_date: date):
    """Return ``(payment_status, payment_date)`` for a scenario.

    Paid scenarios get a payment date of invoice_date + random 10..60 days.
    Rule 37 invoices stay unpaid with a blank payment date.
    """
    if scenario in _PAID_SCENARIOS:
        return "Paid", invoice_date + timedelta(days=random.randint(10, 60))
    return "Unpaid", None


def build_rows():
    rows = []
    for rec in PR_RECORDS:
        total = rec["taxable"] + rec["igst"] + rec["cgst"] + rec["sgst"]
        payment_status, payment_date = _payment_fields(
            rec["scenario"], rec["invoice_date"]
        )
        rows.append([
            rec["supplier_gstin"],
            rec["supplier_name"],
            rec["invoice_no"],
            rec["invoice_date"],
            rec["taxable"],
            rec["igst"],
            rec["cgst"],
            rec["sgst"],
            total,
            payment_status,
            payment_date,
        ])
    return rows


def main():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append(HEADERS)
    for row in build_rows():
        ws.append(row)
    for cell in ws["D"][1:]:  # Invoice Date
        cell.number_format = "DD-MM-YYYY"
    for cell in ws["K"][1:]:  # Payment Date
        if cell.value is not None:
            cell.number_format = "DD-MM-YYYY"
    wb.save(OUTPUT_PATH)
    print(f"Wrote {len(PR_RECORDS)} rows to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
