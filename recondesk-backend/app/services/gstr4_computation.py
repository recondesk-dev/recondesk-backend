"""GSTR-4 Composition Scheme Annual Return Computation Engine.

Computes system values for Tables 1-9 of Form GSTR-4 for Composition Taxpayers.
Calculates composition rate-wise outward tax liabilities (1% Trader/Manufacturer, 5% Restaurant, 6% Service),
aggregates quarterly CMP-08 payments, calculates inward RCM liabilities, applies CA audit cell overrides,
and exports official GSTN portal GSTR-4 JSON payloads.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from supabase import Client

logger = logging.getLogger(__name__)

# Standard Composition Tax Rates by Category
COMPOSITION_RATES = {
    "trader": {"cgst_rate": 0.5, "sgst_rate": 0.5, "total_rate": 1.0, "label": "Trader / Manufacturer (1%)"},
    "manufacturer": {"cgst_rate": 0.5, "sgst_rate": 0.5, "total_rate": 1.0, "label": "Trader / Manufacturer (1%)"},
    "restaurant": {"cgst_rate": 2.5, "sgst_rate": 2.5, "total_rate": 5.0, "label": "Restaurant Services (5%)"},
    "service": {"cgst_rate": 3.0, "sgst_rate": 3.0, "total_rate": 6.0, "label": "Service Provider / Other (6%)"},
}


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        return round(float(val), 2)
    except (TypeError, ValueError):
        return default


def parse_fy_label(fy: str) -> tuple[int, int]:
    """Parse FY label like '2025-26' into start year and end year (2025, 2026)."""
    parts = fy.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"Invalid financial_year format '{fy}'. Expected format 'YYYY-YY' e.g. '2025-26'.")
    start = int(parts[0])
    short_end = int(parts[1])
    century = (start // 100) * 100
    end = century + short_end
    if end <= start:
        end += 100
    return start, end


def fy_periods(start_year: int) -> list[str]:
    """Generate 12 period strings YYYYMM for a financial year starting April."""
    periods = []
    for m in range(4, 13):
        periods.append(f"{start_year}{m:02d}")
    next_year = start_year + 1
    for m in range(1, 4):
        periods.append(f"{next_year}{m:02d}")
    return periods


def _ensure_gstr4_tables_exist(conn: Any) -> None:
    """SQL self-healing fallback for direct database connections."""
    import sqlalchemy as sa
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS public.gstr4_cmp08_records (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                financial_year TEXT NOT NULL,
                quarter TEXT NOT NULL,
                outward_taxable NUMERIC(15, 2) DEFAULT 0.00,
                outward_tax NUMERIC(15, 2) DEFAULT 0.00,
                rcm_taxable NUMERIC(15, 2) DEFAULT 0.00,
                rcm_tax NUMERIC(15, 2) DEFAULT 0.00,
                igst NUMERIC(15, 2) DEFAULT 0.00,
                cgst NUMERIC(15, 2) DEFAULT 0.00,
                sgst NUMERIC(15, 2) DEFAULT 0.00,
                cess NUMERIC(15, 2) DEFAULT 0.00,
                interest NUMERIC(15, 2) DEFAULT 0.00,
                late_fee NUMERIC(15, 2) DEFAULT 0.00,
                updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT uq_gstr4_cmp08_quarter UNIQUE (client_gstin_id, financial_year, quarter)
            );

            CREATE TABLE IF NOT EXISTS public.gstr4_audit_overrides (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                client_gstin_id UUID NOT NULL REFERENCES public.client_gstins(id) ON DELETE CASCADE,
                financial_year TEXT NOT NULL,
                table_key TEXT NOT NULL,
                cell_key TEXT NOT NULL,
                system_value NUMERIC(15, 2) DEFAULT 0.00,
                override_value NUMERIC(15, 2) NOT NULL,
                notes TEXT,
                updated_by UUID REFERENCES auth.users(id) ON DELETE SET NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
                CONSTRAINT uq_gstr4_override_cell UNIQUE (client_gstin_id, financial_year, table_key, cell_key)
            );
            """
        )
    )
    conn.commit()


def load_gstr4_overrides(sb: Client, client_gstin_id: str, fy: str) -> dict[str, dict[str, Any]]:
    """Load existing CA audit overrides for a client and FY."""
    try:
        res = (
            sb.table("gstr4_audit_overrides")
            .select("table_key, cell_key, system_value, override_value, notes")
            .eq("client_gstin_id", client_gstin_id)
            .eq("financial_year", fy)
            .execute()
        )
        rows = res.data or []
        result = {}
        for r in rows:
            key = f"{r['table_key']}.{r['cell_key']}"
            result[key] = {
                "system_value": _safe_float(r.get("system_value")),
                "override_value": _safe_float(r.get("override_value")),
                "notes": r.get("notes") or "",
            }
        return result
    except Exception as exc:
        logger.warning("Supabase PostgREST query failed for gstr4_audit_overrides: %s", exc)
        try:
            from app.config import get_settings
            import sqlalchemy as sa
            s = get_settings()
            db_url = s.SUPABASE_DATABASE_URL or s.DATABASE_URL
            if db_url:
                eng = sa.create_engine(db_url)
                with eng.connect() as conn:
                    _ensure_gstr4_tables_exist(conn)
                    res = conn.execute(
                        sa.text(
                            "SELECT table_key, cell_key, system_value, override_value, notes "
                            "FROM public.gstr4_audit_overrides "
                            "WHERE client_gstin_id = :cid AND financial_year = :fy"
                        ),
                        {"cid": client_gstin_id, "fy": fy},
                    )
                    rows = res.mappings().all()
                    eng.dispose()
                    result = {}
                    for r in rows:
                        key = f"{r['table_key']}.{r['cell_key']}"
                        result[key] = {
                            "system_value": _safe_float(r.get("system_value")),
                            "override_value": _safe_float(r.get("override_value")),
                            "notes": r.get("notes") or "",
                        }
                    return result
        except Exception as sql_exc:
            logger.warning("Direct SQL fallback failed for load_gstr4_overrides: %s", sql_exc)
        return {}


def load_gstr4_cmp08_records(sb: Client, client_gstin_id: str, fy: str) -> list[dict[str, Any]]:
    """Load quarterly CMP-08 summary records (Q1..Q4) for client & FY."""
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    default_cmp08 = {
        q: {
            "quarter": q,
            "outward_taxable": 0.0,
            "outward_tax": 0.0,
            "rcm_taxable": 0.0,
            "rcm_tax": 0.0,
            "igst": 0.0,
            "cgst": 0.0,
            "sgst": 0.0,
            "cess": 0.0,
            "interest": 0.0,
            "late_fee": 0.0,
        }
        for q in quarters
    }

    has_saved_data = False
    try:
        res = (
            sb.table("gstr4_cmp08_records")
            .select("*")
            .eq("client_gstin_id", client_gstin_id)
            .eq("financial_year", fy)
            .execute()
        )
        data = res.data or []
        if data:
            has_saved_data = True
        for row in data:
            q = row.get("quarter")
            if q in default_cmp08:
                default_cmp08[q] = {
                    "quarter": q,
                    "outward_taxable": _safe_float(row.get("outward_taxable")),
                    "outward_tax": _safe_float(row.get("outward_tax")),
                    "rcm_taxable": _safe_float(row.get("rcm_taxable")),
                    "rcm_tax": _safe_float(row.get("rcm_tax")),
                    "igst": _safe_float(row.get("igst")),
                    "cgst": _safe_float(row.get("cgst")),
                    "sgst": _safe_float(row.get("sgst")),
                    "cess": _safe_float(row.get("cess")),
                    "interest": _safe_float(row.get("interest")),
                    "late_fee": _safe_float(row.get("late_fee")),
                }
    except Exception as exc:
        logger.warning("Could not fetch CMP-08 records from Supabase: %s", exc)

    return [default_cmp08[q] for q in quarters], has_saved_data


def save_cmp08_records(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    records: list[dict[str, Any]],
    updater_id: str | None = None,
) -> list[dict[str, Any]]:
    """Upsert quarterly CMP-08 summary records."""
    saved = []
    for rec in records:
        q = rec.get("quarter", "").strip().upper()
        if q not in ("Q1", "Q2", "Q3", "Q4"):
            continue
        payload = {
            "client_gstin_id": client_gstin_id,
            "financial_year": fy,
            "quarter": q,
            "outward_taxable": _safe_float(rec.get("outward_taxable")),
            "outward_tax": _safe_float(rec.get("outward_tax")),
            "rcm_taxable": _safe_float(rec.get("rcm_taxable")),
            "rcm_tax": _safe_float(rec.get("rcm_tax")),
            "igst": _safe_float(rec.get("igst")),
            "cgst": _safe_float(rec.get("cgst")),
            "sgst": _safe_float(rec.get("sgst")),
            "cess": _safe_float(rec.get("cess")),
            "interest": _safe_float(rec.get("interest")),
            "late_fee": _safe_float(rec.get("late_fee")),
        }
        if updater_id and len(updater_id) == 36:
            payload["updated_by"] = updater_id

        try:
            res = (
                sb.table("gstr4_cmp08_records")
                .upsert(payload, on_conflict="client_gstin_id,financial_year,quarter")
                .execute()
            )
            if res.data:
                saved.extend(res.data)
        except Exception as exc:
            logger.error("Failed to upsert CMP-08 record for %s %s: %s", fy, q, exc)

    recs, _ = load_gstr4_cmp08_records(sb, client_gstin_id, fy)
    return saved if saved else recs


def save_gstr4_audit_overrides(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    overrides: list[dict[str, Any]],
    updater_id: str | None = None,
) -> None:
    """Save or update CA audit overrides for GSTR-4 cells."""
    for item in overrides:
        table_key = str(item.get("table_key", "")).strip()
        cell_key = str(item.get("cell_key", "")).strip()
        if not table_key or not cell_key:
            continue
        
        override_val = _safe_float(item.get("override_value"))
        sys_val = _safe_float(item.get("system_value"))
        notes = item.get("notes") or ""

        payload = {
            "client_gstin_id": client_gstin_id,
            "financial_year": fy,
            "table_key": table_key,
            "cell_key": cell_key,
            "system_value": sys_val,
            "override_value": override_val,
            "notes": notes,
        }
        if updater_id and len(updater_id) == 36:
            payload["updated_by"] = updater_id

        try:
            sb.table("gstr4_audit_overrides").upsert(
                payload, on_conflict="client_gstin_id,financial_year,table_key,cell_key"
            ).execute()
        except Exception as exc:
            logger.warning("Failed to save gstr4_audit_override cell %s.%s via Supabase: %s", table_key, cell_key, exc)


def compute_gstr4(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    composition_category: str = "trader",
) -> dict[str, Any]:
    """Compute complete system figures for Form GSTR-4 Tables 1 to 9."""
    category_key = composition_category.lower().strip()
    if category_key not in COMPOSITION_RATES:
        category_key = "trader"
    rate_info = COMPOSITION_RATES[category_key]

    start_year, end_year = parse_fy_label(fy)
    periods = set(fy_periods(start_year))

    # Fetch client details
    client_info = {}
    try:
        res = (
            sb.table("client_gstins")
            .select("gstin, legal_name, trade_name, state_code")
            .eq("id", client_gstin_id)
            .limit(1)
            .execute()
        )
        if res.data:
            client_info = res.data[0]
    except Exception as exc:
        logger.warning("Could not fetch client GSTIN metadata: %s", exc)

    # 1. Load CA cell overrides
    overrides = load_gstr4_overrides(sb, client_gstin_id, fy)

    def resolve_cell(table_key: str, cell_key: str, sys_val: float) -> dict[str, Any]:
        k = f"{table_key}.{cell_key}"
        ov = overrides.get(k)
        if ov is not None:
            eff_val = ov["override_value"]
            return {
                "system_value": sys_val,
                "effective_value": eff_val,
                "override_value": eff_val,
                "notes": ov.get("notes") or "",
                "is_overridden": True,
            }
        return {
            "system_value": sys_val,
            "effective_value": sys_val,
            "override_value": None,
            "notes": "",
            "is_overridden": False,
        }

    # 2. Load CMP-08 Quarterly Figures (Table 5)
    cmp08_rows, has_cmp08_data = load_gstr4_cmp08_records(sb, client_gstin_id, fy)
    cmp08_q1 = cmp08_rows[0]
    cmp08_q2 = cmp08_rows[1]
    cmp08_q3 = cmp08_rows[2]
    cmp08_q4 = cmp08_rows[3]

    table5_outward_taxable_sys = sum(r["outward_taxable"] for r in cmp08_rows)
    table5_outward_tax_sys = sum(r["outward_tax"] for r in cmp08_rows)
    table5_rcm_taxable_sys = sum(r["rcm_taxable"] for r in cmp08_rows)
    table5_rcm_tax_sys = sum(r["rcm_tax"] for r in cmp08_rows)
    table5_igst_sys = sum(r["igst"] for r in cmp08_rows)
    table5_cgst_sys = sum(r["cgst"] for r in cmp08_rows)
    table5_sgst_sys = sum(r["sgst"] for r in cmp08_rows)
    table5_cess_sys = sum(r["cess"] for r in cmp08_rows)
    table5_interest_sys = sum(r["interest"] for r in cmp08_rows)
    table5_late_fee_sys = sum(r["late_fee"] for r in cmp08_rows)

    table5 = {
        "q1": cmp08_q1,
        "q2": cmp08_q2,
        "q3": cmp08_q3,
        "q4": cmp08_q4,
        "outward_taxable": resolve_cell("table5", "outward_taxable", table5_outward_taxable_sys),
        "outward_tax": resolve_cell("table5", "outward_tax", table5_outward_tax_sys),
        "rcm_taxable": resolve_cell("table5", "rcm_taxable", table5_rcm_taxable_sys),
        "rcm_tax": resolve_cell("table5", "rcm_tax", table5_rcm_tax_sys),
        "igst": resolve_cell("table5", "igst", table5_igst_sys),
        "cgst": resolve_cell("table5", "cgst", table5_cgst_sys),
        "sgst": resolve_cell("table5", "sgst", table5_sgst_sys),
        "cess": resolve_cell("table5", "cess", table5_cess_sys),
        "interest": resolve_cell("table5", "interest", table5_interest_sys),
        "late_fee": resolve_cell("table5", "late_fee", table5_late_fee_sys),
    }

    # 3. Table 4: Inward Supplies summary from PR / GSTR-2B / Sales Register if present
    # Fetch purchase register invoices for period if available
    inward_4a_taxable_sys = 0.0
    inward_4a_igst_sys = 0.0
    inward_4a_cgst_sys = 0.0
    inward_4a_sgst_sys = 0.0
    inward_4a_cess_sys = 0.0

    inward_4b_taxable_sys = 0.0
    inward_4b_tax_sys = 0.0

    inward_4c_taxable_sys = 0.0
    inward_4c_tax_sys = 0.0

    inward_4d_taxable_sys = 0.0
    inward_4d_tax_sys = 0.0

    try:
        pr_res = (
            sb.table("pr_records")
            .select("taxable_value, igst, cgst, sgst, cess, is_reverse_charge, supplier_gstin, is_unregistered")
            .eq("client_gstin_id", client_gstin_id)
            .in_("return_period", list(periods))
            .execute()
        )
        for row in (pr_res.data or []):
            tx = _safe_float(row.get("taxable_value"))
            i = _safe_float(row.get("igst"))
            c = _safe_float(row.get("cgst"))
            s = _safe_float(row.get("sgst"))
            cs = _safe_float(row.get("cess"))
            is_rcm = bool(row.get("is_reverse_charge"))
            is_unreg = bool(row.get("is_unregistered"))

            if is_rcm:
                if is_unreg:
                    inward_4c_taxable_sys += tx
                    inward_4c_tax_sys += (i + c + s)
                else:
                    inward_4b_taxable_sys += tx
                    inward_4b_tax_sys += (i + c + s)
            else:
                inward_4a_taxable_sys += tx
                inward_4a_igst_sys += i
                inward_4a_cgst_sys += c
                inward_4a_sgst_sys += s
                inward_4a_cess_sys += cs
    except Exception as exc:
        logger.warning("Could not aggregate PR records for GSTR-4 Table 4: %s", exc)

    table4 = {
        "4A_registered_non_rcm": {
            "taxable_value": resolve_cell("table4", "4A_taxable", inward_4a_taxable_sys),
            "igst": resolve_cell("table4", "4A_igst", inward_4a_igst_sys),
            "cgst": resolve_cell("table4", "4A_cgst", inward_4a_cgst_sys),
            "sgst": resolve_cell("table4", "4A_sgst", inward_4a_sgst_sys),
            "cess": resolve_cell("table4", "4A_cess", inward_4a_cess_sys),
        },
        "4B_registered_rcm": {
            "taxable_value": resolve_cell("table4", "4B_taxable", inward_4b_taxable_sys),
            "tax_payable": resolve_cell("table4", "4B_tax", inward_4b_tax_sys),
        },
        "4C_unregistered_rcm": {
            "taxable_value": resolve_cell("table4", "4C_taxable", inward_4c_taxable_sys),
            "tax_payable": resolve_cell("table4", "4C_tax", inward_4c_tax_sys),
        },
        "4D_import_services": {
            "taxable_value": resolve_cell("table4", "4D_taxable", inward_4d_taxable_sys),
            "tax_payable": resolve_cell("table4", "4D_tax", inward_4d_tax_sys),
        },
    }

    # 4. Table 6: Rate-wise Outward Turnover & Tax Liability
    outward_turnover_sys = table5["outward_taxable"]["effective_value"]
    cgst_rate = rate_info["cgst_rate"]
    sgst_rate = rate_info["sgst_rate"]
    total_rate = rate_info["total_rate"]

    outward_cgst_sys = round(outward_turnover_sys * (cgst_rate / 100.0), 2)
    outward_sgst_sys = round(outward_turnover_sys * (sgst_rate / 100.0), 2)
    outward_tax_total_sys = outward_cgst_sys + outward_sgst_sys

    rcm_inward_taxable_sys = table5["rcm_taxable"]["effective_value"]
    rcm_inward_tax_sys = table5["rcm_tax"]["effective_value"]

    table6 = {
        "composition_category": category_key,
        "category_label": rate_info["label"],
        "rate_percentages": {
            "cgst_rate": cgst_rate,
            "sgst_rate": sgst_rate,
            "total_rate": total_rate,
        },
        "outward_supplies": {
            "turnover": resolve_cell("table6", "outward_turnover", outward_turnover_sys),
            "cgst": resolve_cell("table6", "outward_cgst", outward_cgst_sys),
            "sgst": resolve_cell("table6", "outward_sgst", outward_sgst_sys),
            "tax_total": resolve_cell("table6", "outward_tax_total", outward_tax_total_sys),
        },
        "inward_rcm_supplies": {
            "taxable_value": resolve_cell("table6", "rcm_taxable", rcm_inward_taxable_sys),
            "tax_total": resolve_cell("table6", "rcm_tax_total", rcm_inward_tax_sys),
        },
        "total_tax_payable": {
            "igst": resolve_cell("table6", "total_igst", table5["igst"]["effective_value"]),
            "cgst": resolve_cell(
                "table6",
                "total_cgst",
                round(outward_cgst_sys + (table5["cgst"]["effective_value"] / 2.0 if rcm_inward_tax_sys > 0 else 0.0), 2),
            ),
            "sgst": resolve_cell(
                "table6",
                "total_sgst",
                round(outward_sgst_sys + (table5["sgst"]["effective_value"] / 2.0 if rcm_inward_tax_sys > 0 else 0.0), 2),
            ),
            "cess": resolve_cell("table6", "total_cess", table5["cess"]["effective_value"]),
        },
    }

    # 5. Table 7: TDS/TCS Credit received
    table7 = {
        "tds_credit": resolve_cell("table7", "tds_credit", 0.0),
        "tcs_credit": resolve_cell("table7", "tcs_credit", 0.0),
    }

    # 6. Table 8: Tax, Interest, and Late Fee Payable vs Paid (CMP-08 Discrepancy)
    tax_payable_total = (
        table6["total_tax_payable"]["cgst"]["effective_value"]
        + table6["total_tax_payable"]["sgst"]["effective_value"]
        + table6["total_tax_payable"]["igst"]["effective_value"]
        + table6["total_tax_payable"]["cess"]["effective_value"]
    )
    cmp08_tax_paid_total = table5["outward_tax"]["effective_value"] + table5["rcm_tax"]["effective_value"]
    tax_balance_sys = max(0.0, round(tax_payable_total - cmp08_tax_paid_total, 2))

    # Statutory GSTR-4 Due Date:
    # Notification No. 12/2024-Central Tax (Rule 62(1)):
    # FY 2024-25 onwards: June 30 following FY end (e.g., June 30, 2026 for FY 2025-26).
    # FY 2023-24 and earlier: April 30 following FY end.
    if start_year >= 2024:
        due_date = date(end_year, 6, 30)
    else:
        due_date = date(end_year, 4, 30)

    today = date.today()
    days_late = max(0, (today - due_date).days) if today > due_date else 0

    # Late Fee Rationalization under Section 47 (Notification No. 21/2021-Central Tax):
    # Daily rate: ₹50 per day (₹25 CGST + ₹25 SGST)
    # Capped at ₹500 (₹250 CGST + ₹250 SGST) for Nil Returns (tax_payable_total == 0)
    # Capped at ₹2,000 (₹1,000 CGST + ₹1,000 SGST) for Regular Returns (tax_payable_total > 0)
    late_fee_per_day = 50.0
    is_nil_return = (tax_payable_total == 0.0)
    late_fee_cap = 500.0 if is_nil_return else 2000.0
    calc_late_fee = min(late_fee_cap, days_late * late_fee_per_day)

    table8 = {
        "tax_payable": resolve_cell("table8", "tax_payable", tax_payable_total),
        "cmp08_tax_paid": resolve_cell("table8", "cmp08_tax_paid", cmp08_tax_paid_total),
        "balance_tax_payable": resolve_cell("table8", "balance_tax_payable", tax_balance_sys),
        "due_date": due_date.isoformat(),
        "days_late": days_late,
        "is_nil_return": is_nil_return,
        "late_fee_cap": late_fee_cap,
        "late_fee_payable": resolve_cell("table8", "late_fee_payable", calc_late_fee),
        "interest_payable": resolve_cell("table8", "interest_payable", table5["interest"]["effective_value"]),
    }

    # 7. Table 9: Refund Claimed
    table9 = {
        "refund_claimed": resolve_cell("table9", "refund_claimed", 0.0),
    }

    # Discrepancy warning checks
    warnings = []
    if not has_cmp08_data:
        warnings.append({
            "code": "CMP08_DATA_PENDING",
            "message": f"No quarterly CMP-08 figures saved for FY {fy} yet. Values default to ₹0.00 until Q1–Q4 figures are entered.",
            "severity": "INFO",
        })
    if tax_balance_sys > 0:
        warnings.append({
            "code": "CMP08_SHORTFALL",
            "message": f"Annual tax liability exceeds CMP-08 quarterly payments by ₹{tax_balance_sys:,.2f}. Balance payable in cash.",
            "severity": "WARNING",
        })
    if days_late > 0:
        cap_type_label = "Nil Return ₹500 cap" if is_nil_return else "Normal Return ₹2,000 cap"
        warnings.append({
            "code": "FILING_DELAY",
            "message": f"Filing is {days_late} days past due date ({due_date.strftime('%b %d, %Y')}). Estimated late fee: ₹{calc_late_fee:,.2f} ({cap_type_label}).",
            "severity": "WARNING" if not is_nil_return else "INFO",
        })

    return {
        "client_id": client_gstin_id,
        "gstin": client_info.get("gstin", ""),
        "legal_name": client_info.get("legal_name", ""),
        "trade_name": client_info.get("trade_name", ""),
        "financial_year": fy,
        "composition_category": category_key,
        "tables": {
            "table4": table4,
            "table5": table5,
            "table6": table6,
            "table7": table7,
            "table8": table8,
            "table9": table9,
        },
        "kpi_summary": {
            "outward_turnover": table5["outward_taxable"]["effective_value"],
            "total_tax_payable": tax_payable_total,
            "cmp08_tax_paid": cmp08_tax_paid_total,
            "balance_cash_payable": tax_balance_sys,
            "days_late": days_late,
            "late_fee_payable": table8["late_fee_payable"]["effective_value"],
            "has_cmp08_data": has_cmp08_data,
        },
        "warnings": warnings,
    }


def build_gstr4_gstn_json(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    composition_category: str = "trader",
) -> dict[str, Any]:
    """Format Form GSTR-4 computed & overridden values into official GSTN portal JSON schema."""
    comp = compute_gstr4(sb, client_gstin_id, fy, composition_category)
    tables = comp["tables"]

    gstn_json = {
        "gstin": comp["gstin"],
        "fp": f"{fy.split('-')[0][-2:]}{fy.split('-')[1]}", # e.g. "2526"
        "fy": fy,
        "turnover_prev_fy": 0.0,
        "table4": {
            "inward_reg_non_rcm": tables["table4"]["4A_registered_non_rcm"],
            "inward_reg_rcm": tables["table4"]["4B_registered_rcm"],
            "inward_unreg_rcm": tables["table4"]["4C_unregistered_rcm"],
            "import_services": tables["table4"]["4D_import_services"],
        },
        "table5": {
            "outward_taxable": tables["table5"]["outward_taxable"]["effective_value"],
            "outward_tax": tables["table5"]["outward_tax"]["effective_value"],
            "rcm_taxable": tables["table5"]["rcm_taxable"]["effective_value"],
            "rcm_tax": tables["table5"]["rcm_tax"]["effective_value"],
            "igst": tables["table5"]["igst"]["effective_value"],
            "cgst": tables["table5"]["cgst"]["effective_value"],
            "sgst": tables["table5"]["sgst"]["effective_value"],
            "cess": tables["table5"]["cess"]["effective_value"],
        },
        "table6": {
            "composition_rate": tables["table6"]["rate_percentages"]["total_rate"],
            "outward_turnover": tables["table6"]["outward_supplies"]["turnover"]["effective_value"],
            "cgst": tables["table6"]["outward_supplies"]["cgst"]["effective_value"],
            "sgst": tables["table6"]["outward_supplies"]["sgst"]["effective_value"],
            "total_tax_payable": tables["table6"]["total_tax_payable"],
        },
        "table8": {
            "tax_payable": tables["table8"]["tax_payable"]["effective_value"],
            "cmp08_tax_paid": tables["table8"]["cmp08_tax_paid"]["effective_value"],
            "balance_tax_payable": tables["table8"]["balance_tax_payable"]["effective_value"],
            "late_fee": tables["table8"]["late_fee_payable"]["effective_value"],
        },
    }
    return gstn_json
