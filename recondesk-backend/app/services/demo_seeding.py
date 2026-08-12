"""Demo Workspace auto-provisioning and seeding service.

Creates a synthetic client_gstin ("Demo Enterprises Pvt Ltd — 27DEMOX1234Z1ZD"),
seeds realistic GSTR-2B & Purchase Register records, and runs the real reconciliation
engine to produce genuine calculated matches, ITC-at-Risk, Rule 37 items, Section 17(5)
blocked credits, RCM tie-outs, Audit Observations, IMS recommendations, and Vendor Follow-ups.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any
from uuid import uuid4

from app.config import get_settings
from app.database import get_supabase
from app.worker.reconciliation_task import execute_reconciliation

_log = logging.getLogger(__name__)

DEMO_CLIENT_GSTIN = "27DEMOX1234Z1ZD"
DEMO_TRADE_NAME = "Demo Enterprises Pvt Ltd"
DEMO_LEGAL_NAME = "Demo Enterprises Private Limited"
DEMO_PERIOD = "2026-04"

# ── Supplier Master Data for Realism ──────────────────────────────────────────
SUPPLIER_RELIABLE = {"gstin": "27AAACR5055K1Z7", "name": "Reliable Office Supplies Pvt Ltd"}
SUPPLIER_SHREE = {"gstin": "27AADCS0472N1Z1", "name": "Shree Tech Services"}
SUPPLIER_METRO = {"gstin": "27AAECS1234F1Z2", "name": "Metro Cloud Solutions Pvt Ltd"}
SUPPLIER_ROYAL = {"gstin": "27AAHCR8765L1Z9", "name": "Royal Motors Garage"}
SUPPLIER_PRIME = {"gstin": "27AAICP2468D1ZA", "name": "Prime Office Interiors"}
SUPPLIER_CARBON = {"gstin": "27AAKFC3210M1Z4", "name": "Carbon Fuels & Lubricants"}
SUPPLIER_GLOBAL = {"gstin": "27AABCT3518Q1ZX", "name": "Global Logistics & Transport"}
SUPPLIER_APEX = {"gstin": "27AAFP9999X1Z1", "name": "Apex IT Infrastructure"}


def seed_demo_dataset() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate realistic synthetic GSTR-2B and PR records.

    Produces outputs across all core modules:
    - Clean Matches (Exact & Normalized)
    - Mismatches / ITC-at-Risk (Amount variance, Date mismatch, GSTR-only)
    - Rule 37 items (Unpaid > 180 days, total ₹2.3L ITC at risk)
    - Section 17(5) Blocked Credits (Motor Vehicle HSN 8703, Club Membership 9995, Works Contract 9954)
    - RCM tie-outs (Reverse Charge items)
    - IMS recommendations & Vendor Follow-ups
    """
    gstr_records: list[dict[str, Any]] = []
    pr_records: list[dict[str, Any]] = []

    # 1. ── CLEAN MATCHES ──────────────────────────────────────────────────────
    clean_pairs = [
        ("INV-2026-001", "2026-04-05", 10000000, 1800000, 900000, 900000, 0, SUPPLIER_RELIABLE, "9983"),
        ("INV-2026-002", "2026-04-08", 5000000, 900000, 450000, 450000, 0, SUPPLIER_SHREE, "9983"),
        ("INV-2026-003", "2026-04-12", 20000000, 3600000, 0, 0, 3600000, SUPPLIER_METRO, "9983"),
        ("INV-2026-004", "2026-04-15", 7500000, 1350000, 675000, 675000, 0, SUPPLIER_RELIABLE, "9983"),
        ("INV-2026-005", "2026-04-18", 12000000, 2160000, 1080000, 1080000, 0, SUPPLIER_SHREE, "9983"),
    ]

    for inv, dt, taxable, total_tax, cgst, sgst, igst, supp, hsn in clean_pairs:
        gstr_records.append({
            "supplier_gstin": supp["gstin"],
            "supplier_name": supp["name"],
            "invoice_number": inv,
            "invoice_date": dt,
            "taxable_value_paise": taxable,
            "total_tax_paise": total_tax,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": igst,
            "invoice_value_paise": taxable + total_tax,
            "hsn_code": hsn,
            "filing_status": "Filed",
            "is_reverse_charge": "N",
        })
        pr_records.append({
            "supplier_gstin": supp["gstin"],
            "supplier_name": supp["name"],
            "invoice_number": inv,
            "invoice_date": dt,
            "taxable_value_paise": taxable,
            "total_tax_paise": total_tax,
            "cgst_paise": cgst,
            "sgst_paise": sgst,
            "igst_paise": igst,
            "invoice_value_paise": taxable + total_tax,
            "payment_status": "Paid",
            "payment_date": dt,
        })

    # 2. ── INVOICE FORMAT VARIANT (Fuzzy Match) ────────────────────────────────
    # GSTR: INV/2026/101, PR: INV2026101
    gstr_records.append({
        "supplier_gstin": SUPPLIER_METRO["gstin"],
        "supplier_name": SUPPLIER_METRO["name"],
        "invoice_number": "INV/2026/101",
        "invoice_date": "2026-04-10",
        "taxable_value_paise": 15000000,
        "total_tax_paise": 2700000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": 2700000,
        "invoice_value_paise": 17700000,
        "hsn_code": "9983",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_METRO["gstin"],
        "supplier_name": SUPPLIER_METRO["name"],
        "invoice_number": "INV2026101",
        "invoice_date": "2026-04-10",
        "taxable_value_paise": 15000000,
        "total_tax_paise": 2700000,
        "cgst_paise": 0,
        "sgst_paise": 0,
        "igst_paise": 2700000,
        "invoice_value_paise": 17700000,
        "payment_status": "Paid",
        "payment_date": "2026-04-14",
    })

    # 3. ── AMOUNT MISMATCH & DATE MISMATCH (ITC at Risk) ─────────────────────
    # Taxable amount discrepancy
    gstr_records.append({
        "supplier_gstin": SUPPLIER_APEX["gstin"],
        "supplier_name": SUPPLIER_APEX["name"],
        "invoice_number": "APX-8801",
        "invoice_date": "2026-04-14",
        "taxable_value_paise": 10000000,
        "total_tax_paise": 1800000,
        "cgst_paise": 900000,
        "sgst_paise": 900000,
        "igst_paise": 0,
        "invoice_value_paise": 11800000,
        "hsn_code": "9983",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_APEX["gstin"],
        "supplier_name": SUPPLIER_APEX["name"],
        "invoice_number": "APX-8801",
        "invoice_date": "2026-04-14",
        "taxable_value_paise": 12000000,  # PR has higher taxable amount (1.2L vs 1.0L)
        "total_tax_paise": 2160000,
        "cgst_paise": 1080000,
        "sgst_paise": 1080000,
        "igst_paise": 0,
        "invoice_value_paise": 14160000,
        "payment_status": "Paid",
        "payment_date": "2026-04-20",
    })

    # 4. ── SECTION 17(5) BLOCKED CREDITS ──────────────────────────────────────
    # Motor Vehicle repair/purchase (HSN 8703)
    gstr_records.append({
        "supplier_gstin": SUPPLIER_ROYAL["gstin"],
        "supplier_name": SUPPLIER_ROYAL["name"],
        "invoice_number": "ROY-9901",
        "invoice_date": "2026-04-16",
        "taxable_value_paise": 8000000,
        "total_tax_paise": 1440000,
        "cgst_paise": 720000,
        "sgst_paise": 720000,
        "igst_paise": 0,
        "invoice_value_paise": 9440000,
        "hsn_code": "8703",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_ROYAL["gstin"],
        "supplier_name": SUPPLIER_ROYAL["name"],
        "invoice_number": "ROY-9901",
        "invoice_date": "2026-04-16",
        "taxable_value_paise": 8000000,
        "total_tax_paise": 1440000,
        "cgst_paise": 720000,
        "sgst_paise": 720000,
        "igst_paise": 0,
        "invoice_value_paise": 9440000,
        "payment_status": "Paid",
        "payment_date": "2026-04-22",
    })

    # Club Membership (HSN 9995)
    gstr_records.append({
        "supplier_gstin": SUPPLIER_PRIME["gstin"],
        "supplier_name": SUPPLIER_PRIME["name"],
        "invoice_number": "CLM-4402",
        "invoice_date": "2026-04-19",
        "taxable_value_paise": 5000000,
        "total_tax_paise": 900000,
        "cgst_paise": 450000,
        "sgst_paise": 450000,
        "igst_paise": 0,
        "invoice_value_paise": 5900000,
        "hsn_code": "9995",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_PRIME["gstin"],
        "supplier_name": SUPPLIER_PRIME["name"],
        "invoice_number": "CLM-4402",
        "invoice_date": "2026-04-19",
        "taxable_value_paise": 5000000,
        "total_tax_paise": 900000,
        "cgst_paise": 450000,
        "sgst_paise": 450000,
        "igst_paise": 0,
        "invoice_value_paise": 5900000,
        "payment_status": "Paid",
        "payment_date": "2026-04-25",
    })

    # 5. ── RULE 37 ITEMS (Unpaid > 180 Days, Total ₹2.3L ITC at risk) ─────────
    # Item 1: ₹1,50,000 tax unpaid (inv date: 2025-09-10)
    gstr_records.append({
        "supplier_gstin": SUPPLIER_PRIME["gstin"],
        "supplier_name": SUPPLIER_PRIME["name"],
        "invoice_number": "R37-1001",
        "invoice_date": "2025-09-10",
        "taxable_value_paise": 8333333,
        "total_tax_paise": 15000000,  # ₹1.5L tax
        "cgst_paise": 7500000,
        "sgst_paise": 7500000,
        "igst_paise": 0,
        "invoice_value_paise": 23333333,
        "hsn_code": "9983",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_PRIME["gstin"],
        "supplier_name": SUPPLIER_PRIME["name"],
        "invoice_number": "R37-1001",
        "invoice_date": "2025-09-10",
        "taxable_value_paise": 8333333,
        "total_tax_paise": 15000000,
        "cgst_paise": 7500000,
        "sgst_paise": 7500000,
        "igst_paise": 0,
        "invoice_value_paise": 23333333,
        "payment_status": "Unpaid",
        "payment_date": None,
    })

    # Item 2: ₹80,000 tax unpaid (inv date: 2025-10-05) -> Total = ₹2.3L
    gstr_records.append({
        "supplier_gstin": SUPPLIER_CARBON["gstin"],
        "supplier_name": SUPPLIER_CARBON["name"],
        "invoice_number": "R37-1002",
        "invoice_date": "2025-10-05",
        "taxable_value_paise": 4444444,
        "total_tax_paise": 8000000,  # ₹80k tax
        "cgst_paise": 4000000,
        "sgst_paise": 4000000,
        "igst_paise": 0,
        "invoice_value_paise": 12444444,
        "hsn_code": "9983",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_CARBON["gstin"],
        "supplier_name": SUPPLIER_CARBON["name"],
        "invoice_number": "R37-1002",
        "invoice_date": "2025-10-05",
        "taxable_value_paise": 4444444,
        "total_tax_paise": 8000000,
        "cgst_paise": 4000000,
        "sgst_paise": 4000000,
        "igst_paise": 0,
        "invoice_value_paise": 12444444,
        "payment_status": "Unpaid",
        "payment_date": None,
    })

    # 6. ── RCM TIE-OUTS ───────────────────────────────────────────────────────
    gstr_records.append({
        "supplier_gstin": SUPPLIER_GLOBAL["gstin"],
        "supplier_name": SUPPLIER_GLOBAL["name"],
        "invoice_number": "RCM-3001",
        "invoice_date": "2026-04-20",
        "taxable_value_paise": 3000000,
        "total_tax_paise": 150000,  # 5% GTA RCM
        "cgst_paise": 75000,
        "sgst_paise": 75000,
        "igst_paise": 0,
        "invoice_value_paise": 3150000,
        "hsn_code": "9965",
        "filing_status": "Filed",
        "is_reverse_charge": "Y",
    })
    pr_records.append({
        "supplier_gstin": SUPPLIER_GLOBAL["gstin"],
        "supplier_name": SUPPLIER_GLOBAL["name"],
        "invoice_number": "RCM-3001",
        "invoice_date": "2026-04-20",
        "taxable_value_paise": 3000000,
        "total_tax_paise": 150000,
        "cgst_paise": 75000,
        "sgst_paise": 75000,
        "igst_paise": 0,
        "invoice_value_paise": 3150000,
        "payment_status": "Paid",
        "payment_date": "2026-04-26",
    })

    # 7. ── GSTR-2B ONLY (Missed / Unclaimed in PR) ───────────────────────────
    gstr_records.append({
        "supplier_gstin": SUPPLIER_CARBON["gstin"],
        "supplier_name": SUPPLIER_CARBON["name"],
        "invoice_number": "CRB-5501",
        "invoice_date": "2026-04-22",
        "taxable_value_paise": 6000000,
        "total_tax_paise": 1080000,
        "cgst_paise": 540000,
        "sgst_paise": 540000,
        "igst_paise": 0,
        "invoice_value_paise": 7080000,
        "hsn_code": "9983",
        "filing_status": "Filed",
        "is_reverse_charge": "N",
    })

    return gstr_records, pr_records


def provision_demo_workspace_if_needed(user_id: str) -> dict[str, Any] | None:
    """Auto-provision a Demo Workspace for a user on signup or first login.

    Returns the demo client dict, or None if DEMO_ONBOARDING_ENABLED is false.
    """
    settings = get_settings()
    if not settings.demo_onboarding_enabled:
        _log.info("provision_demo_workspace_if_needed: DEMO_ONBOARDING_ENABLED is false, skipping")
        return None

    sb = get_supabase()
    user_id = str(user_id).strip()

    # Check if demo client already exists for this firm owner
    existing = (
        sb.table("client_gstins")
        .select("*")
        .eq("firm_owner_id", user_id)
        .eq("is_demo", True)
        .limit(1)
        .execute()
    )

    if existing.data and len(existing.data) > 0:
        demo_client = existing.data[0]
        _log.info("provision_demo_workspace_if_needed: demo client already exists id=%s", demo_client.get("id"))
        return demo_client

    now_iso = datetime.now(timezone.utc).isoformat()
    client_id = str(uuid4())

    # 1. Create client_gstins row with is_demo = True
    client_row = {
        "id": client_id,
        "gstin": DEMO_CLIENT_GSTIN,
        "trade_name": DEMO_TRADE_NAME,
        "legal_name": DEMO_LEGAL_NAME,
        "state_code": "27",
        "firm_owner_id": user_id,
        "is_demo": True,
        "is_active": True,
        "added_at": now_iso,
    }

    try:
        sb.table("client_gstins").insert(client_row).execute()
        _log.info("provision_demo_workspace_if_needed: created demo client_gstins id=%s", client_id)
    except Exception as exc:
        _log.exception("provision_demo_workspace_if_needed: failed to insert demo client_gstins")
        # Retry lookup in case of race condition
        raced = (
            sb.table("client_gstins")
            .select("*")
            .eq("firm_owner_id", user_id)
            .eq("is_demo", True)
            .limit(1)
            .execute()
        )
        if raced.data:
            return raced.data[0]
        raise

    # 2. Create reconciliation_run row
    run_id = str(uuid4())
    run_row = {
        "id": run_id,
        "client_gstin_id": client_id,
        "period": DEMO_PERIOD,
        "status": "MATCHING",
        "progress_percent": 0,
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    sb.table("reconciliation_run").insert(run_row).execute()

    # 3. Insert GSTR-2B and PR records
    gstr_records, pr_records = seed_demo_dataset()

    gstr_inserts = []
    for g in gstr_records:
        gstr_inserts.append({
            "id": str(uuid4()),
            "reconciliation_run_id": run_id,
            "client_gstin_id": client_id,
            "period": DEMO_PERIOD,
            "record_data": g,
        })
    sb.table("gstr_records").insert(gstr_inserts).execute()

    pr_inserts = []
    for p in pr_records:
        pr_inserts.append({
            "id": str(uuid4()),
            "reconciliation_run_id": run_id,
            "client_gstin_id": client_id,
            "period": DEMO_PERIOD,
            "record_data": p,
        })
    sb.table("pr_records").insert(pr_inserts).execute()

    # Update run record import counts
    sb.table("reconciliation_run").update({
        "gstr_records_imported": len(gstr_inserts),
        "pr_records_imported": len(pr_inserts),
    }).eq("id", run_id).execute()

    # 4. Run real reconciliation engine to compute genuine output!
    _log.info("provision_demo_workspace_if_needed: running reconciliation engine for demo run %s", run_id)
    try:
        execute_reconciliation(run_id)
    except Exception as exc:
        _log.exception("provision_demo_workspace_if_needed: execute_reconciliation failed run_id=%s", run_id)

    # 5. Seed Vendor Followup Audit rows for demonstration
    try:
        followup_rows = [
            {
                "id": str(uuid4()),
                "client_gstin_id": client_id,
                "reconciliation_run_id": run_id,
                "vendor_gstin": SUPPLIER_APEX["gstin"],
                "vendor_name": SUPPLIER_APEX["name"],
                "action_type": "REMINDER_DISPATCHED",
                "invoice_number": "APX-8801",
                "discrepancy_amount_paise": 360000,
                "letter_body": f"Dear {SUPPLIER_APEX['name']},\n\nOur reconciliation detected a taxable amount mismatch of ₹3,600 on invoice APX-8801. Please amend GSTR-1.",
                "created_at": now_iso,
            },
            {
                "id": str(uuid4()),
                "client_gstin_id": client_id,
                "reconciliation_run_id": run_id,
                "vendor_gstin": SUPPLIER_CARBON["gstin"],
                "vendor_name": SUPPLIER_CARBON["name"],
                "action_type": "NOTICE_GENERATED",
                "invoice_number": "CRB-5501",
                "discrepancy_amount_paise": 1080000,
                "letter_body": f"Dear {SUPPLIER_CARBON['name']},\n\nInvoice CRB-5501 appears in GSTR-2B but is missing in our Purchase Register. Please re-send invoice copy.",
                "created_at": now_iso,
            },
        ]
        sb.table("supplier_followup_audit").insert(followup_rows).execute()
    except Exception:
        _log.warning("provision_demo_workspace_if_needed: supplier_followup_audit seed failed (non-fatal)")

    # 6. Mark onboarding_completed = True on user_profiles
    try:
        sb.table("user_profiles").update({"onboarding_completed": True}).eq("id", user_id).execute()
    except Exception:
        _log.warning("provision_demo_workspace_if_needed: user_profiles update failed (non-fatal)")

    return client_row
