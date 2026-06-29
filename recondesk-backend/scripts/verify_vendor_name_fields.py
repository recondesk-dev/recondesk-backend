"""
Sanity check: verify that gstr_db_row_to_matcher_row() and
pr_db_row_to_matcher_row() both produce non-empty vendor name fields.

Uses the sample GSTR-2B fixture in test_fixtures/ and a synthetic PR row
that matches what the PR parser produces.

Run from recondesk-backend/:
    python3 scripts/verify_vendor_name_fields.py
"""

import json
import sys
import os

# Make sure app is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parsers.gstr2b_parser import parse_gstr2b
from app.services.reconciliation_record_adapter import (
    gstr_db_row_to_matcher_row,
    pr_db_row_to_matcher_row,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__),
    "../test_fixtures/reconciliation/recondesk-sample-gstr-2b.json",
)

# ── GSTR side ─────────────────────────────────────────────────────────────
with open(FIXTURE) as fh:
    raw = json.load(fh)

result = parse_gstr2b(raw)
records = result["records"]

print(f"Parsed {len(records)} GSTR-2B records from fixture.\n")
print("GSTR matcher rows (first 5):")
print(f"  {'id':<6}  {'supplier_name':<40}  {'invoice_number'}")
print("  " + "-" * 70)

empty_names = 0
for rec in records[:5]:
    fake_row = {"id": rec.get("unique_key", "?"), "record_data": rec}
    mr = gstr_db_row_to_matcher_row(fake_row)
    sname = mr.get("supplier_name", "")
    if not sname:
        empty_names += 1
    print(f"  {str(mr['id'])[:6]:<6}  {sname:<40}  {mr.get('invoice_number', '')}")

print()
if empty_names:
    print(f"  ⚠️  WARNING: {empty_names} GSTR rows have empty supplier_name!")
else:
    print("  ✅  All GSTR rows have non-empty supplier_name.")

# ── PR side ───────────────────────────────────────────────────────────────
pr_samples = [
    {
        "id": "pr-1",
        "record_data": {
            "gstin": "27AAACR5055K1Z7",
            "supplier_name": "Reliable Office Supplies Pvt Ltd",
            "invoice_number": "INV-001",
            "invoice_number_normalized": "INV001",
            "invoice_date": "2026-04-03",
            "taxable_amount_paise": 1_000_000,
            "igst_paise": 0,
            "cgst_paise": 90_000,
            "sgst_paise": 90_000,
            "total_tax_paise": 180_000,
        },
    },
    {
        "id": "pr-2",
        "record_data": {
            "gstin": "27AADCS0472N1Z1",
            "supplier_name": "Shree Tech Services",
            "invoice_number_normalized": "INV002",
            "invoice_date": "2026-04-05",
            "taxable_amount_paise": 500_000,
            "igst_paise": 90_000,
            "cgst_paise": 0,
            "sgst_paise": 0,
            "total_tax_paise": 90_000,
        },
    },
    {
        "id": "pr-3",
        "record_data": {
            # No supplier_name at all — should come through as ""
            "gstin": "27AADCM3467H1Z5",
            "invoice_number_normalized": "INV003",
            "invoice_date": "2026-04-08",
            "taxable_amount_paise": 200_000,
            "total_tax_paise": 36_000,
        },
    },
]

print("\nPR matcher rows:")
print(f"  {'id':<6}  {'vendor_name':<40}  {'invoice_number'}")
print("  " + "-" * 70)

pr_empty = 0
for row in pr_samples:
    mr = pr_db_row_to_matcher_row(row)
    vname = mr.get("vendor_name", "")
    marker = "" if vname else "  ← (expected empty — no supplier_name in record_data)"
    if not vname and row["record_data"].get("supplier_name"):
        pr_empty += 1
    print(f"  {str(mr['id']):<6}  {vname:<40}  {mr.get('invoice_number', '')}{marker}")

print()
if pr_empty:
    print(f"  ⚠️  WARNING: {pr_empty} PR rows lost their supplier_name!")
else:
    print("  ✅  PR rows correctly populate vendor_name (or are empty when source is empty).")

# ── Guard round-trip test ──────────────────────────────────────────────────
print("\n── Vendor-name guard round-trip ──")
from app.services.vendor_name_matcher import vendor_name_similarity

# Case 1: names present and matching
g = "Reliable Office Supplies Pvt Ltd"
p = "Reliable Office Supplies Pvt Ltd"
sim = vendor_name_similarity(g, p)
print(f"  Same name → similarity={sim:.3f}  {'✅ passes L1 guard' if sim >= 0.95 else '❌ BLOCKED'}")

# Case 2: variant name (slight mismatch)
g2 = "Reliable Office Supplies Pvt Ltd"
p2 = "Reliable Officee Supplies Pvt Ltd"  # typo
sim2 = vendor_name_similarity(g2, p2)
print(f"  Typo name → similarity={sim2:.3f}  {'✅ passes L1 guard' if sim2 >= 0.95 else '⚠️  BLOCKED (falls to L2)'}")

# Case 3: meaningfully different names
g3 = "Dynamic Deccan Associates"
p3 = "Reliable Office Supplies"
sim3 = vendor_name_similarity(g3, p3)
print(f"  Different → similarity={sim3:.3f}  {'✅ passes L1 guard' if sim3 >= 0.95 else '⚠️  BLOCKED (falls to L2) ← expected'}")
