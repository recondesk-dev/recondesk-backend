"""Bidirectional GSTR ↔ PR reconciliation orchestration."""

from __future__ import annotations

from collections import defaultdict

from app.services.matcher import (
    INVOICE_SIMILARITY_L5_MIN,
    MatchResult,
    invoice_similarity,
    match_gstr_to_pr,
)


def _taxable_paise(rec: dict) -> int:
    v = rec.get("taxable_amount_paise")
    if v is None:
        return 0
    return int(v)


def _tie_key(
    result: MatchResult,
    gstr_rec: dict,
    pr_rec: dict,
) -> tuple[int, int, int]:
    """Sort key: lower level first, higher confidence, smaller taxable gap."""
    return (
        result.level,
        -result.confidence,
        abs(_taxable_paise(gstr_rec) - _taxable_paise(pr_rec)),
    )


def _accept_reconciliation_pair(
    gstr_rec: dict, pr_rec: dict, result: MatchResult
) -> bool:
    """Gate matcher output for 1:1 reconciliation: same GSTIN, no L4/L6, min invoice sim."""
    if result.level == 6 or result.level > 5:
        return False
    g_gst = str(gstr_rec.get("supplier_gstin") or "").strip()
    p_gst = str(pr_rec.get("supplier_gstin") or "").strip()
    if not g_gst or g_gst != p_gst:
        return False
    # L4 links different invoice numbers with similar amounts — too weak for strict pairing
    # (e.g. INV099 vs INV999 at the same taxable totals).
    if result.level == 4:
        return False
    g_inv = str(gstr_rec.get("invoice_number_normalized") or "")
    p_inv = str(pr_rec.get("invoice_number_normalized") or "")
    return invoice_similarity(g_inv, p_inv) >= INVOICE_SIMILARITY_L5_MIN


def run_bidirectional_reconciliation(
    gstr_records: list[dict],
    pr_records: list[dict],
) -> dict:
    total_gstr = len(gstr_records)
    total_pr = len(pr_records)

    if total_gstr == 0:
        return {
            "matched": [],
            "missed_itc": [],
            "wrongful_itc_risk": [],
            "stats": {
                "total_gstr": 0,
                "total_pr": total_pr,
                "matched_count": 0,
                "missed_itc_count": 0,
                "missed_itc_amount_paise": 0,
                "wrongful_risk_count": 0,
                "wrongful_risk_amount_paise": 0,
                "match_rate_pct": 0.0,
                "sanity_passed": True,
            },
        }

    pr_index: dict[str, list[dict]] = defaultdict(list)
    for pr_rec in pr_records:
        gstin = pr_rec.get("supplier_gstin") or ""
        pr_index[str(gstin)].append(pr_rec)

    matched: list[dict] = []
    matched_pr_ids: set[str] = set()
    matched_gstr_ids: set[str] = set()
    missed_itc: list[dict] = []

    for gstr_record in gstr_records:
        gstr_id = str(gstr_record["id"])
        gstin = gstr_record.get("supplier_gstin") or ""
        candidates = pr_index.get(str(gstin), [])

        best_result: MatchResult | None = None
        best_pr: dict | None = None
        best_key: tuple[int, int, int] | None = None

        for pr_rec in candidates:
            pr_id = str(pr_rec["id"])
            if pr_id in matched_pr_ids:
                continue
            result = match_gstr_to_pr(gstr_record, [pr_rec])
            if result is None or not _accept_reconciliation_pair(
                gstr_record, pr_rec, result
            ):
                continue
            key = _tie_key(result, gstr_record, pr_rec)
            if best_key is None or key < best_key:
                best_key = key
                best_result = result
                best_pr = pr_rec

        if best_result is not None and best_pr is not None:
            matched.append(
                {
                    "gstr_id": str(gstr_record["id"]),
                    "pr_id": str(best_pr["id"]),
                    "match_result": best_result,
                }
            )
            matched_pr_ids.add(str(best_pr["id"]))
            matched_gstr_ids.add(gstr_id)
        else:
            ttp = gstr_record.get("total_tax_paise")
            missed_itc.append(
                {
                    "gstr_id": gstr_id,
                    "supplier_gstin": str(gstin),
                    "invoice_number_normalized": str(
                        gstr_record.get("invoice_number_normalized") or ""
                    ),
                    "invoice_date": gstr_record.get("invoice_date"),
                    "total_tax_paise": int(ttp) if ttp is not None else 0,
                }
            )

    wrongful_itc_risk: list[dict] = []
    for pr_rec in pr_records:
        pr_id = str(pr_rec["id"])
        if pr_id in matched_pr_ids:
            continue
        ttp = pr_rec.get("total_tax_paise")
        tap = pr_rec.get("taxable_amount_paise")
        wrongful_itc_risk.append(
            {
                "id": pr_id,
                "supplier_gstin": str(pr_rec.get("supplier_gstin") or ""),
                "invoice_number_normalized": str(
                    pr_rec.get("invoice_number_normalized") or ""
                ),
                "invoice_date": pr_rec.get("invoice_date"),
                "taxable_amount_paise": int(tap) if tap is not None else 0,
                "total_tax_paise": int(ttp) if ttp is not None else 0,
            }
        )

    matched_count = len(matched)
    missed_itc_count = len(missed_itc)
    missed_itc_amount_paise = sum(
        int(m["total_tax_paise"]) for m in missed_itc
    )
    wrongful_risk_count = len(wrongful_itc_risk)
    wrongful_risk_amount_paise = sum(
        int(w["total_tax_paise"]) for w in wrongful_itc_risk
    )

    missed_gstr_ids = {str(m["gstr_id"]) for m in missed_itc}
    sanity_passed = (
        matched_count + missed_itc_count == total_gstr
        and not (matched_gstr_ids & missed_gstr_ids)
        and len(matched_pr_ids) == matched_count
    )

    if total_gstr > 0:
        match_rate_pct = round(matched_count / total_gstr * 100, 2)
    else:
        match_rate_pct = 0.0

    return {
        "matched": matched,
        "missed_itc": missed_itc,
        "wrongful_itc_risk": wrongful_itc_risk,
        "stats": {
            "total_gstr": total_gstr,
            "total_pr": total_pr,
            "matched_count": matched_count,
            "missed_itc_count": missed_itc_count,
            "missed_itc_amount_paise": missed_itc_amount_paise,
            "wrongful_risk_count": wrongful_risk_count,
            "wrongful_risk_amount_paise": wrongful_risk_amount_paise,
            "match_rate_pct": match_rate_pct,
            "sanity_passed": sanity_passed,
        },
    }
