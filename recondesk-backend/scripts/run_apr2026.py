from __future__ import annotations

import json
import sys
import datetime
from datetime import date

import openpyxl

from app.services.matcher import normalize_invoice
from app.services.reconciliation import run_bidirectional_reconciliation
from app.services.reconciliation_debug import build_debug_report, print_debug_report
from scripts.stress_repro import _to_paise

def _iso(dmy) -> str | None:
    if not dmy:
        return None
    if isinstance(dmy, (datetime.date, datetime.datetime)):
        return dmy.strftime("%Y-%m-%d")
    s = str(dmy).strip()
    s = s.split(" ")[0]
    for sep in ("-", "/"):
        if sep in s:
            parts = s.split(sep)
            if len(parts) == 3:
                if len(parts[0]) == 4:
                    return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                else:
                    return f"{int(parts[2]):04d}-{int(parts[1]):02d}-{int(parts[0]):02d}"
    return s

def load_gstr_rows(path: str) -> list[dict]:
    with open(path) as fh:
        doc = json.load(fh)
    rows: list[dict] = []
    data = doc.get("data", {}).get("docdata", {})
    idx = 0
    for sup in data.get("b2b", []):
        ctin = sup.get("ctin")
        name = sup.get("trdnm")
        for inv in sup.get("inv", []):
            idx += 1
            itms = inv.get("items", [])
            txval = sum(_to_paise(i.get("txval")) for i in itms)
            cgst = sum(_to_paise(i.get("cgst")) for i in itms)
            sgst = sum(_to_paise(i.get("sgst")) for i in itms)
            igst = sum(_to_paise(i.get("igst")) for i in itms)
            cess = sum(_to_paise(i.get("cess")) for i in itms)
            rows.append(
                {
                    "id": f"g{idx}",
                    "supplier_gstin": ctin,
                    "supplier_name": name,
                    "invoice_number": inv.get("inum"),
                    "invoice_number_normalized": normalize_invoice(inv.get("inum")),
                    "invoice_date": _iso(inv.get("dt")),
                    "taxable_amount_paise": txval,
                    "cgst_paise": cgst,
                    "sgst_paise": sgst,
                    "igst_paise": igst,
                    "total_tax_paise": cgst + sgst + igst + cess,
                }
            )
    return rows

def load_pr_rows(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Purchase_Register"]
    header = None
    rows: list[dict] = []
    idx = 0
    for row in ws.iter_rows(values_only=True):
        if header is None:
            header = list(row)
            continue
        if all(c is None for c in row):
            continue
        rec = dict(zip(header, row))
        idx += 1
        cgst = _to_paise(rec.get("CGST"))
        sgst = _to_paise(rec.get("SGST"))
        igst = _to_paise(rec.get("IGST"))
        rows.append(
            {
                "id": f"p{idx}",
                "supplier_gstin": rec.get("Supplier GSTIN"),
                "vendor_name": rec.get("Supplier Name"),
                "invoice_number": rec.get("Invoice Number"),
                "invoice_number_normalized": normalize_invoice(rec.get("Invoice Number")),
                "invoice_date": _iso(rec.get("Invoice Date")),
                "taxable_amount_paise": _to_paise(rec.get("Taxable Value")),
                "cgst_paise": cgst,
                "sgst_paise": sgst,
                "igst_paise": igst,
                "total_tax_paise": cgst + sgst + igst,
            }
        )
    return rows

def main() -> None:
    gstr_path = sys.argv[1]
    pr_path = sys.argv[2]
    gstr_rows = load_gstr_rows(gstr_path)
    pr_rows = load_pr_rows(pr_path)

    for r in gstr_rows:
        r["invoice_date"] = _iso(r["invoice_date"])

    result = run_bidirectional_reconciliation(
        gstr_rows, pr_rows, gstr_period=date(2026, 4, 1)
    )

    report = build_debug_report(result, gstr_rows, pr_rows)
    print_debug_report(report)

if __name__ == "__main__":
    main()
