#!/usr/bin/env python3
"""Generate a clean, internally consistent 2,000-invoice GSTR-1 benchmark.

Produces:
- sales_register_fuzz_2000.csv (2,000 rows: 1,780 B2B, 100 B2CL, 100 B2CS, 20 CDNR)
- gstr1_clean_control_2000.json (Clean GSTR-1 matching SR 100%)
- gstr1_fuzz_2000.json (Mutated GSTR-1 with disjoint, controlled mutations)
- gstr1_prior_jun2025.json (June 2025 prior GSTR-1 for B2BA baseline)
- gstr3b_fuzz_2000.json (Clean GSTR-3B matching clean SR)
- MUTATION_MANIFEST.json (Mechanically derived mutation manifest)
- EXPECTED_RESULT.md (Mechanically derived expected reconciliation results)
"""

import csv
import json
import os
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SEED = 20260911
SUPPLIER_GSTIN = "27ISKPK1273H1ZF"
FILING_PERIOD = "07-2025"
PRIOR_PERIOD = "06-2025"

# Known parties
REGISTERED_PARTIES = [
    {"name": "Alpha Industries", "gstin": "27AAECR1000A1Z1", "pos": "27"},  # Intra-state
    {"name": "Bharat Pharma", "gstin": "29AAECR1001A1Z2", "pos": "29"},     # Karnataka
    {"name": "Cobalt Systems", "gstin": "24AAECR1002A1Z3", "pos": "24"},    # Gujarat
    {"name": "Delta Retail", "gstin": "06AAECR1003A1Z4", "pos": "06"},      # Haryana
    {"name": "Everest Components", "gstin": "07AAECR1004A1Z5", "pos": "07"},# Delhi
    {"name": "Falcon Labs", "gstin": "09AAECR1005A1Z6", "pos": "09"},       # UP
    {"name": "Ganga Traders", "gstin": "19AAECR1006A1Z7", "pos": "19"},     # West Bengal
    {"name": "Horizon Tech", "gstin": "33AAECR1007A1Z8", "pos": "33"},      # Tamil Nadu
]

UNREGISTERED_STATES = ["24", "06", "07", "09", "19", "29", "33"]
HSN_CATALOG = [
    {"hsn": "3004", "desc": "Pharma Products"},
    {"hsn": "9403", "desc": "Office Furniture"},
    {"hsn": "8504", "desc": "Electrical Equipment"},
    {"hsn": "8471", "desc": "Computer Hardware"},
]

GST_RATES = [5.0, 12.0, 18.0, 28.0]


def _calc_taxes(pos: str, rate: float, taxable: float) -> tuple[float, float, float, float, float, float]:
    """Return (igst_rate, igst_amt, cgst_rate, cgst_amt, sgst_rate, sgst_amt)."""
    if pos == "27":
        igst_rt = 0.0
        igst_amt = 0.0
        cgst_rt = rate / 2.0
        sgst_rt = rate / 2.0
        cgst_amt = round(taxable * (cgst_rt / 100.0), 2)
        sgst_amt = round(taxable * (sgst_rt / 100.0), 2)
    else:
        igst_rt = rate
        igst_amt = round(taxable * (rate / 100.0), 2)
        cgst_rt = 0.0
        sgst_rt = 0.0
        cgst_amt = 0.0
        sgst_amt = 0.0
    return igst_rt, igst_amt, cgst_rt, cgst_amt, sgst_rt, sgst_amt


def generate_benchmark(output_dir: Path) -> dict[str, Any]:
    random.seed(SEED)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Generate Clean Sales Register (2,000 rows)
    # ──────────────────────────────────────────────────────────────────────────
    sr_rows: list[dict[str, Any]] = []

    # 1a. 1,780 B2B Invoices: INV/25-26/0001 to INV/25-26/1780
    b2b_taxable_pool = [7500, 15000, 25000, 40000, 60000, 85000, 125000, 175000, 250000]
    for i in range(1, 1781):
        inum = f"INV/25-26/{i:04d}"
        party = random.choice(REGISTERED_PARTIES)
        hsn_item = random.choice(HSN_CATALOG)
        rate = random.choice(GST_RATES)
        taxable = float(random.choice(b2b_taxable_pool))
        day = random.randint(1, 28)
        doc_date = f"{day:02d}/07/2025"

        igst_rt, igst_amt, cgst_rt, cgst_amt, sgst_rt, sgst_amt = _calc_taxes(party["pos"], rate, taxable)
        inv_val = round(taxable + igst_amt + cgst_amt + sgst_amt, 2)

        sr_rows.append({
            "Voucher Type": "Sales",
            "Invoice No": inum,
            "Document Date": doc_date,
            "Party Name": party["name"],
            "GSTIN": party["gstin"],
            "Place of Supply (State Code)": party["pos"],
            "HSN Code": hsn_item["hsn"],
            "Description": hsn_item["desc"],
            "Taxable Value": taxable,
            "IGST Rate %": igst_rt,
            "IGST Amount": igst_amt,
            "CGST Rate %": cgst_rt,
            "CGST Amount": cgst_amt,
            "SGST Rate %": sgst_rt,
            "SGST Amount": sgst_amt,
            "Invoice Value": inv_val,
            "_rate": rate,
            "_category": "B2B",
            "_num": i,
        })

    # 1b. 20 Credit Notes: CN/25-26/0001 to CN/25-26/0020
    cn_taxable_pool = [10000, 15000, 20000, 30000, 50000]
    for i in range(1, 21):
        inum = f"CN/25-26/{i:04d}"
        party = random.choice(REGISTERED_PARTIES)
        hsn_item = random.choice(HSN_CATALOG)
        rate = random.choice(GST_RATES)
        taxable_pos = float(random.choice(cn_taxable_pool))
        taxable = -taxable_pos
        day = random.randint(5, 25)
        doc_date = f"{day:02d}/07/2025"

        igst_rt, igst_amt_pos, cgst_rt, cgst_amt_pos, sgst_rt, sgst_amt_pos = _calc_taxes(party["pos"], rate, taxable_pos)
        igst_amt = -igst_amt_pos
        cgst_amt = -cgst_amt_pos
        sgst_amt = -sgst_amt_pos
        inv_val = round(taxable + igst_amt + cgst_amt + sgst_amt, 2)

        sr_rows.append({
            "Voucher Type": "Credit Note",
            "Invoice No": inum,
            "Document Date": doc_date,
            "Party Name": party["name"],
            "GSTIN": party["gstin"],
            "Place of Supply (State Code)": party["pos"],
            "HSN Code": hsn_item["hsn"],
            "Description": hsn_item["desc"],
            "Taxable Value": taxable,
            "IGST Rate %": igst_rt,
            "IGST Amount": igst_amt,
            "CGST Rate %": cgst_rt,
            "CGST Amount": cgst_amt,
            "SGST Rate %": sgst_rt,
            "SGST Amount": sgst_amt,
            "Invoice Value": inv_val,
            "_rate": rate,
            "_category": "CDNR",
            "_num": i,
        })

    # 1c. 100 B2CL Invoices: B2CL/25-26/0001 to B2CL/25-26/0100
    b2cl_taxable_pool = [260000, 280000, 300000, 350000, 400000]
    for i in range(1, 101):
        inum = f"B2CL/25-26/{i:04d}"
        pos = random.choice(UNREGISTERED_STATES)
        hsn_item = random.choice(HSN_CATALOG)
        rate = random.choice(GST_RATES)
        taxable = float(random.choice(b2cl_taxable_pool))
        day = random.randint(1, 28)
        doc_date = f"{day:02d}/07/2025"

        igst_rt, igst_amt, cgst_rt, cgst_amt, sgst_rt, sgst_amt = _calc_taxes(pos, rate, taxable)
        inv_val = round(taxable + igst_amt + cgst_amt + sgst_amt, 2)

        sr_rows.append({
            "Voucher Type": "Sales",
            "Invoice No": inum,
            "Document Date": doc_date,
            "Party Name": "Unregistered Consumer",
            "GSTIN": "",
            "Place of Supply (State Code)": pos,
            "HSN Code": hsn_item["hsn"],
            "Description": hsn_item["desc"],
            "Taxable Value": taxable,
            "IGST Rate %": igst_rt,
            "IGST Amount": igst_amt,
            "CGST Rate %": cgst_rt,
            "CGST Amount": cgst_amt,
            "SGST Rate %": sgst_rt,
            "SGST Amount": sgst_amt,
            "Invoice Value": inv_val,
            "_rate": rate,
            "_category": "B2CL",
            "_num": i,
        })

    # 1d. 100 B2CS Invoices: B2CS/25-26/0001 to B2CS/25-26/0100
    b2cs_taxable_pool = [500, 1000, 1500, 2500, 5000, 10000]
    for i in range(1, 101):
        inum = f"B2CS/25-26/{i:04d}"
        pos = "27" if random.random() < 0.7 else random.choice(UNREGISTERED_STATES)
        hsn_item = random.choice(HSN_CATALOG)
        rate = random.choice(GST_RATES)
        taxable = float(random.choice(b2cs_taxable_pool))
        day = random.randint(1, 28)
        doc_date = f"{day:02d}/07/2025"

        igst_rt, igst_amt, cgst_rt, cgst_amt, sgst_rt, sgst_amt = _calc_taxes(pos, rate, taxable)
        inv_val = round(taxable + igst_amt + cgst_amt + sgst_amt, 2)

        sr_rows.append({
            "Voucher Type": "Sales",
            "Invoice No": inum,
            "Document Date": doc_date,
            "Party Name": "Retail Customer",
            "GSTIN": "",
            "Place of Supply (State Code)": pos,
            "HSN Code": hsn_item["hsn"],
            "Description": hsn_item["desc"],
            "Taxable Value": taxable,
            "IGST Rate %": igst_rt,
            "IGST Amount": igst_amt,
            "CGST Rate %": cgst_rt,
            "CGST Amount": cgst_amt,
            "SGST Rate %": sgst_rt,
            "SGST Amount": sgst_amt,
            "Invoice Value": inv_val,
            "_rate": rate,
            "_category": "B2CS",
            "_num": i,
        })

    assert len(sr_rows) == 2000, f"Expected 2000 SR rows, got {len(sr_rows)}"

    # Write Sales Register CSV
    sr_csv_path = output_dir / "sales_register_fuzz_2000.csv"
    csv_fields = [
        "Voucher Type", "Invoice No", "Document Date", "Party Name", "GSTIN",
        "Place of Supply (State Code)", "HSN Code", "Description",
        "Taxable Value", "IGST Rate %", "IGST Amount", "CGST Rate %",
        "CGST Amount", "SGST Rate %", "SGST Amount", "Invoice Value",
    ]
    with open(sr_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for r in sr_rows:
            clean_r = {k: r[k] for k in csv_fields}
            writer.writerow(clean_r)

    # Calculate Clean Totals
    sr_taxable_tot = sum(r["Taxable Value"] for r in sr_rows)
    sr_igst_tot = sum(r["IGST Amount"] for r in sr_rows)
    sr_cgst_tot = sum(r["CGST Amount"] for r in sr_rows)
    sr_sgst_tot = sum(r["SGST Amount"] for r in sr_rows)
    sr_inv_tot = sum(r["Invoice Value"] for r in sr_rows)

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Generate Prior-Period June 2025 GSTR-1 (B2BA Baseline)
    # ──────────────────────────────────────────────────────────────────────────
    prior_gstr1 = {
        "gstin": SUPPLIER_GSTIN,
        "fp": PRIOR_PERIOD,
        "gt": 0,
        "cur_gt": 0,
        "b2b": [
            {
                "ctin": "29AAECR1001A1Z2",
                "inv": [
                    {
                        "inum": "INV/25-26/BA0001",
                        "idt": "15-06-2025",
                        "val": 59000.0,
                        "pos": "29",
                        "rchrg": "N",
                        "inv_typ": "R",
                        "itms": [
                            {
                                "num": 1,
                                "itm_det": {
                                    "txval": 50000.0,
                                    "rt": 18.0,
                                    "iamt": 9000.0,
                                    "camt": 0.0,
                                    "samt": 0.0,
                                    "csamt": 0.0,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
        "b2cs": [],
        "hsn": {"data": []},
        "doc_issue": {"doc_det": []},
    }
    prior_json_path = output_dir / "gstr1_prior_jun2025.json"
    with open(prior_json_path, mode="w", encoding="utf-8") as f:
        json.dump(prior_gstr1, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Generate Clean Control GSTR-1
    # ──────────────────────────────────────────────────────────────────────────
    def _make_gstr1_base(rows: list[dict[str, Any]]) -> dict[str, Any]:
        b2b_by_ctin: dict[str, list[dict[str, Any]]] = {}
        cdnr_by_ctin: dict[str, list[dict[str, Any]]] = {}
        b2cl_by_pos: dict[str, list[dict[str, Any]]] = {}
        b2cs_agg: dict[tuple[str, str, float], dict[str, float]] = {}

        for r in rows:
            cat = r["_category"]
            d_parts = r["Document Date"].split("/")
            idt_formatted = f"{d_parts[0]}-{d_parts[1]}-{d_parts[2]}"

            if cat == "B2B":
                ctin = r["GSTIN"]
                b2b_by_ctin.setdefault(ctin, []).append({
                    "inum": r["Invoice No"],
                    "idt": idt_formatted,
                    "val": r["Invoice Value"],
                    "pos": r["Place of Supply (State Code)"],
                    "rchrg": "N",
                    "inv_typ": "R",
                    "itms": [
                        {
                            "num": 1,
                            "itm_det": {
                                "txval": r["Taxable Value"],
                                "rt": r["_rate"],
                                "iamt": r["IGST Amount"],
                                "camt": r["CGST Amount"],
                                "samt": r["SGST Amount"],
                                "csamt": 0.0,
                            },
                        }
                    ],
                })
            elif cat == "CDNR":
                ctin = r["GSTIN"]
                cdnr_by_ctin.setdefault(ctin, []).append({
                    "ntty": "C",
                    "nt_num": r["Invoice No"],
                    "nt_dt": idt_formatted,
                    "val": abs(r["Invoice Value"]),
                    "pos": r["Place of Supply (State Code)"],
                    "rchrg": "N",
                    "inv_typ": "R",
                    "itms": [
                        {
                            "num": 1,
                            "itm_det": {
                                "txval": abs(r["Taxable Value"]),
                                "rt": r["_rate"],
                                "iamt": abs(r["IGST Amount"]),
                                "camt": abs(r["CGST Amount"]),
                                "samt": abs(r["SGST Amount"]),
                                "csamt": 0.0,
                            },
                        }
                    ],
                })
            elif cat == "B2CL":
                pos = r["Place of Supply (State Code)"]
                b2cl_by_pos.setdefault(pos, []).append({
                    "pos": pos,
                    "inv": [
                        {
                            "inum": r["Invoice No"],
                            "idt": idt_formatted,
                            "val": r["Invoice Value"],
                            "itms": [
                                {
                                    "num": 1,
                                    "itm_det": {
                                        "txval": r["Taxable Value"],
                                        "rt": r["_rate"],
                                        "iamt": r["IGST Amount"],
                                        "csamt": 0.0,
                                    },
                                }
                            ],
                        }
                    ],
                })
            elif cat == "B2CS":
                pos = r["Place of Supply (State Code)"]
                sply_ty = "INTRA" if pos == "27" else "INTER"
                key = (sply_ty, pos, r["_rate"])
                if key not in b2cs_agg:
                    b2cs_agg[key] = {"txval": 0.0, "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0}
                b2cs_agg[key]["txval"] += r["Taxable Value"]
                b2cs_agg[key]["iamt"] += r["IGST Amount"]
                b2cs_agg[key]["camt"] += r["CGST Amount"]
                b2cs_agg[key]["samt"] += r["SGST Amount"]

        b2b_list = [{"ctin": ctin, "inv": invs} for ctin, invs in sorted(b2b_by_ctin.items())]
        cdnr_list = [{"ctin": ctin, "nt": nts} for ctin, nts in sorted(cdnr_by_ctin.items())]
        b2cl_list = []
        for pos, inv_blocks in sorted(b2cl_by_pos.items()):
            all_pos_invs = []
            for b in inv_blocks:
                all_pos_invs.extend(b["inv"])
            b2cl_list.append({"pos": pos, "inv": all_pos_invs})

        b2cs_list = [
            {
                "sply_ty": sply_ty,
                "pos": pos,
                "typ": "OE",
                "rt": rt,
                "txval": round(vals["txval"], 2),
                "iamt": round(vals["iamt"], 2),
                "camt": round(vals["camt"], 2),
                "samt": round(vals["samt"], 2),
                "csamt": 0.0,
            }
            for (sply_ty, pos, rt), vals in sorted(b2cs_agg.items())
        ]

        return {
            "gstin": SUPPLIER_GSTIN,
            "fp": FILING_PERIOD,
            "gt": 0,
            "cur_gt": 0,
            "b2b": b2b_list,
            "b2cl": b2cl_list,
            "b2cs": b2cs_list,
            "cdnr": cdnr_list,
            "exp": [],
            "b2ba": [],
            "hsn": {"data": []},
            "doc_issue": {"doc_det": []},
        }

    clean_gstr1 = _make_gstr1_base(sr_rows)
    clean_json_path = output_dir / "gstr1_clean_control_2000.json"
    with open(clean_json_path, mode="w", encoding="utf-8") as f:
        json.dump(clean_gstr1, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Generate Clean GSTR-3B (Matching Clean SR Totals)
    # ──────────────────────────────────────────────────────────────────────────
    gstr3b_data = {
        "gstin": SUPPLIER_GSTIN,
        "ret_period": FILING_PERIOD,
        "sup_details": {
            "osup_det": {
                "txval": round(sr_taxable_tot, 2),
                "iamt": round(sr_igst_tot, 2),
                "camt": round(sr_cgst_tot, 2),
                "samt": round(sr_sgst_tot, 2),
                "csamt": 0.0,
            },
            "osup_zero": {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "osup_nil_exmp": {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "osup_others": {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
        },
        "inter_sup": {
            "unreg_intra": 0,
            "unreg_inter": 0,
            "unreg_inter_upto_250k": 0,
            "reg_intra": 0,
            "reg_inter": 0,
        },
        "itc_elg": {},
        "inward_sup": {},
        "intr_ltfee": {},
    }
    gstr3b_json_path = output_dir / "gstr3b_fuzz_2000.json"
    with open(gstr3b_json_path, mode="w", encoding="utf-8") as f:
        json.dump(gstr3b_data, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Generate Mutated GSTR-1 (With Disjoint Mutations)
    # ──────────────────────────────────────────────────────────────────────────
    mutated_gstr1 = json.loads(json.dumps(clean_gstr1))

    b2b_inv_map: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for c_idx, ctin_block in enumerate(mutated_gstr1["b2b"]):
        for i_idx, inv in enumerate(ctin_block["inv"]):
            b2b_inv_map[inv["inum"]] = (c_idx, i_idx, inv)

    manifest_mutations: dict[str, Any] = {}
    manifest_details: dict[str, Any] = {}

    # ── Mutation 1: missing_b2b (20 invoices: 0101 to 0120) ──────────────────
    missing_b2b_nums = list(range(101, 121))
    missing_b2b_inums = [f"INV/25-26/{n:04d}" for n in missing_b2b_nums]
    missing_b2b_set = set(missing_b2b_inums)
    for ctin_block in mutated_gstr1["b2b"]:
        ctin_block["inv"] = [inv for inv in ctin_block["inv"] if inv["inum"] not in missing_b2b_set]
    mutated_gstr1["b2b"] = [b for b in mutated_gstr1["b2b"] if b["inv"]]
    manifest_mutations["missing_b2b"] = len(missing_b2b_inums)
    manifest_details["missing_b2b"] = {
        "count": len(missing_b2b_inums),
        "range": "INV/25-26/0101 to INV/25-26/0120",
        "invoices": missing_b2b_inums,
    }

    # Rebuild b2b_inv_map
    b2b_inv_map.clear()
    for c_idx, ctin_block in enumerate(mutated_gstr1["b2b"]):
        for i_idx, inv in enumerate(ctin_block["inv"]):
            b2b_inv_map[inv["inum"]] = (c_idx, i_idx, inv)

    # ── Mutation 2: duplicate_b2b (15 invoices: 0121 to 0135) ────────────────
    dup_b2b_nums = list(range(121, 136))
    dup_b2b_inums = [f"INV/25-26/{n:04d}" for n in dup_b2b_nums]
    for inum in dup_b2b_inums:
        c_idx, _, inv_obj = b2b_inv_map[inum]
        dup_copy = json.loads(json.dumps(inv_obj))
        mutated_gstr1["b2b"][c_idx]["inv"].append(dup_copy)
    manifest_mutations["duplicate_b2b"] = len(dup_b2b_inums)
    manifest_details["duplicate_b2b"] = {
        "count": len(dup_b2b_inums),
        "range": "INV/25-26/0121 to INV/25-26/0135",
        "invoices": dup_b2b_inums,
    }

    # ── Mutation 3: extra_b2b_duplicate_representation (20 invoices: 0136 to 0155)
    extra_b2b_nums = list(range(136, 156))
    extra_b2b_inums = [f"INV/25-26/{n:04d}" for n in extra_b2b_nums]
    for inum in extra_b2b_inums:
        c_idx, _, inv_obj = b2b_inv_map[inum]
        extra_copy = json.loads(json.dumps(inv_obj))
        mutated_gstr1["b2b"][c_idx]["inv"].append(extra_copy)
    manifest_mutations["extra_b2b_duplicate_representation"] = len(extra_b2b_inums)
    manifest_details["extra_b2b_duplicate_representation"] = {
        "count": len(extra_b2b_inums),
        "range": "INV/25-26/0136 to INV/25-26/0155",
        "invoices": extra_b2b_inums,
    }

    # ── Mutation 4: b2b_taxable_mismatch (25 invoices: 0156 to 0180) ──────────
    taxable_mm_nums = list(range(156, 181))
    taxable_mm_inums = [f"INV/25-26/{n:04d}" for n in taxable_mm_nums]
    for inum in taxable_mm_inums:
        _, _, inv_obj = b2b_inv_map[inum]
        itm = inv_obj["itms"][0]["itm_det"]
        orig_tx = itm["txval"]
        new_tx = orig_tx + 10000.0  # +10,000 taxable value
        pos = inv_obj["pos"]
        rt = itm["rt"]
        _, new_iamt, _, new_camt, _, new_samt = _calc_taxes(pos, rt, new_tx)
        itm["txval"] = new_tx
        itm["iamt"] = new_iamt
        itm["camt"] = new_camt
        itm["samt"] = new_samt
        inv_obj["val"] = round(new_tx + new_iamt + new_camt + new_samt, 2)
    manifest_mutations["b2b_taxable_mismatch"] = len(taxable_mm_inums)
    manifest_details["b2b_taxable_mismatch"] = {
        "count": len(taxable_mm_inums),
        "range": "INV/25-26/0156 to INV/25-26/0180",
        "delta_per_invoice": "+10000.0 taxable",
        "invoices": taxable_mm_inums,
    }

    # ── Mutation 5: b2b_tax_mismatch (25 invoices: 0181 to 0205) ─────────────
    tax_mm_nums = list(range(181, 206))
    tax_mm_inums = [f"INV/25-26/{n:04d}" for n in tax_mm_nums]
    for idx, inum in enumerate(tax_mm_inums):
        _, _, inv_obj = b2b_inv_map[inum]
        itm = inv_obj["itms"][0]["itm_det"]
        pos = inv_obj["pos"]
        tax_shift = 500.0 if idx % 2 == 0 else 1000.0
        if pos == "27":
            itm["camt"] += tax_shift / 2.0
            itm["samt"] += tax_shift / 2.0
        else:
            itm["iamt"] += tax_shift
        inv_obj["val"] += tax_shift
    manifest_mutations["b2b_tax_mismatch"] = len(tax_mm_inums)
    manifest_details["b2b_tax_mismatch"] = {
        "count": len(tax_mm_inums),
        "range": "INV/25-26/0181 to INV/25-26/0205",
        "invoices": tax_mm_inums,
    }

    # ── Mutation 6: date_mismatch (15 invoices: 0206 to 0220) ────────────────
    date_mm_nums = list(range(206, 221))
    date_mm_inums = [f"INV/25-26/{n:04d}" for n in date_mm_nums]
    for inum in date_mm_inums:
        _, _, inv_obj = b2b_inv_map[inum]
        d_str = inv_obj["idt"]
        p = [int(x) for x in d_str.split("-")]
        orig_d = date(p[2], p[1], p[0])
        new_d = orig_d + timedelta(days=10)
        if new_d.month != 7:
            new_d = date(2025, 7, 28)
        inv_obj["idt"] = f"{new_d.day:02d}-{new_d.month:02d}-{new_d.year}"
    manifest_mutations["date_mismatch"] = len(date_mm_inums)
    manifest_details["date_mismatch"] = {
        "count": len(date_mm_inums),
        "range": "INV/25-26/0206 to INV/25-26/0220",
        "description": "Deterministic +10-day shift outside L1/L2 tolerance (1d/3d), within L3",
        "invoices": date_mm_inums,
    }

    # ── Mutation 7: gstin_mismatch (15 invoices: 0221 to 0235) ───────────────
    gstin_mm_nums = list(range(221, 236))
    gstin_mm_inums = [f"INV/25-26/{n:04d}" for n in gstin_mm_nums]
    dummy_ctin = "27ZZZPK9999A1ZQ"
    dummy_invs: list[dict[str, Any]] = []
    for inum in gstin_mm_inums:
        c_idx, _, inv_obj = b2b_inv_map[inum]
        dummy_invs.append(inv_obj)
    gstin_mm_set = set(gstin_mm_inums)
    for ctin_block in mutated_gstr1["b2b"]:
        ctin_block["inv"] = [inv for inv in ctin_block["inv"] if inv["inum"] not in gstin_mm_set]
    mutated_gstr1["b2b"] = [b for b in mutated_gstr1["b2b"] if b["inv"]]
    mutated_gstr1["b2b"].append({"ctin": dummy_ctin, "inv": dummy_invs})
    manifest_mutations["gstin_mismatch"] = len(gstin_mm_inums)
    manifest_details["gstin_mismatch"] = {
        "count": len(gstin_mm_inums),
        "range": "INV/25-26/0221 to INV/25-26/0235",
        "dummy_gstin": dummy_ctin,
        "invoices": gstin_mm_inums,
    }

    # Rebuild b2b_inv_map
    b2b_inv_map.clear()
    for c_idx, ctin_block in enumerate(mutated_gstr1["b2b"]):
        for i_idx, inv in enumerate(ctin_block["inv"]):
            b2b_inv_map[inv["inum"]] = (c_idx, i_idx, inv)

    # ── Mutation 8: rate_mismatch (15 invoices: 0236 to 0250) ────────────────
    rate_mm_nums = list(range(236, 251))
    rate_mm_inums = [f"INV/25-26/{n:04d}" for n in rate_mm_nums]
    swap_rates = {5.0: 18.0, 12.0: 28.0, 18.0: 5.0, 28.0: 12.0}
    for inum in rate_mm_inums:
        _, _, inv_obj = b2b_inv_map[inum]
        itm = inv_obj["itms"][0]["itm_det"]
        cur_rt = itm["rt"]
        new_rt = swap_rates.get(cur_rt, 18.0)
        pos = inv_obj["pos"]
        tx = itm["txval"]
        _, new_iamt, _, new_camt, _, new_samt = _calc_taxes(pos, new_rt, tx)
        itm["rt"] = new_rt
        itm["iamt"] = new_iamt
        itm["camt"] = new_camt
        itm["samt"] = new_samt
        inv_obj["val"] = round(tx + new_iamt + new_camt + new_samt, 2)
    manifest_mutations["rate_mismatch"] = len(rate_mm_inums)
    manifest_details["rate_mismatch"] = {
        "count": len(rate_mm_inums),
        "range": "INV/25-26/0236 to INV/25-26/0250",
        "invoices": rate_mm_inums,
    }

    # ── Mutation 9: invoice_format_variation (30 invoices: 0251 to 0280) ─────
    fmt_nums = list(range(251, 281))
    fmt_inums = [f"INV/25-26/{n:04d}" for n in fmt_nums]
    fmt_map = {}
    for idx, inum in enumerate(fmt_inums):
        _, _, inv_obj = b2b_inv_map[inum]
        n = fmt_nums[idx]
        new_num = f"SYS-INV25-26{n:04d}"
        inv_obj["inum"] = new_num
        fmt_map[inum] = new_num
    manifest_mutations["invoice_format_variation"] = len(fmt_inums)
    manifest_details["invoice_format_variation"] = {
        "count": len(fmt_inums),
        "range": "INV/25-26/0251 to INV/25-26/0280",
        "mapping": fmt_map,
    }

    # ── Mutation 10: credit_note_missing (5 credit notes: CN/25-26/0001 to 0005)
    cn_missing_nums = list(range(1, 6))
    cn_missing_inums = [f"CN/25-26/{n:04d}" for n in cn_missing_nums]
    cn_missing_set = set(cn_missing_inums)
    for ctin_block in mutated_gstr1["cdnr"]:
        ctin_block["nt"] = [nt for nt in ctin_block["nt"] if nt["nt_num"] not in cn_missing_set]
    mutated_gstr1["cdnr"] = [c for c in mutated_gstr1["cdnr"] if c["nt"]]
    manifest_mutations["credit_note_missing"] = len(cn_missing_inums)
    manifest_details["credit_note_missing"] = {
        "count": len(cn_missing_inums),
        "range": "CN/25-26/0001 to CN/25-26/0005",
        "invoices": cn_missing_inums,
    }

    # ── Mutation 11: credit_note_amount_mismatch (5 credit notes: CN/25-26/0006 to 0010)
    cn_mm_nums = list(range(6, 11))
    cn_mm_inums = [f"CN/25-26/{n:04d}" for n in cn_mm_nums]
    cn_mm_set = set(cn_mm_inums)
    for ctin_block in mutated_gstr1["cdnr"]:
        for nt in ctin_block["nt"]:
            if nt["nt_num"] in cn_mm_set:
                itm = nt["itms"][0]["itm_det"]
                orig_tx = itm["txval"]
                new_tx = orig_tx + 5000.0
                pos = nt["pos"]
                rt = itm["rt"]
                _, new_iamt, _, new_camt, _, new_samt = _calc_taxes(pos, rt, new_tx)
                itm["txval"] = new_tx
                itm["iamt"] = new_iamt
                itm["camt"] = new_camt
                itm["samt"] = new_samt
                nt["val"] = round(new_tx + new_iamt + new_camt + new_samt, 2)
    manifest_mutations["credit_note_amount_mismatch"] = len(cn_mm_inums)
    manifest_details["credit_note_amount_mismatch"] = {
        "count": len(cn_mm_inums),
        "range": "CN/25-26/0006 to CN/25-26/0010",
        "delta_per_note": "+5000.0 taxable",
        "invoices": cn_mm_inums,
    }

    # ── Mutation 12: b2cl_taxable_mismatch (10 invoices: B2CL/25-26/0001 to 0010)
    b2cl_mm_nums = list(range(1, 11))
    b2cl_mm_inums = [f"B2CL/25-26/{n:04d}" for n in b2cl_mm_nums]
    b2cl_mm_set = set(b2cl_mm_inums)
    for pos_block in mutated_gstr1["b2cl"]:
        for inv in pos_block["inv"]:
            if inv["inum"] in b2cl_mm_set:
                itm = inv["itms"][0]["itm_det"]
                orig_tx = itm["txval"]
                new_tx = orig_tx + 15000.0
                rt = itm["rt"]
                new_iamt = round(new_tx * (rt / 100.0), 2)
                itm["txval"] = new_tx
                itm["iamt"] = new_iamt
                inv["val"] = round(new_tx + new_iamt, 2)
    manifest_mutations["b2cl_taxable_mismatch"] = len(b2cl_mm_inums)
    manifest_details["b2cl_taxable_mismatch"] = {
        "count": len(b2cl_mm_inums),
        "range": "B2CL/25-26/0001 to B2CL/25-26/0010",
        "delta_per_invoice": "+15000.0 taxable",
        "invoices": b2cl_mm_inums,
    }

    # ── Mutation 13: b2cs_aggregate_mismatch (1 aggregate bucket) ────────────
    if mutated_gstr1["b2cs"]:
        b2cs_target = mutated_gstr1["b2cs"][0]
        b2cs_target["txval"] = round(b2cs_target["txval"] + 1000.0, 2)
        rt = b2cs_target["rt"]
        pos = b2cs_target["pos"]
        if pos == "27":
            add_c = round(1000.0 * (rt / 200.0), 2)
            b2cs_target["camt"] = round(b2cs_target["camt"] + add_c, 2)
            b2cs_target["samt"] = round(b2cs_target["samt"] + add_c, 2)
        else:
            add_i = round(1000.0 * (rt / 100.0), 2)
            b2cs_target["iamt"] = round(b2cs_target["iamt"] + add_i, 2)
    manifest_mutations["b2cs_aggregate_mismatch"] = 1
    manifest_details["b2cs_aggregate_mismatch"] = {
        "count": 1,
        "delta": "+1000.0 taxable on aggregate Table 7 bucket",
    }

    # ── Mutation 14: valid_b2ba (1 valid amendment: INV/25-26/BA0001) ─────────
    valid_b2ba_entry = {
        "ctin": "29AAECR1001A1Z2",
        "inv": [
            {
                "oinum": "INV/25-26/BA0001",
                "oidt": "15-06-2025",
                "inum": "INV/25-26/BA0001",
                "idt": "15-06-2025",
                "val": 64900.0,
                "pos": "29",
                "rchrg": "N",
                "inv_typ": "R",
                "itms": [
                    {
                        "num": 1,
                        "itm_det": {
                            "txval": 55000.0,
                            "rt": 18.0,
                            "iamt": 9900.0,
                            "camt": 0.0,
                            "samt": 0.0,
                            "csamt": 0.0,
                        },
                    }
                ],
            }
        ],
    }
    manifest_mutations["valid_b2ba"] = 1
    manifest_details["valid_b2ba"] = {
        "count": 1,
        "original_invoice": "INV/25-26/BA0001",
        "prior_period": "06-2025",
        "prior_taxable": 50000.0,
        "prior_igst": 9000.0,
        "amended_taxable": 55000.0,
        "amended_igst": 9900.0,
        "current_period_delta": {"taxable": 5000.0, "igst": 900.0},
    }

    # ── Mutation 15: invalid_b2ba (1 invalid amendment: NONEXIST-999) ─────────
    invalid_b2ba_entry = {
        "ctin": "29AAECR1001A1Z2",
        "inv": [
            {
                "oinum": "NONEXIST-999",
                "oidt": "10-06-2025",
                "inum": "NONEXIST-999",
                "idt": "10-06-2025",
                "val": 53100.0,
                "pos": "29",
                "rchrg": "N",
                "inv_typ": "R",
                "itms": [
                    {
                        "num": 1,
                        "itm_det": {
                            "txval": 45000.0,
                            "rt": 18.0,
                            "iamt": 8100.0,
                            "camt": 0.0,
                            "samt": 0.0,
                            "csamt": 0.0,
                        },
                    }
                ],
            }
        ],
    }
    manifest_mutations["invalid_b2ba"] = 1
    manifest_details["invalid_b2ba"] = {
        "count": 1,
        "original_invoice": "NONEXIST-999",
        "note": "Original invoice not found in prior GSTR-1; must be flagged and excluded from current turnover",
    }

    mutated_gstr1["b2ba"] = [valid_b2ba_entry, invalid_b2ba_entry]

    # Write mutated GSTR-1 JSON
    mutated_json_path = output_dir / "gstr1_fuzz_2000.json"
    with open(mutated_json_path, mode="w", encoding="utf-8") as f:
        json.dump(mutated_gstr1, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 6. Compute Programmatic Expected Reconciliation Metrics
    # ──────────────────────────────────────────────────────────────────────────
    all_b2b_inums = []
    for c in mutated_gstr1["b2b"]:
        for inv in c["inv"]:
            all_b2b_inums.append(inv["inum"])
    b2b_counter = Counter(all_b2b_inums)
    table_4a_duplicates = {k: v for k, v in b2b_counter.items() if v > 1}
    duplicate_count_exact = len(table_4a_duplicates)

    missing_count_exact = len(missing_b2b_inums) + len(gstin_mm_inums) + len(cn_missing_inums)
    extra_count_exact = len(dup_b2b_inums) + len(extra_b2b_inums) + len(gstin_mm_inums)

    amount_mismatch_exact = (
        len(taxable_mm_inums) + len(tax_mm_inums) + len(b2cl_mm_inums) +
        len(cn_mm_inums) + 1
    )

    # Financial Deltas for Tie-Out:
    mut_txval = 0.0
    mut_iamt = 0.0
    mut_camt = 0.0
    mut_samt = 0.0

    for c in mutated_gstr1["b2b"]:
        for inv in c["inv"]:
            for itm in inv["itms"]:
                d = itm["itm_det"]
                mut_txval += d["txval"]
                mut_iamt += d["iamt"]
                mut_camt += d["camt"]
                mut_samt += d["samt"]

    for pos_b in mutated_gstr1["b2cl"]:
        for inv in pos_b["inv"]:
            for itm in inv["itms"]:
                d = itm["itm_det"]
                mut_txval += d["txval"]
                mut_iamt += d["iamt"]

    for b in mutated_gstr1["b2cs"]:
        mut_txval += b["txval"]
        mut_iamt += b["iamt"]
        mut_camt += b["camt"]
        mut_samt += b["samt"]

    for c in mutated_gstr1["cdnr"]:
        for nt in c["nt"]:
            for itm in nt["itms"]:
                d = itm["itm_det"]
                mut_txval -= d["txval"]
                mut_iamt -= d["iamt"]
                mut_camt -= d["camt"]
                mut_samt -= d["samt"]

    # Table 9A Amendments: Valid B2BA adds +5,000 delta. Invalid B2BA is excluded.
    net_tieout_txval = mut_txval + 5000.0
    net_tieout_iamt = mut_iamt + 900.0
    net_tieout_camt = mut_camt
    net_tieout_samt = mut_samt

    taxable_variance = round(net_tieout_txval - sr_taxable_tot, 2)
    igst_variance = round(net_tieout_iamt - sr_igst_tot, 2)
    cgst_variance = round(net_tieout_camt - sr_cgst_tot, 2)
    sgst_variance = round(net_tieout_samt - sr_sgst_tot, 2)

    # ──────────────────────────────────────────────────────────────────────────
    # 7. Generate Derived MUTATION_MANIFEST.json
    # ──────────────────────────────────────────────────────────────────────────
    manifest = {
        "seed": SEED,
        "supplier_gstin": SUPPLIER_GSTIN,
        "period": FILING_PERIOD,
        "prior_period": PRIOR_PERIOD,
        "sales_register_records": len(sr_rows),
        "composition": {
            "B2B": 1780,
            "CDNR": 20,
            "B2CL": 100,
            "B2CS": 100,
        },
        "mutations": manifest_mutations,
        "mutation_details": manifest_details,
        "financial_summary": {
            "clean_sales_register": {
                "taxable": round(sr_taxable_tot, 2),
                "igst": round(sr_igst_tot, 2),
                "cgst": round(sr_cgst_tot, 2),
                "sgst": round(sr_sgst_tot, 2),
                "total_tax": round(sr_igst_tot + sr_cgst_tot + sr_sgst_tot, 2),
            },
            "clean_gstr3b": {
                "taxable": round(sr_taxable_tot, 2),
                "igst": round(sr_igst_tot, 2),
                "cgst": round(sr_cgst_tot, 2),
                "sgst": round(sr_sgst_tot, 2),
                "total_tax": round(sr_igst_tot + sr_cgst_tot + sr_sgst_tot, 2),
            },
            "mutated_gstr1_net": {
                "taxable": round(net_tieout_txval, 2),
                "igst": round(net_tieout_iamt, 2),
                "cgst": round(net_tieout_camt, 2),
                "sgst": round(net_tieout_samt, 2),
                "total_tax": round(net_tieout_iamt + net_tieout_camt + net_tieout_samt, 2),
            },
            "expected_tie_out_variance": {
                "taxable": taxable_variance,
                "igst": igst_variance,
                "cgst": cgst_variance,
                "sgst": sgst_variance,
            },
        },
        "verification_metrics": {
            "missing_records_total": missing_count_exact,
            "missing_b2b_and_gstin": len(missing_b2b_inums) + len(gstin_mm_inums),
            "missing_credit_notes": len(cn_missing_inums),
            "extra_records_total": extra_count_exact,
            "amount_mismatches_total": amount_mismatch_exact,
            "rate_mismatches_total": len(rate_mm_inums),
            "g1m8_duplicate_count": duplicate_count_exact,
            "g1m8_series_gap_numbers": len(missing_b2b_nums) + 20,
            "g1m11_invalid_amendments": 1,
        },
    }
    manifest_path = output_dir / "MUTATION_MANIFEST.json"
    with open(manifest_path, mode="w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # ──────────────────────────────────────────────────────────────────────────
    # 8. Generate Derived EXPECTED_RESULT.md
    # ──────────────────────────────────────────────────────────────────────────
    expected_md = f"""# ReconDesk GSTR-1 Clean Adversarial Benchmark — 2,000 Records

Supplier GSTIN: `{SUPPLIER_GSTIN}`  
Period: `{FILING_PERIOD}`  
Prior Period: `{PRIOR_PERIOD}`  
Seed: `{SEED}`

## Objective
Rigorous stress-testing of outward supply reconciliation with 2,000 synthetic records and mathematically disjoint, controlled mutations across all GST sections.

## Population Composition
- **Total Sales Register Records**: 2,000
  - B2B Invoices: 1,780 (`INV/25-26/0001` to `INV/25-26/1780`)
  - Credit Notes: 20 (`CN/25-26/0001` to `CN/25-26/0020`)
  - B2CL Large Invoices: 100 (`B2CL/25-26/0001` to `B2CL/25-26/0100`)
  - B2CS Small Invoices: 100 (`B2CS/25-26/0001` to `B2CS/25-26/0100`)
- **GSTR-1 Population**:
  - Clean Control: Exactly mirrors Sales Register (1,780 B2B, 20 CDNR, 100 B2CL, B2CS table aggregate)
  - Prior June GSTR-1: Contains `INV/25-26/BA0001` (Taxable ₹50,000.00, 18% IGST ₹9,000.00)

## Mechanically Derived Mutation Counts
```json
{json.dumps(manifest_mutations, indent=2)}
```

## Expected Metric Verifications
- **Missing Records (G1M1)**:
  - 20 missing B2B invoices (`INV/25-26/0101` to `INV/25-26/0120`)
  - 15 unfiled B2B invoices filed under dummy GSTIN `27ZZZPK9999A1ZQ` (`INV/25-26/0221` to `INV/25-26/0235`)
  - 5 missing Credit Notes (`CN/25-26/0001` to `CN/25-26/0005`), flagged with document-aware credit note terminology
  - **Total Missing Records**: **{missing_count_exact}** ({len(missing_b2b_inums) + len(gstin_mm_inums)} invoices + {len(cn_missing_inums)} credit notes)

- **Extra in GSTR-1 (G1M2)**:
  - 15 duplicate B2B copies (`INV/25-26/0121` to `INV/25-26/0135`)
  - 20 extra B2B representations (`INV/25-26/0136` to `INV/25-26/0155`)
  - 15 unmatched GSTR-1 invoices under dummy GSTIN `27ZZZPK9999A1ZQ`
  - Zero cross-table collisions (prior `INV/25-26/BA0001` is strictly separated from fresh July invoices)
  - **Total Extra Records**: **{extra_count_exact}**

- **Amount Mismatches (G1M3)**:
  - 25 B2B taxable mismatches (+₹10,000 each)
  - 25 B2B tax amount mismatches
  - 10 B2CL taxable mismatches (+₹15,000 each)
  - 5 Credit Note taxable mismatches (+₹5,000 each)
  - 1 B2CS aggregate mismatch (+₹1,000 taxable on Table 7)
  - **Total Amount Mismatches**: **{amount_mismatch_exact}** ({amount_mismatch_exact - 1} document-level + 1 aggregate)

- **Rate Mismatches (G1M5)**:
  - Exactly **15** rate swaps (`INV/25-26/0236` to `INV/25-26/0250`)

- **Date Mismatches**:
  - Exactly **15** invoices (`INV/25-26/0206` to `INV/25-26/0220`) shifted by +10 days (outside L1/L2 tolerance, matched at Level 3 with date discrepancy noted)

- **Invoice Format Variations**:
  - Exactly **30** invoices (`INV/25-26/0251` to `INV/25-26/0280`) matched via normalization and multi-tier fuzzy matching with sequential series guard

- **Series Continuity (G1M8)**:
  - **Duplicate Invoices**: Exactly **{duplicate_count_exact}** duplicate pairs in GSTR-1 (15 from `duplicate_b2b` + 20 from `extra_b2b`)
  - **Duplicate Message Source**: Accurately reports `"appears 2 times in GSTR-1"`

- **Amendments (G1M11)**:
  - Valid B2BA (`INV/25-26/BA0001`): Successfully verified against June original; only current-period delta (+₹5,000.00 taxable, +₹900.00 IGST) affects aggregation
  - Invalid B2BA (`NONEXIST-999`): Flagged as `G1M_011_UNMATCHED_AMENDMENT` and excluded from turnover

## Financial Totals & Expected Tie-Out Variances
- **Clean Sales Register Baseline**:
  - Taxable Value: ₹{sr_taxable_tot:,.2f}
  - IGST: ₹{sr_igst_tot:,.2f}
  - CGST: ₹{sr_cgst_tot:,.2f}
  - SGST: ₹{sr_sgst_tot:,.2f}
- **Clean GSTR-3B Baseline**:
  - Reconciles 100% to Clean Sales Register (Zero Variance)
- **Net GSTR-1 Evaluated Liability**:
  - Taxable Value: ₹{net_tieout_txval:,.2f}
  - IGST: ₹{net_tieout_iamt:,.2f}
  - CGST: ₹{net_tieout_camt:,.2f}
  - SGST: ₹{net_tieout_samt:,.2f}
- **Expected Tie-Out Variances**:
  - Taxable Variance: **₹{taxable_variance:,.2f}**
  - IGST Variance: **₹{igst_variance:,.2f}**
  - CGST Variance: **₹{cgst_variance:,.2f}**
  - SGST Variance: **₹{sgst_variance:,.2f}**
"""
    expected_path = output_dir / "EXPECTED_RESULT.md"
    with open(expected_path, mode="w", encoding="utf-8") as f:
        f.write(expected_md)

    print("Benchmark generation completed successfully.")
    print(f"Output directory: {output_dir}")
    print(f"Sales Register rows: {len(sr_rows)}")
    print(f"Duplicate count: {duplicate_count_exact}")
    print(f"Taxable variance: {taxable_variance}")
    print(f"IGST variance: {igst_variance}")
    return manifest


if __name__ == "__main__":
    import sys
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("benchmark_data/fuzz_2000_clean")
    generate_benchmark(out)
