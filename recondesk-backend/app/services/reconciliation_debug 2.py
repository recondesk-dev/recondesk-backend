"""Invoice-level debug report for a reconciliation run.

Turns the output of :func:`run_bidirectional_reconciliation` into a structured,
auditable report: every matched pair, discrepancy pair, GSTIN-mismatch review
pair, missed-ITC row and ITC-at-risk row, with both-side GSTIN / invoice /
normalized invoice / taxable / ITC, the resolved match level + discrepancy
reason, and whether each GSTR and PR record was consumed exactly once.

This module is read-only: it never mutates engine output and has no DB access,
so it is safe to call from scripts, tests or the worker for diagnostics.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.services.matcher import match_gstr_to_pr, normalize_invoice


def _index_by_id(rows: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(r.get("id")): r for r in rows}


def _rupees(paise: Any) -> float:
    return round(int(paise or 0) / 100.0, 2)


def _side(rec: Mapping[str, Any] | None) -> dict[str, Any]:
    if not rec:
        return {}
    inv = rec.get("invoice_number") or rec.get("invoice_number_normalized")
    return {
        "gstin": str(rec.get("supplier_gstin") or ""),
        "invoice": str(inv or ""),
        "invoice_normalized": str(
            rec.get("invoice_number_normalized") or normalize_invoice(inv)
        ),
        "taxable": _rupees(rec.get("taxable_amount_paise")),
        "itc": _rupees(rec.get("total_tax_paise")),
        "date": str(rec.get("invoice_date") or ""),
    }


def build_debug_report(
    result: Mapping[str, Any],
    gstr_rows: list[Mapping[str, Any]],
    pr_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    g_by_id = _index_by_id(gstr_rows)
    p_by_id = _index_by_id(pr_rows)

    consumed_gstr: set[str] = set()
    consumed_pr: set[str] = set()

    matched_pairs: list[dict[str, Any]] = []
    discrepancy_pairs: list[dict[str, Any]] = []
    gstin_mismatch_pairs: list[dict[str, Any]] = []

    for m in result.get("matched") or []:
        gid = str(m.get("gstr_id", ""))
        pid = str(m.get("pr_id", ""))
        consumed_gstr.add(gid)
        consumed_pr.add(pid)
        g = g_by_id.get(gid)
        p = p_by_id.get(pid)
        mr = match_gstr_to_pr(dict(g), [dict(p)]) if g and p else None
        level = mr.level if mr else None
        reason = (mr.review_reason if mr else None) or ""
        entry = {
            "gstr": _side(g),
            "pr": _side(p),
            "match_level": level,
            "match_status_text": m.get("match_status_text"),
            "discrepancy_reason": reason,
            "discrepancies": list(mr.discrepancies) if mr else [],
            "confidence": m.get("confidence_score"),
            "consumed": True,
        }
        if level is not None and level >= 3:
            discrepancy_pairs.append(entry)
        else:
            matched_pairs.append(entry)

    for gm in result.get("gstin_mismatch") or []:
        gid = str(gm.get("gstr_id", ""))
        pid = str(gm.get("pr_id", ""))
        consumed_gstr.add(gid)
        consumed_pr.add(pid)
        gstin_mismatch_pairs.append(
            {
                "gstr": _side(g_by_id.get(gid)),
                "pr": _side(p_by_id.get(pid)),
                "match_level": "GSTIN_MISMATCH",
                "discrepancy_reason": gm.get("reason") or "GSTIN_MISMATCH",
                "consumed": True,
            }
        )

    missed: list[dict[str, Any]] = []
    for mi in result.get("missed_itc") or []:
        gid = str(mi.get("gstr_id", ""))
        consumed_gstr.add(gid)
        missed.append(
            {
                "gstr": _side(g_by_id.get(gid)),
                "itc": _rupees(mi.get("total_tax_paise")),
                "consumed": True,
            }
        )

    review_required: list[dict[str, Any]] = []
    for rr in result.get("review_required") or []:
        side = rr.get("side")
        rid = str(rr.get("gstr_id") or rr.get("id", ""))
        if side == "GSTR":
            consumed_gstr.add(rid)
            rec = g_by_id.get(rid)
        else:
            consumed_pr.add(rid)
            rec = p_by_id.get(rid)
        review_required.append(
            {
                "record": _side(rec),
                "side": side,
                "reason": rr.get("reason"),
                "itc": _rupees(rr.get("total_tax_paise")),
                "consumed": True,
            }
        )

    at_risk: list[dict[str, Any]] = []
    for wr in result.get("wrongful_itc_risk") or []:
        pid = str(wr.get("id", ""))
        consumed_pr.add(pid)
        at_risk.append(
            {
                "pr": _side(p_by_id.get(pid)),
                "itc": _rupees(wr.get("total_tax_paise")),
                "risk_reason": wr.get("risk_reason") or "PR_ONLY",
                "consumed": True,
            }
        )

    # Double-consumption guard: a GSTR or PR id must not appear in two buckets.
    gstr_seen: dict[str, int] = {}
    pr_seen: dict[str, int] = {}
    for m in result.get("matched") or []:
        gstr_seen[str(m.get("gstr_id"))] = gstr_seen.get(str(m.get("gstr_id")), 0) + 1
        pr_seen[str(m.get("pr_id"))] = pr_seen.get(str(m.get("pr_id")), 0) + 1
    for gm in result.get("gstin_mismatch") or []:
        gstr_seen[str(gm.get("gstr_id"))] = gstr_seen.get(str(gm.get("gstr_id")), 0) + 1
        pr_seen[str(gm.get("pr_id"))] = pr_seen.get(str(gm.get("pr_id")), 0) + 1
    for mi in result.get("missed_itc") or []:
        gstr_seen[str(mi.get("gstr_id"))] = gstr_seen.get(str(mi.get("gstr_id")), 0) + 1
    for wr in result.get("wrongful_itc_risk") or []:
        pr_seen[str(wr.get("id"))] = pr_seen.get(str(wr.get("id")), 0) + 1
    for rr in result.get("review_required") or []:
        side = rr.get("side")
        rid = str(rr.get("gstr_id") or rr.get("id", ""))
        if side == "GSTR":
            gstr_seen[rid] = gstr_seen.get(rid, 0) + 1
        else:
            pr_seen[rid] = pr_seen.get(rid, 0) + 1

    double_counted_gstr = sorted(k for k, v in gstr_seen.items() if v > 1)
    double_counted_pr = sorted(k for k, v in pr_seen.items() if v > 1)

    stats = dict(result.get("stats") or {})
    summary = {
        "total_gstr": len(gstr_rows),
        "total_pr": len(pr_rows),
        "matched": len(matched_pairs),
        "discrepancy": len(discrepancy_pairs),
        "gstin_mismatch": len(gstin_mismatch_pairs),
        "missed_itc": len(missed),
        "itc_at_risk": len(at_risk),
        "review_required": len(review_required),
        "missed_itc_rupees": round(sum(m["itc"] for m in missed), 2),
        "itc_at_risk_rupees": round(sum(r["itc"] for r in at_risk), 2),
        "double_counted_gstr_ids": double_counted_gstr,
        "double_counted_pr_ids": double_counted_pr,
        "no_double_counting": not double_counted_gstr and not double_counted_pr,
    }

    return {
        "summary": summary,
        "engine_stats": stats,
        "matched_pairs": matched_pairs,
        "discrepancy_pairs": discrepancy_pairs,
        "gstin_mismatch_pairs": gstin_mismatch_pairs,
        "missed_itc": missed,
        "itc_at_risk": at_risk,
        "review_required": review_required,
    }


def print_debug_report(report: Mapping[str, Any]) -> None:
    s = report["summary"]
    print("=" * 78)
    print("RECONCILIATION DEBUG REPORT")
    print("=" * 78)
    print(
        f"GSTR rows: {s['total_gstr']}   PR rows: {s['total_pr']}   "
        f"no_double_counting={s['no_double_counting']}"
    )
    print(
        f"  matched(clean)={s['matched']}  discrepancy={s['discrepancy']}  "
        f"gstin_mismatch={s['gstin_mismatch']}  "
        f"review_required={s['review_required']}  "
        f"missed_itc={s['missed_itc']} (Rs {s['missed_itc_rupees']:,})  "
        f"itc_at_risk={s['itc_at_risk']} (Rs {s['itc_at_risk_rupees']:,})"
    )
    st = report["engine_stats"]
    print("\nBENCHMARK STATS:")
    print(f" - clean_matched_count: {st.get('clean_matched_count')}")
    print(f" - review_required_count: {st.get('review_required_count')}")
    print(f" - duplicate_conflict_count: {st.get('duplicate_conflict_count')}")
    print(f" - genuine_gstr_only_count: {st.get('genuine_gstr_only_count')}")
    print(f" - genuine_pr_only_count: {st.get('genuine_pr_only_count')}")
    print(f" - missed_itc_total: Rs {st.get('missed_itc_total', 0)/100:,.2f}")
    print(f" - itc_at_risk_total: Rs {st.get('itc_at_risk_total', 0)/100:,.2f}")

    if s["double_counted_gstr_ids"] or s["double_counted_pr_ids"]:
        print(
            f"  !! DOUBLE COUNTED gstr={s['double_counted_gstr_ids']} "
            f"pr={s['double_counted_pr_ids']}"
        )

    def _line(tag: str, e: Mapping[str, Any]) -> str:
        g = e.get("gstr") or {}
        p = e.get("pr") or {}
        return (
            f"  [{tag}] L{e.get('match_level')} "
            f"GSTR[{g.get('gstin','-')} {g.get('invoice','-')}"
            f"->{g.get('invoice_normalized','-')} itc={g.get('itc','-')}] "
            f"PR[{p.get('gstin','-')} {p.get('invoice','-')}"
            f"->{p.get('invoice_normalized','-')} itc={p.get('itc','-')}] "
            f"{e.get('discrepancy_reason','')}"
        )

    print("\n-- MATCHED (clean) --")
    for e in report["matched_pairs"]:
        print(_line("MATCH", e))
    print("\n-- DISCREPANCY (linked, review) --")
    for e in report["discrepancy_pairs"]:
        print(_line("DISC", e))
    print("\n-- GSTIN MISMATCH (review) --")
    for e in report["gstin_mismatch_pairs"]:
        print(_line("GSTIN", e))
    print("\n-- MISSED ITC (GSTR only) --")
    for e in report["missed_itc"]:
        g = e["gstr"]
        print(f"  [MISSED] {g.get('gstin','-')} {g.get('invoice','-')} itc={e['itc']}")
    print("\n-- ITC AT RISK (PR only) --")
    for e in report["itc_at_risk"]:
        p = e["pr"]
        print(
            f"  [RISK] {p.get('gstin','-')} {p.get('invoice','-')} "
            f"itc={e['itc']} reason={e.get('risk_reason')}"
        )
    print("\n-- REVIEW REQUIRED / DUPLICATE CONFLICT --")
    for e in report["review_required"]:
        r = e["record"]
        print(f"  [REVIEW] {e['side']} {r.get('gstin','-')} {r.get('invoice','-')} itc={e['itc']} reason={e['reason']}")
    print("=" * 78)
