"""Regenerate bundled first-login demo GSTR-2B + Purchase Register fixtures.

Usage (from repo root or backend root):
    python recondesk-backend/scripts/generate_demo_tour_data.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parents[1] / "app" / "demo_data"
BUYER = "27DEMOC0001A1ZJ"
PERIOD = "042026"
PERIOD_LABEL = "Apr-2026"


def gstin_checksum(gstin14: str) -> str:
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    factor = 1
    total = 0
    for c in gstin14:
        code = chars.index(c)
        product = code * factor
        q, r = divmod(product, 36)
        total += q + r
        factor = 2 if factor == 1 else 1
    return chars[(36 - (total % 36)) % 36]


RAW_SUPPLIERS = [
    ("27AAACR5055K1Z7", "Reliable Office Supplies Pvt Ltd"),
    ("27AADCS0472N1Z1", "Shree Tech Services"),
    ("27AAECS1234F1Z2", "Metro Cloud Solutions"),
    ("27AACCM9910C1Z8", "RD Logistics"),
    ("27AABCT3518Q1ZX", "Tally Data Processors"),
    ("27AAHCR8765L1Z9", "Royal Motors Garage"),
    ("27AAFP9999X1Z1", "Prime Stationery Mart"),
    ("27AAICP2468D1ZA", "Prime Office Interiors"),
    ("27AAKFC3210M1Z4", "Carbon Fuels Corporation"),
    ("27AABCU9603R1ZX", "Urban Packers India"),
]

SUPPLIERS = [(g[:14] + gstin_checksum(g[:14]), n) for g, n in RAW_SUPPLIERS]


def main() -> None:
    invoices: list[dict] = []

    def add(
        scenario: str,
        si: int,
        inum: str,
        idt: date,
        taxable: int,
        igst: int,
        cgst: int,
        sgst: int,
        *,
        in_gstr: bool = True,
        in_pr: bool = True,
        unpaid: bool = False,
    ) -> None:
        invoices.append(
            {
                "scenario": scenario,
                "si": si,
                "inum": inum,
                "idt": idt,
                "taxable": taxable,
                "igst": igst,
                "cgst": cgst,
                "sgst": sgst,
                "in_gstr": in_gstr,
                "in_pr": in_pr,
                "unpaid": unpaid,
            }
        )

    add("CLEAN", 0, "INV-001", date(2026, 4, 3), 10000, 0, 900, 900)
    add("CLEAN", 1, "INV-002", date(2026, 4, 5), 5000, 0, 450, 450)
    add("CLEAN", 2, "INV-003", date(2026, 4, 7), 20000, 3600, 0, 0)
    add("CLEAN", 3, "INV-004", date(2026, 4, 9), 7000, 0, 630, 630)
    add("CLEAN", 4, "INV-005", date(2026, 4, 12), 15000, 0, 1350, 1350)
    add("CLEAN", 5, "INV-006", date(2026, 4, 14), 8000, 0, 720, 720)
    add("CLEAN", 6, "INV-007", date(2026, 4, 16), 4500, 0, 405, 405)
    add("CLEAN", 9, "INV-008", date(2026, 4, 18), 12000, 0, 1080, 1080)
    add("CLEAN", 0, "INV-009", date(2026, 4, 20), 6000, 0, 540, 540)
    add("CLEAN", 1, "INV-010", date(2026, 4, 21), 9000, 0, 810, 810)
    add("CLEAN", 2, "INV-011", date(2026, 4, 22), 11000, 1980, 0, 0)
    add("CLEAN", 3, "INV-012", date(2026, 4, 23), 3500, 0, 315, 315)
    # MISSED_ITC — GSTR-2B only
    add(
        "MISSED_ITC",
        4,
        "INV-MISS-01",
        date(2026, 4, 10),
        25000,
        0,
        2250,
        2250,
        in_pr=False,
    )
    # RULE37_OVERDUE — unpaid >180 days
    add(
        "RULE37_OVERDUE",
        7,
        "INV-R37-01",
        date(2025, 9, 15),
        18000,
        0,
        1620,
        1620,
        unpaid=True,
    )
    add("CLEAN", 8, "INV-013", date(2026, 4, 24), 22000, 3960, 0, 0)
    add("CLEAN", 9, "INV-014", date(2026, 4, 25), 5500, 0, 495, 495)
    add("CLEAN", 0, "INV-015", date(2026, 4, 26), 7500, 0, 675, 675)
    add("CLEAN", 1, "INV-016", date(2026, 4, 27), 4100, 0, 369, 369)
    add("CLEAN", 2, "INV-017", date(2026, 4, 28), 13000, 2340, 0, 0)

    by_ctin: dict[tuple[str, str], list] = defaultdict(list)
    for inv in invoices:
        if not inv["in_gstr"]:
            continue
        ctin, trdnm = SUPPLIERS[inv["si"]]
        by_ctin[(ctin, trdnm)].append(inv)

    b2b = []
    for (ctin, trdnm), invs in by_ctin.items():
        entry = {
            "ctin": ctin,
            "trdnm": trdnm,
            "supfildt": "11-05-2026",
            "supprd": PERIOD,
            "inv": [],
        }
        for inv in invs:
            val = inv["taxable"] + inv["igst"] + inv["cgst"] + inv["sgst"]
            entry["inv"].append(
                {
                    "inum": inv["inum"],
                    "idt": inv["idt"].strftime("%d-%m-%Y"),
                    "val": float(val),
                    "pos": "27",
                    "rchrg": "N",
                    "inv_typ": "R",
                    "itcavl": "Y",
                    "rsn": "",
                    "itms": [
                        {
                            "num": 1,
                            "itm_det": {
                                "rt": 18.0,
                                "txval": float(inv["taxable"]),
                                "iamt": float(inv["igst"]),
                                "camt": float(inv["cgst"]),
                                "samt": float(inv["sgst"]),
                                "csamt": 0.0,
                            },
                        }
                    ],
                }
            )
        b2b.append(entry)

    gstr = {
        "status_cd": "1",
        "data": {
            "gstin": BUYER,
            "rtnprd": PERIOD,
            "fp": PERIOD,
            "version": "ReconDesk-Demo-1.0",
            "gendt": "14-05-2026",
            "docdata": {"b2b": b2b},
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "demo_gstr_2b.json").write_text(json.dumps(gstr, indent=2))

    headers = [
        "Recipient GSTIN",
        "Supplier GSTIN",
        "Supplier Name",
        "Document Type",
        "Invoice No",
        "Invoice Date",
        "Taxable Value",
        "IGST",
        "CGST",
        "SGST",
        "CESS",
        "Total GST",
        "Invoice Value",
        "Filing Period",
        "GSTR-1 Filing Date",
        "Reverse Charge",
        "ITC Availability",
        "Payment Status",
        "Payment Date",
        "Reason",
    ]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Purchase Register"
    ws.append(headers)
    for inv in invoices:
        if not inv["in_pr"]:
            continue
        ctin, trdnm = SUPPLIERS[inv["si"]]
        total_gst = inv["igst"] + inv["cgst"] + inv["sgst"]
        val = inv["taxable"] + total_gst
        if inv["unpaid"]:
            pay_status, pay_date = "Unpaid", None
        else:
            pay_status = "Paid"
            pay_date = inv["idt"] + timedelta(days=25)
        ws.append(
            [
                BUYER,
                ctin,
                trdnm,
                "Invoice",
                inv["inum"],
                inv["idt"],
                inv["taxable"],
                inv["igst"],
                inv["cgst"],
                inv["sgst"],
                0,
                total_gst,
                val,
                PERIOD_LABEL,
                date(2026, 5, 11),
                "No",
                "Yes",
                pay_status,
                pay_date,
                inv["scenario"],
            ]
        )
    for col in ("F", "O", "S"):
        for cell in ws[col][1:]:
            if cell.value is not None:
                cell.number_format = "DD-MM-YYYY"
    wb.save(OUT / "demo_purchase_register.xlsx")

    manifest = {
        "buyer_gstin": BUYER,
        "trade_name": "Demo Client - Sample Reconciliation",
        "legal_name": "Demo Client - Sample Reconciliation",
        "period": "2026-04",
        "gstr_file": "demo_gstr_2b.json",
        "pr_file": "demo_purchase_register.xlsx",
        "scenarios": {
            "clean_match": "INV-001",
            "missed_itc": "INV-MISS-01",
            "rule37_overdue": "INV-R37-01",
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        f"Wrote demo pack to {OUT} "
        f"(gstr={sum(len(s['inv']) for s in b2b)} inv, "
        f"pr={sum(1 for i in invoices if i['in_pr'])} rows)"
    )


if __name__ == "__main__":
    main()
