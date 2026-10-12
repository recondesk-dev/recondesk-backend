"""GSTR-3B Save draft suggestions (optional — never auto-applied).

Sources (already proven elsewhere):
* Outward 3.1(a) ``osup_det`` ← ``aggregate_gstr1`` (GSTR-1 vs 3B tie-out)
* ITC 4.1(A) ``OTH`` ← ``accumulate_gstr2b_available_itc``

Suggestions are drafts for the CA to Use or Dismiss. Missing source data
returns ``available=False`` — that is **not** a confirmed zero.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from app.constants import RunStatus
from app.reconciliation.gstr1_vs_3b import GSTR1Aggregate, aggregate_gstr1
from app.services.gstr3b_reconciliation import accumulate_gstr2b_available_itc
from app.services.gstr9c_itc_fy_rollup import normalize_period_yyyy_mm, paise_to_rupees

_log = logging.getLogger(__name__)

_RUN_STATUSES = (RunStatus.COMPLETED, RunStatus.FINAL)

REASON_NO_GSTR1_RUN = "no_gstr1_reconcile_run"
REASON_NO_GSTR1_AGGREGATE = "no_gstr1_aggregate"
REASON_NO_GSTR2B_RUN = "no_gstr2b_reconcile_run"
REASON_NO_GSTR2B_RECORDS = "no_gstr2b_records"


def _round_rupees(val: float) -> float:
    return round(float(val), 2)


def osup_det_from_gstr1_aggregate(agg: GSTR1Aggregate | Mapping[str, Any]) -> dict[str, float]:
    """Convert a GSTR-1 3.1(a) aggregate (paise) → Save ``osup_det`` (rupees)."""
    if isinstance(agg, GSTR1Aggregate):
        tv = agg.taxable_value_paise
        igst = agg.igst_paise
        cgst = agg.cgst_paise
        sgst = agg.sgst_paise
        cess = agg.cess_paise
    else:
        tv = int(agg.get("taxable_value_paise") or 0)
        igst = int(agg.get("igst_paise") or 0)
        cgst = int(agg.get("cgst_paise") or 0)
        sgst = int(agg.get("sgst_paise") or 0)
        cess = int(agg.get("cess_paise") or 0)
    return {
        "txval": paise_to_rupees(tv),
        "iamt": paise_to_rupees(igst),
        "camt": paise_to_rupees(cgst),
        "samt": paise_to_rupees(sgst),
        "csamt": paise_to_rupees(cess),
    }


def suggest_osup_det_from_gstr1_records(
    records: Sequence[Mapping[str, Any]],
    *,
    source: str = "GSTR-1 Table 3.1(a)",
) -> dict[str, Any]:
    """Run ``aggregate_gstr1`` and build an ``osup_det`` suggestion payload.

    Returns ``available=False`` when there are no usable invoice-level rows
    contributing to the aggregate (``record_count == 0``).
    """
    agg = aggregate_gstr1(records, include_cdn=True, include_zero_rated=False)
    if agg.record_count <= 0:
        return {
            "available": False,
            "reason": REASON_NO_GSTR1_AGGREGATE,
            "source": source,
            "record_count": 0,
        }
    return {
        "available": True,
        "source": source,
        "record_count": agg.record_count,
        "osup_det": osup_det_from_gstr1_aggregate(agg),
    }


def suggest_itc_oth_from_gstr2b_records(
    records: Sequence[Mapping[str, Any]],
    *,
    source: str = "GSTR-2B Table 4.1(A) OTH",
) -> dict[str, Any]:
    """Run ``accumulate_gstr2b_available_itc`` → ``itc_avl`` OTH heads.

    ``csamt`` is always 0 here — the proven accumulator does not track cess.
    Empty ``records`` → ``available=False`` (not a confirmed zero).
    """
    usable = [r for r in records if isinstance(r, Mapping)]
    if not usable:
        return {
            "available": False,
            "reason": REASON_NO_GSTR2B_RECORDS,
            "source": source,
            "record_count": 0,
        }
    totals = accumulate_gstr2b_available_itc([dict(r) for r in usable])
    return {
        "available": True,
        "source": source,
        "record_count": len(usable),
        "iamt": _round_rupees(totals.get("igst") or 0),
        "camt": _round_rupees(totals.get("cgst") or 0),
        "samt": _round_rupees(totals.get("sgst") or 0),
        "csamt": 0.0,
    }


def _latest_gstr1_run(sb, *, client_gstin_id: str, period: str) -> dict[str, Any] | None:
    want = normalize_period_yyyy_mm(period)
    if not want:
        return None
    res = (
        sb.table("gstr1_reconciliation_run")
        .select("id, client_gstin_id, period, result_payload, created_at, completed_at")
        .eq("client_gstin_id", client_gstin_id)
        .order("created_at", desc=True)
        .limit(50)
        .execute()
    )
    for row in res.data or []:
        if normalize_period_yyyy_mm(row.get("period")) == want:
            return row
    return None


def _latest_gstr2b_run(sb, *, client_gstin_id: str, period: str) -> dict[str, Any] | None:
    want = normalize_period_yyyy_mm(period)
    if not want:
        return None
    res = (
        sb.table("reconciliation_run")
        .select("id, client_gstin_id, period, status, completed_at, created_at")
        .eq("client_gstin_id", client_gstin_id)
        .in_("status", list(_RUN_STATUSES))
        .order("completed_at", desc=True)
        .limit(100)
        .execute()
    )
    for row in res.data or []:
        if normalize_period_yyyy_mm(row.get("period")) == want:
            return row
    return None


def _load_gstr2b_record_datas(sb, run_id: str) -> list[dict[str, Any]]:
    offset = 0
    chunk = 1000
    out: list[dict[str, Any]] = []
    while True:
        res = (
            sb.table("gstr_records")
            .select("record_data")
            .eq("run_id", run_id)
            .range(offset, offset + chunk - 1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            break
        for row in rows:
            rd = row.get("record_data") if isinstance(row, dict) else None
            if isinstance(rd, dict):
                out.append(rd)
        if len(rows) < chunk:
            break
        offset += chunk
    return out


def load_osup_det_suggestion(
    sb,
    *,
    client_gstin_id: str,
    period: str,
) -> dict[str, Any]:
    """Draft from the latest GSTR-1 reconcile run's ``tie_out.gstr1`` aggregate.

    That aggregate is produced by ``aggregate_gstr1`` at reconcile time.
    """
    run = _latest_gstr1_run(sb, client_gstin_id=client_gstin_id, period=period)
    if not run:
        return {
            "available": False,
            "reason": REASON_NO_GSTR1_RUN,
            "period": normalize_period_yyyy_mm(period) or period,
        }

    payload = run.get("result_payload") if isinstance(run.get("result_payload"), dict) else {}
    tie_out = payload.get("tie_out") if isinstance(payload.get("tie_out"), dict) else {}
    gstr1 = tie_out.get("gstr1") if isinstance(tie_out.get("gstr1"), dict) else None
    if not gstr1:
        return {
            "available": False,
            "reason": REASON_NO_GSTR1_AGGREGATE,
            "period": normalize_period_yyyy_mm(period) or period,
            "run_id": str(run.get("id") or "") or None,
        }

    record_count = int(tie_out.get("gstr1_record_count") or gstr1.get("record_count") or 0)
    source = f"GSTR-1 Table 3.1(a) (reconcile run {run.get('id')})"
    if record_count <= 0 and not any(
        int(gstr1.get(k) or 0)
        for k in (
            "taxable_value_paise",
            "igst_paise",
            "cgst_paise",
            "sgst_paise",
            "cess_paise",
        )
    ):
        return {
            "available": False,
            "reason": REASON_NO_GSTR1_AGGREGATE,
            "period": normalize_period_yyyy_mm(period) or period,
            "run_id": str(run.get("id") or "") or None,
            "source": source,
            "record_count": 0,
        }

    osup = osup_det_from_gstr1_aggregate(gstr1)
    gstr1a_applied = False
    gstr1a_meta: dict[str, Any] = {}
    try:
        norm_p = normalize_period_yyyy_mm(period) or period
        # Prevent double-counting if the baseline reconcile run already incorporated GSTR-1A adjustments
        already_incorporated = bool(
            tie_out.get("gstr1a_applied")
            or gstr1.get("gstr1a_applied")
            or (run.get("result_payload") or {}).get("gstr1a_applied")
            or run.get("gstr1a_applied")
        )
        if already_incorporated:
            _log.info(
                "Baseline GSTR-1 reconcile run %s already includes GSTR-1A deltas; skipping batch delta addition to prevent double-counting.",
                run.get("id"),
            )
            gstr1a_applied = True
            gstr1a_meta = {"already_incorporated_in_baseline": True, "source_run_id": run.get("id")}
        else:
            b_res = (
                sb.table("gstr1a_amendment_batches")
                .select("id, status, delta_taxable_value, delta_igst, delta_cgst, delta_sgst, delta_cess, total_additions, total_amendments, figures_digest")
                .eq("client_gstin_id", client_gstin_id)
                .eq("period", norm_p)
                .execute()
            )
            eligible_statuses = {"APPROVED", "SAVED", "FILED"}
            if b_res.data and len(b_res.data) > 0:
                priority_order = {"FILED": 3, "SAVED": 2, "APPROVED": 1}
                eligible_batches = [
                    b for b in b_res.data
                    if str(b.get("status") or "").upper() in eligible_statuses
                ]
                if eligible_batches:
                    eligible_batches.sort(
                        key=lambda b: priority_order.get(str(b.get("status") or "").upper(), 0),
                        reverse=True,
                    )
                    batch = eligible_batches[0]
                    d_txval = float(batch.get("delta_taxable_value") or 0)
                    d_igst = float(batch.get("delta_igst") or 0)
                    d_cgst = float(batch.get("delta_cgst") or 0)
                    d_sgst = float(batch.get("delta_sgst") or 0)
                    d_cess = float(batch.get("delta_cess") or 0)

                    osup["txval"] = _round_rupees(osup["txval"] + d_txval)
                    osup["iamt"] = _round_rupees(osup["iamt"] + d_igst)
                    osup["camt"] = _round_rupees(osup["camt"] + d_cgst)
                    osup["samt"] = _round_rupees(osup["samt"] + d_sgst)
                    osup["csamt"] = _round_rupees(osup["csamt"] + d_cess)
                    gstr1a_applied = True
                    gstr1a_meta = {
                        "batch_id": batch.get("id"),
                        "status": batch.get("status"),
                        "figures_digest": batch.get("figures_digest"),
                        "delta_taxable_value": d_txval,
                        "delta_igst": d_igst,
                        "delta_cgst": d_cgst,
                        "delta_sgst": d_sgst,
                        "delta_cess": d_cess,
                    }
                    source = f"{source} + GSTR-1A adjustments"
                else:
                    _log.info(
                        "Found GSTR-1A batch(es) for period %s but none in eligible status (%s); Table 3.1 unchanged.",
                        norm_p,
                        eligible_statuses,
                    )
    except Exception as exc:
        _log.warning("Could not apply GSTR-1A adjustments to GSTR-3B osup_det: %s", exc)



    ret = {
        "available": True,
        "source": source,
        "period": normalize_period_yyyy_mm(period) or period,
        "run_id": str(run.get("id") or "") or None,
        "record_count": record_count,
        "osup_det": osup,
    }
    if gstr1a_applied:
        ret["gstr1a_applied"] = True
        ret["gstr1a"] = gstr1a_meta
    return ret


def load_itc_oth_suggestion(
    sb,
    *,
    client_gstin_id: str,
    period: str,
) -> dict[str, Any]:
    """Draft OTH ITC from the latest COMPLETED/FINAL purchase reconcile run."""
    run = _latest_gstr2b_run(sb, client_gstin_id=client_gstin_id, period=period)
    if not run:
        return {
            "available": False,
            "reason": REASON_NO_GSTR2B_RUN,
            "period": normalize_period_yyyy_mm(period) or period,
        }

    run_id = str(run.get("id") or "")
    records = _load_gstr2b_record_datas(sb, run_id)
    base = suggest_itc_oth_from_gstr2b_records(
        records,
        source=f"GSTR-2B Table 4.1(A) OTH (reconcile run {run_id})",
    )
    base["period"] = normalize_period_yyyy_mm(period) or period
    base["run_id"] = run_id or None
    return base


def load_table4_suggestion(
    sb,
    *,
    client_gstin_id: str,
    period: str,
) -> dict[str, Any]:
    """Draft full GSTR-3B Table 4 from the latest purchase reconcile run."""
    run = _latest_gstr2b_run(sb, client_gstin_id=client_gstin_id, period=period)
    if not run:
        return {
            "available": False,
            "status": "unavailable",
            "reason": REASON_NO_GSTR2B_RUN,
            "period": normalize_period_yyyy_mm(period) or period,
        }

    run_id = str(run.get("id") or "")
    source = f"Reconciliation Run Table 4 (run {run_id[:8]})"
    try:
        from app.services.gstr3b_table4_engine import compile_gstr3b_table4
        t4_data = compile_gstr3b_table4(sb, run_id)
        t4 = t4_data.get("table_4") or {}
        sec_4a = t4.get("section_4a") or {}
        sec_4b = t4.get("section_4b") or {}
        sec_4c = t4.get("section_4c_net_itc") or {}
        sec_4d = t4.get("section_4d") or {}

        def _tax(d: Any) -> dict[str, float]:
            if not isinstance(d, dict):
                return {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
            return {
                "igst": round(float(d.get("igst") or 0.0), 2),
                "cgst": round(float(d.get("cgst") or 0.0), 2),
                "sgst": round(float(d.get("sgst") or d.get("samt") or 0.0), 2),
                "cess": round(float(d.get("cess") or d.get("csamt") or 0.0), 2),
            }

        impg = _tax(sec_4a.get("row_4a1_import_goods"))
        imps = _tax(sec_4a.get("row_4a2_import_services"))
        rcm = _tax(sec_4a.get("row_4a3_inward_rcm"))
        isd = _tax(sec_4a.get("row_4a4_isd"))
        oth = _tax(sec_4a.get("row_4a5_all_other_itc"))

        rul_rev = _tax(sec_4b.get("row_4b1_rule38_42_43_sec175"))
        oth_rev = _tax(sec_4b.get("row_4b2_others_rule37_37a"))

        net = _tax(sec_4c)

        reclaimed = _tax(sec_4d.get("row_4d1_reclaimed"))
        ineligible_pos = _tax(sec_4d.get("row_4d2_ineligible_16_4_pos"))

        total_avl = round(impg["igst"] + impg["cess"] + imps["igst"] + imps["cess"] + rcm["igst"] + rcm["cgst"] + rcm["sgst"] + rcm["cess"] + isd["igst"] + isd["cgst"] + isd["sgst"] + isd["cess"] + oth["igst"] + oth["cgst"] + oth["sgst"] + oth["cess"], 2)
        total_rev = round(rul_rev["igst"] + rul_rev["cgst"] + rul_rev["sgst"] + rul_rev["cess"] + oth_rev["igst"] + oth_rev["cgst"] + oth_rev["sgst"] + oth_rev["cess"], 2)
        total_net = round(net["igst"] + net["cgst"] + net["sgst"] + net["cess"], 2)
        total_inelg = round(reclaimed["igst"] + reclaimed["cgst"] + reclaimed["sgst"] + reclaimed["cess"] + ineligible_pos["igst"] + ineligible_pos["cgst"] + ineligible_pos["sgst"] + ineligible_pos["cess"], 2)

        return {
            "available": True,
            "status": "available",
            "period": normalize_period_yyyy_mm(period) or period,
            "run_id": run_id,
            "source": source,
            "summary": {
                "itc_available_tax": total_avl,
                "itc_reversed_tax": total_rev,
                "net_itc_tax": total_net,
                "ineligible_tax": total_inelg,
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "iamt": impg["igst"], "camt": 0.0, "samt": 0.0, "csamt": impg["cess"]},
                    {"ty": "IMPS", "iamt": imps["igst"], "camt": 0.0, "samt": 0.0, "csamt": imps["cess"]},
                    {"ty": "ISRC", "iamt": rcm["igst"], "camt": rcm["cgst"], "samt": rcm["sgst"], "csamt": rcm["cess"]},
                    {"ty": "ISD", "iamt": isd["igst"], "camt": isd["cgst"], "samt": isd["sgst"], "csamt": isd["cess"]},
                    {"ty": "OTH", "iamt": oth["igst"], "camt": oth["cgst"], "samt": oth["sgst"], "csamt": oth["cess"]},
                ],
                "itc_rev": [
                    {"ty": "RUL", "iamt": rul_rev["igst"], "camt": rul_rev["cgst"], "samt": rul_rev["sgst"], "csamt": rul_rev["cess"]},
                    {"ty": "OTH", "iamt": oth_rev["igst"], "camt": oth_rev["cgst"], "samt": oth_rev["sgst"], "csamt": oth_rev["cess"]},
                ],
                "itc_net": [
                    {"ty": "", "iamt": net["igst"], "camt": net["cgst"], "samt": net["sgst"], "csamt": net["cess"]},
                ],
                "itc_inelg": [
                    {"ty": "RUL", "iamt": reclaimed["igst"], "camt": reclaimed["cgst"], "samt": reclaimed["sgst"], "csamt": reclaimed["cess"]},
                    {"ty": "OTH", "iamt": ineligible_pos["igst"], "camt": ineligible_pos["cgst"], "samt": ineligible_pos["sgst"], "csamt": ineligible_pos["cess"]},
                ],
            },
        }
    except Exception as exc:
        _log.warning("load_table4_suggestion failed for run %s: %s; falling back to OTH suggestion", run_id, exc)
        oth_res = load_itc_oth_suggestion(sb, client_gstin_id=client_gstin_id, period=period)
        if not oth_res.get("available"):
            oth_res["status"] = "unavailable"
            return oth_res
        oth_tax = round(float(oth_res.get("iamt") or 0.0) + float(oth_res.get("camt") or 0.0) + float(oth_res.get("samt") or 0.0), 2)
        return {
            "available": True,
            "status": "available",
            "period": normalize_period_yyyy_mm(period) or period,
            "run_id": run_id,
            "source": f"GSTR-2B OTH fallback (run {run_id[:8]})",
            "summary": {
                "itc_available_tax": oth_tax,
                "itc_reversed_tax": 0.0,
                "net_itc_tax": oth_tax,
                "ineligible_tax": 0.0,
            },
            "itc_elg": {
                "itc_avl": [
                    {"ty": "IMPG", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "IMPS", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "ISRC", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "ISD", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": oth_res.get("iamt", 0.0), "camt": oth_res.get("camt", 0.0), "samt": oth_res.get("samt", 0.0), "csamt": 0.0},
                ],
                "itc_rev": [
                    {"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                ],
                "itc_net": [
                    {"ty": "", "iamt": oth_res.get("iamt", 0.0), "camt": oth_res.get("camt", 0.0), "samt": oth_res.get("samt", 0.0), "csamt": 0.0},
                ],
                "itc_inelg": [
                    {"ty": "RUL", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                    {"ty": "OTH", "iamt": 0.0, "camt": 0.0, "samt": 0.0, "csamt": 0.0},
                ],
            },
        }


def _load_pr_record_datas(sb, run_id: str) -> list[dict[str, Any]]:
    """Fetch purchase register records for the reconciliation run."""
    offset = 0
    chunk = 1000
    out: list[dict[str, Any]] = []
    while True:
        try:
            res = (
                sb.table("pr_records")
                .select("record_data")
                .eq("run_id", run_id)
                .range(offset, offset + chunk - 1)
                .execute()
            )
            rows = res.data or []
        except Exception as exc:
            _log.warning("pr_records fetch failed for run %s: %s", run_id, exc)
            break
        if not rows:
            break
        for row in rows:
            rd = row.get("record_data") if isinstance(row, dict) else None
            if isinstance(rd, dict):
                out.append(rd)
        if len(rows) < chunk:
            break
        offset += chunk
    return out


def load_rcm_suggestion(
    sb,
    *,
    client_gstin_id: str,
    period: str,
) -> dict[str, Any]:
    """Draft GSTR-3B Table 3.1(d) inward RCM liability from detected supplies.

    Reuses detect_rcm_inward_supplies from rcm_detector.py on the latest
    purchase reconcile run records. Never silently overwrites manual figures.
    """
    from app.reconciliation.rcm_detector import detect_rcm_inward_supplies

    clean_period = normalize_period_yyyy_mm(period) or period
    run = _latest_gstr2b_run(sb, client_gstin_id=client_gstin_id, period=clean_period)
    if not run:
        return {
            "available": False,
            "status": "unavailable",
            "reason": REASON_NO_GSTR2B_RUN,
            "period": clean_period,
        }

    run_id = str(run.get("id") or "")
    pr_records = _load_pr_record_datas(sb, run_id)
    if not pr_records:
        # Fallback to gstr_records if PR records table is sparse for this run
        pr_records = _load_gstr2b_record_datas(sb, run_id)

    if not pr_records:
        return {
            "available": False,
            "status": "unavailable",
            "reason": "no_records_for_rcm_detection",
            "period": clean_period,
            "run_id": run_id,
        }

    # Resolve recipient GSTIN state for accurate tax-head allocation
    recipient_gstin = ""
    if sb is not None:
        try:
            cg_res = sb.table("client_gstins").select("gstin").eq("id", client_gstin_id).limit(1).execute()
            if (
                cg_res
                and isinstance(getattr(cg_res, "data", None), list)
                and len(cg_res.data) > 0
                and isinstance(cg_res.data[0], dict)
                and isinstance(cg_res.data[0].get("gstin"), str)
            ):
                recipient_gstin = str(cg_res.data[0].get("gstin") or "").strip().upper()
        except Exception:
            pass
    if not recipient_gstin:
        recipient_gstin = str(run.get("client_gstin") or "").strip().upper()
    recipient_state = recipient_gstin[:2] if len(recipient_gstin) >= 2 else ""

    detected_rows = detect_rcm_inward_supplies(pr_records)
    if not detected_rows:
        return {
            "available": True,
            "status": "available",
            "source": f"RCM Detection (run {run_id[:8]})",
            "period": clean_period,
            "run_id": run_id,
            "record_count": 0,
            "isup_rev": {
                "txval": 0.0,
                "iamt": 0.0,
                "camt": 0.0,
                "samt": 0.0,
                "csamt": 0.0,
            },
            "flagged_rows": [],
            "cash_ledger_note": (
                "Section 49(4) CGST Act: Tax on inward supplies under reverse charge must be discharged "
                "strictly in cash through Electronic Cash Ledger and cannot be offset against ITC."
            ),
        }

    # Deduplicate detected rows to prevent duplicate counting of multiline/re-imported entries
    seen_fingerprints: set[tuple[Any, ...]] = set()
    unique_detected_rows: list[dict[str, Any]] = []

    tot_txval_p = 0
    tot_iamt_p = 0
    tot_camt_p = 0
    tot_samt_p = 0
    tot_csamt_p = 0

    for r in detected_rows:
        raw = r.get("raw_record") if isinstance(r.get("raw_record"), dict) else {}
        inv_num = str(r.get("invoice_number") or raw.get("invoice_number") or "").strip().upper()
        sup_gstin = str(r.get("supplier_gstin") or raw.get("supplier_gstin") or "").strip().upper()
        inv_dt = str(r.get("invoice_date") or raw.get("invoice_date") or "").strip()
        hsn = str(r.get("hsn_sac") or raw.get("hsn_sac") or "").strip()
        txval_raw = int(r.get("taxable_value_paise") or 0)

        fp = (inv_num, sup_gstin, inv_dt, hsn, txval_raw)
        if fp in seen_fingerprints and inv_num:
            continue
        seen_fingerprints.add(fp)
        unique_detected_rows.append(r)

        # Handle credit notes & reversals
        doc_type = str(raw.get("doc_type") or raw.get("document_type") or r.get("doc_type") or "").strip().upper()
        remarks = str(raw.get("remarks") or "").upper()
        is_credit_note = (
            doc_type in ("CR", "C", "CN", "CREDIT_NOTE", "CREDIT NOTE", "CDN", "CDNR")
            or "CREDIT" in remarks
            or txval_raw < 0
        )
        sign = -1 if is_credit_note else 1

        txval_p = abs(txval_raw) * sign
        iamt_p = abs(int(r.get("igst_paise") or 0)) * sign
        camt_p = abs(int(r.get("cgst_paise") or 0)) * sign
        samt_p = abs(int(r.get("sgst_paise") or 0)) * sign
        csamt_p = abs(int(r.get("cess_paise") or 0)) * sign
        tot_tax_p = abs(int(r.get("total_tax_paise") or 0)) * sign

        # Tax-head allocation: When supplier billed 0 tax under RCM but estimated RCM tax is non-zero
        if (iamt_p == 0 and camt_p == 0 and samt_p == 0) and tot_tax_p != 0:
            sup_state = sup_gstin[:2] if len(sup_gstin) >= 2 else ""
            cat = str(r.get("category") or "").upper()
            is_import = "IMPORT" in cat or not sup_state
            is_interstate = is_import or (bool(recipient_state and sup_state) and sup_state != recipient_state)

            if is_interstate:
                iamt_p = tot_tax_p
            else:
                half = tot_tax_p // 2
                camt_p = half
                samt_p = tot_tax_p - half  # Handles any odd paise exactly

        tot_txval_p += txval_p
        tot_iamt_p += iamt_p
        tot_camt_p += camt_p
        tot_samt_p += samt_p
        tot_csamt_p += csamt_p

    # Floor net totals at 0 (cannot report negative outward RCM liability on Table 3.1d)
    tot_txval_p = max(0, tot_txval_p)
    tot_iamt_p = max(0, tot_iamt_p)
    tot_camt_p = max(0, tot_camt_p)
    tot_samt_p = max(0, tot_samt_p)
    tot_csamt_p = max(0, tot_csamt_p)

    return {
        "available": True,
        "status": "available",
        "source": f"RCM Inward Detection (run {run_id[:8]})",
        "period": clean_period,
        "run_id": run_id,
        "record_count": len(unique_detected_rows),
        "isup_rev": {
            "txval": paise_to_rupees(tot_txval_p),
            "iamt": paise_to_rupees(tot_iamt_p),
            "camt": paise_to_rupees(tot_camt_p),
            "samt": paise_to_rupees(tot_samt_p),
            "csamt": paise_to_rupees(tot_csamt_p),
        },
        "flagged_rows": unique_detected_rows[:50],  # preview top 50
        "cash_ledger_note": (
            "Section 49(4) CGST Act: Tax on inward supplies under reverse charge must be discharged "
            "strictly in cash through Electronic Cash Ledger and cannot be offset against ITC."
        ),
    }

