"""GSTR-9C Reconciliation Statement Engine.

Computes Part II (Turnover Recon), Part III (ITC Recon), Part IV (Tax Paid Recon)
and generates portal-ready GSTR-9C JSON payloads for auditor DSC signing.
"""

from __future__ import annotations

import logging
from typing import Any

from supabase import Client

from app.services.gstr9_computation import compute_gstr9

logger = logging.getLogger(__name__)


def compute_gstr9c(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    audited_turnover: float = 0.0,
    audited_itc: float = 0.0,
    audited_tax: float = 0.0,
) -> dict[str, Any]:
    """Compute GSTR-9C reconciliation statement figures & variances."""
    g9 = compute_gstr9(sb, client_gstin_id, fy)

    # ── Part II: Table 5 — Turnover Reconciliation ─────────────────────────────
    g9_gross_turnover = round(
        g9["table4"]["4N_total_taxable"] + g9["table5"]["5N_total_exempted"], 2
    )
    turnover_variance = round(audited_turnover - g9_gross_turnover, 2)

    table5_turnover = {
        "5A_audited_gross_turnover": audited_turnover,
        "5P_reconciled_turnover": audited_turnover,
        "5Q_gstr9_declared_turnover": g9_gross_turnover,
        "5R_unreconciled_turnover_variance": turnover_variance,
    }

    # ── Part III: Table 12 — ITC Reconciliation ────────────────────────────────
    g9_net_itc = round(
        g9["table6"]["6A_total_3b_itc"] - g9["table7"]["7H_total_reversals"], 2
    )
    itc_variance = round(audited_itc - g9_net_itc, 2)

    table12_itc = {
        "12A_audited_itc": audited_itc,
        "12E_reconciled_itc": audited_itc,
        "12F_gstr9_declared_itc": g9_net_itc,
        "12G_unreconciled_itc_variance": itc_variance,
    }

    # ── Part IV: Table 14 — Tax Paid Reconciliation ────────────────────────────
    g9_tax_paid = round(
        g9["table9"]["igst_cash"] + g9["table9"]["cgst_cash"] + g9["table9"]["sgst_cash"]
        + g9["table9"]["igst_itc"] + g9["table9"]["cgst_itc"] + g9["table9"]["sgst_itc"],
        2
    )
    tax_variance = round(audited_tax - g9_tax_paid, 2)

    table14_tax = {
        "14A_audited_tax_payable": audited_tax,
        "14P_gstr9_tax_paid": g9_tax_paid,
        "14Q_unreconciled_tax_variance": tax_variance,
    }

    # ── Part V: Auditor Recommendation ─────────────────────────────────────────
    # Auditor recommendations require CA rate-wise tax evaluation; default to 0.00
    auditor_recommendation = {
        "additional_turnover_tax": 0.0,
        "additional_itc_reversal_tax": 0.0,
        "total_recommended_payment": 0.0,
    }

    return {
        "client_gstin_id": client_gstin_id,
        "gstin": g9["gstin"],
        "trade_name": g9["trade_name"],
        "financial_year": fy,
        "part_ii_turnover": table5_turnover,
        "part_iii_itc": table12_itc,
        "part_iv_tax_paid": table14_tax,
        "part_v_auditor_recommendation": auditor_recommendation,
    }


def build_gstr9c_portal_json(
    sb: Client,
    client_gstin_id: str,
    fy: str,
    audited_turnover: float = 0.0,
    audited_itc: float = 0.0,
    audited_tax: float = 0.0,
) -> dict[str, Any]:
    """Generate official GSTN Portal compliant GSTR-9C JSON payload for DSC signing."""
    g9c = compute_gstr9c(sb, client_gstin_id, fy, audited_turnover, audited_itc, audited_tax)

    return {
        "gstin": g9c["gstin"],
        "fp": fy.replace("-", ""),
        "turnover_recon": g9c["part_ii_turnover"],
        "itc_recon": g9c["part_iii_itc"],
        "tax_recon": g9c["part_iv_tax_paid"],
        "recommendations": g9c["part_v_auditor_recommendation"],
    }
