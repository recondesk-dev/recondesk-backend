"""End-to-end validation of GSTR-2B amendment handling using real parser output and full pipeline."""

import json
from datetime import date
from unittest.mock import MagicMock, patch
import pytest

from app.parsers.gstr2b_parser import parse_gstr2b
from app.services.reconciliation_record_adapter import (
    gstr_db_row_to_matcher_row,
    pr_db_row_to_matcher_row,
)
from app.services.amendment_handler import build_effective_gstr_records
from app.matching.engine import run_bidirectional_reconciliation
from app.worker.reconciliation_task import execute_reconciliation

BUYER_GSTIN = "27AAAAA1234A1ZP"
SUPPLIER = "27ABCDE1234F1Z5"
CLIENT_UUID = "00000000-0000-0000-0000-000000000001"


def _make_gstn_payload(*, b2b=None, b2ba=None, cdnr=None, cdnra=None, rtnprd="042024"):
    data = {"gstin": BUYER_GSTIN, "rtnprd": rtnprd}
    if b2b is not None:
        data["b2b"] = b2b
    if b2ba is not None:
        data["b2ba"] = b2ba
    if cdnr is not None:
        data["cdnr"] = cdnr
    if cdnra is not None:
        data["cdnra"] = cdnra
    return json.dumps({"data": data}).encode("utf-8")


def _supplier(ctin: str, invoices: list) -> dict:
    return {"ctin": ctin, "inv": invoices}


def _item(txval, rt=18, igst=0, cgst=None, sgst=None, cess=0):
    if cgst is None:
        cgst = round(txval * rt / 200)
    if sgst is None:
        sgst = round(txval * rt / 200)
    return {
        "num": 1,
        "itm_det": {
            "txval": txval,
            "rt": rt,
            "igst": igst,
            "cgst": cgst,
            "sgst": sgst,
            "cess": cess,
        },
    }


def _invoice(inum, dt, val, itms, pos="27", rev="N", itcavl="Y", **extra):
    inv = {
        "inum": inum,
        "dt": dt,
        "val": val,
        "pos": pos,
        "rev": rev,
        "itcavl": itcavl,
        "itms": itms,
    }
    inv.update(extra)
    return inv


def test_parser_field_population_for_real_amendment():
    """Verify that parse_gstr2b populates all required amendment fields."""
    inv = _invoice(
        inum="INV-102-REV",
        dt="15-04-2024",
        val=141600,
        itms=[_item(txval=120000, cgst=10800, sgst=10800)],
        oinum="INV-102",
        oidt="01-04-2024",
        supprd="042024",
    )
    payload_bytes = _make_gstn_payload(b2ba=[_supplier(SUPPLIER, [inv])])
    parsed = parse_gstr2b(payload_bytes)

    assert parsed["total_parsed"] == 1
    rec = parsed["records"][0]

    # Verify real parsed amendment fields
    assert rec["is_amendment"] is True
    assert rec["original_invoice_number_raw"] == "INV-102"
    assert rec["original_invoice_number"] == "INV102"
    assert rec["original_invoice_date_raw"] == "01-04-2024"
    assert rec["original_invoice_date_norm"] == "2024-04-01"
    assert rec["supprd"] == "042024"
    assert rec["supplier_gstin"] == SUPPLIER
    assert rec["invoice_number"] == "INV102REV"
    assert rec["invoice_date_norm"] == "2024-04-15"
    assert rec["doc_type"] == "INVOICE"
    assert rec["section"] == "b2ba"

    # Verify adapter consumption
    db_row = {"id": "gstr-uuid-1", "record_data": rec}
    matcher_row = gstr_db_row_to_matcher_row(db_row)

    assert matcher_row["is_amendment"] is True
    assert matcher_row["original_invoice_number"] == "INV102"
    assert matcher_row["original_invoice_number_raw"] == "INV-102"
    assert matcher_row["original_invoice_date"] == "2024-04-01"
    assert matcher_row["supprd"] == "042024"
    assert matcher_row["supplier_gstin"] == SUPPLIER
    assert matcher_row["invoice_number"] == "INV-102-REV"
    assert matcher_row["taxable_amount_paise"] == 12000000  # Rs 120000 -> paise
    assert matcher_row["total_tax_paise"] == 2160000       # Rs 21600 -> paise


def _run_pipeline_for_scenario(scenario_name, gstr_payload_bytes, pr_invoices):
    """Executes the full pipeline via execute_reconciliation and returns metrics and saved payload."""
    parsed = parse_gstr2b(gstr_payload_bytes)
    gstr_records = parsed.get("records") or []

    run_uuid = f"00000000-0000-0000-0000-00000000{abs(hash(scenario_name)) % 10000:04d}"
    gstr_db_rows = [
        {
            "id": f"00000000-0000-0000-0001-00000000{abs(hash(f'{scenario_name}-{idx}')) % 10000:04d}",
            "run_id": run_uuid,
            "client_gstin_id": CLIENT_UUID,
            "period": "2024-04",
            "record_data": rec,
        }
        for idx, rec in enumerate(gstr_records)
    ]

    pr_db_rows = [
        {
            "id": f"00000000-0000-0000-0002-00000000{abs(hash(f'{scenario_name}-{idx}')) % 10000:04d}",
            "run_id": run_uuid,
            "client_gstin_id": CLIENT_UUID,
            "period": "2024-04",
            "record_data": {
                "supplier_gstin": SUPPLIER,
                "invoice_number": pr["inum"],
                "invoice_date": pr.get("dt", "2024-04-15"),
                "taxable_amount_paise": pr["taxable_paise"],
                "total_tax_paise": pr["tax_paise"],
                "cgst_paise": pr["tax_paise"] // 2,
                "sgst_paise": pr["tax_paise"] // 2,
                "payment_status": "PAID",
            },
        }
        for idx, pr in enumerate(pr_invoices)
    ]

    # Convert to matcher rows
    matcher_gstr = [gstr_db_row_to_matcher_row(r) for r in gstr_db_rows]
    raw_gstr_by_id = {r["id"]: r["record_data"] for r in gstr_db_rows}

    matcher_pr = [pr_db_row_to_matcher_row(r) for r in pr_db_rows]
    pr_index_current = {SUPPLIER: matcher_pr}

    mock_client = MagicMock()
    run_record = {
        "id": run_uuid,
        "client_gstin_id": CLIENT_UUID,
        "period": "2024-04",
        "gstr_records_imported": len(gstr_db_rows),
        "pr_records_imported": len(pr_db_rows),
        "status": "MATCHING",
        "user_id": CLIENT_UUID,
    }
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [run_record]
    mock_client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value.data = [run_record]
    mock_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [run_record]

    saved_payloads = []

    def mock_save(c, rid, payload, created_at=None):
        saved_payloads.append(payload)

    # Store a deep copy of gstr_db_rows to check immutability
    original_db_snapshot = json.dumps([r["record_data"] for r in gstr_db_rows], sort_keys=True)

    raw_pr_by_id = {r["id"]: r["record_data"] for r in pr_db_rows}

    with patch("app.worker.reconciliation_task._supabase", return_value=mock_client), \
         patch("app.worker.reconciliation_task._update_run"), \
         patch("app.worker.reconciliation_task._load_gstr_matcher_and_raw", return_value=(matcher_gstr, raw_gstr_by_id)), \
         patch("app.worker.reconciliation_task._load_pr_matcher_and_raw", return_value=(matcher_pr, raw_pr_by_id)), \
         patch("app.worker.reconciliation_task._build_pr_index_for_matching", return_value=(pr_index_current, len(matcher_pr), 0, [])), \
         patch("app.worker.reconciliation_task._load_pr_for_historical_periods_paged", return_value={}), \
         patch("app.worker.reconciliation_task.save_reconciliation_results", side_effect=mock_save), \
         patch("app.worker.reconciliation_task.update_invoice_tracking"), \
         patch("app.worker.reconciliation_task.notify_reconciliation_run_completed_email_maybe"):

        execute_reconciliation(run_uuid)

    # Verify immutability of raw database rows
    after_db_snapshot = json.dumps([r["record_data"] for r in gstr_db_rows], sort_keys=True)
    assert original_db_snapshot == after_db_snapshot, f"Raw DB records mutated in {scenario_name}!"

    assert len(saved_payloads) == 1, f"Failed to save results payload for {scenario_name}"
    payload = saved_payloads[0]
    engine_data = payload.get("engine") or {}

    return {
        "raw_count": len(gstr_db_rows),
        "amendment_count": payload.get("amendment_summary", {}).get("amendment_count", 0),
        "chains_count": payload.get("amendment_summary", {}).get("chains_count", 0),
        "superseded_count": payload.get("amendment_summary", {}).get("superseded_count", 0),
        "effective_count": payload.get("amendment_summary", {}).get("effective_count", 0),
        "matched_count": len(engine_data.get("matched") or []),
        "missed_itc_count": len(engine_data.get("missed_itc") or []),
        "review_count": len(engine_data.get("duplicates") or []),
        "duplicate_entries": len(engine_data.get("duplicate_entries") or []),
        "amendment_summary": payload.get("amendment_summary"),
        "payload": payload,
    }


def test_scenario_1_original_only():
    """Scenario 1: Original invoice only."""
    inv = _invoice("INV-001", "01-04-2024", 118000, [_item(100000, cgst=9000, sgst=9000)])
    payload = _make_gstn_payload(b2b=[_supplier(SUPPLIER, [inv])])
    pr = [{"inum": "INV-001", "dt": "2024-04-01", "taxable_paise": 10000000, "tax_paise": 1800000}]

    res = _run_pipeline_for_scenario("sc1", payload, pr)
    assert res["raw_count"] == 1
    assert res["amendment_count"] == 0
    assert res["chains_count"] == 0
    assert res["superseded_count"] == 0
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0


def test_scenario_2_original_plus_one_amendment():
    """Scenario 2: Original + one amendment."""
    inv_orig = _invoice("INV-002", "01-04-2024", 118000, [_item(100000, cgst=9000, sgst=9000)])
    inv_amend = _invoice(
        "INV-002", "15-04-2024", 141600, [_item(120000, cgst=10800, sgst=10800)],
        oinum="INV-002", oidt="01-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_amend])],
    )
    # PR records the updated amount and date
    pr = [{"inum": "INV-002", "dt": "2024-04-15", "taxable_paise": 12000000, "tax_paise": 2160000}]

    res = _run_pipeline_for_scenario("sc2", payload, pr)
    assert res["raw_count"] == 2
    assert res["amendment_count"] == 1
    assert res["chains_count"] == 1
    assert res["superseded_count"] == 1
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0


def test_scenario_3_original_plus_a1_plus_a2():
    """Scenario 3: Original + A1 + A2 multi-hop chain."""
    inv_orig = _invoice("INV-003", "01-04-2024", 118000, [_item(100000, cgst=9000, sgst=9000)])
    inv_a1 = _invoice(
        "INV-003-V1", "10-04-2024", 129800, [_item(110000, cgst=9900, sgst=9900)],
        oinum="INV-003", oidt="01-04-2024", supprd="042024"
    )
    inv_a2 = _invoice(
        "INV-003-V2", "20-04-2024", 147500, [_item(125000, cgst=11250, sgst=11250)],
        oinum="INV-003-V1", oidt="10-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_a1, inv_a2])],
    )
    pr = [{"inum": "INV-003-V2", "dt": "2024-04-20", "taxable_paise": 12500000, "tax_paise": 2250000}]

    res = _run_pipeline_for_scenario("sc3", payload, pr)
    assert res["raw_count"] == 3
    assert res["amendment_count"] == 2
    assert res["chains_count"] == 1
    assert res["superseded_count"] == 2
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0


def test_scenario_4_renumbered_amendment():
    """Scenario 4: Renumbered amendment."""
    inv_orig = _invoice("INV-004", "01-04-2024", 59000, [_item(50000, cgst=4500, sgst=4500)])
    inv_amend = _invoice(
        "INV-004-AMENDED", "12-04-2024", 59000, [_item(50000, cgst=4500, sgst=4500)],
        oinum="INV-004", oidt="01-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_amend])],
    )
    pr = [{"inum": "INV-004-AMENDED", "dt": "2024-04-12", "taxable_paise": 5000000, "tax_paise": 900000}]

    res = _run_pipeline_for_scenario("sc4", payload, pr)
    assert res["raw_count"] == 2
    assert res["amendment_count"] == 1
    assert res["chains_count"] == 1
    assert res["superseded_count"] == 1
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0


def test_scenario_5_amendment_prior_period():
    """Scenario 5: Amendment whose original is from a prior return period."""
    # Only the amendment is in the current 042024 GSTR-2B file
    inv_amend = _invoice(
        "INV-005", "15-04-2024", 94400, [_item(80000, cgst=7200, sgst=7200)],
        oinum="INV-005", oidt="10-01-2024", supprd="012024"
    )
    payload = _make_gstn_payload(b2ba=[_supplier(SUPPLIER, [inv_amend])])
    pr = [{"inum": "INV-005", "dt": "2024-04-15", "taxable_paise": 8000000, "tax_paise": 1440000}]

    res = _run_pipeline_for_scenario("sc5", payload, pr)
    assert res["raw_count"] == 1
    assert res["amendment_count"] == 1
    assert res["chains_count"] == 1
    assert res["superseded_count"] == 0
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0
    chain = res["amendment_summary"]["chains"][0]
    assert chain["has_local_original"] is False
    assert chain["classification"] == "AMENDMENT_WITHOUT_ORIGINAL"


def test_scenario_6_duplicate_amendment_input():
    """Scenario 6: Duplicate amendment input."""
    inv_orig = _invoice("INV-006", "01-04-2024", 70800, [_item(60000, cgst=5400, sgst=5400)])
    inv_amend = _invoice(
        "INV-006", "15-04-2024", 82600, [_item(70000, cgst=6300, sgst=6300)],
        oinum="INV-006", oidt="01-04-2024", supprd="042024"
    )
    # Duplicate identical amendment
    inv_amend_dup = _invoice(
        "INV-006", "15-04-2024", 82600, [_item(70000, cgst=6300, sgst=6300)],
        oinum="INV-006", oidt="01-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_amend, inv_amend_dup])],
    )
    pr = [{"inum": "INV-006", "dt": "2024-04-15", "taxable_paise": 7000000, "tax_paise": 1260000}]

    res = _run_pipeline_for_scenario("sc6", payload, pr)
    assert res["raw_count"] == 3
    assert res["amendment_count"] == 2
    assert res["chains_count"] == 1
    assert res["superseded_count"] == 2  # 1 original + 1 duplicate amendment
    assert res["effective_count"] == 1
    assert res["matched_count"] == 1
    assert res["missed_itc_count"] == 0
    assert res["review_count"] == 0


def test_superseded_records_strictly_excluded_from_all_matching_phases():
    """Verify that superseded records never enter candidate indexing, Phase 1, Phase 2/3, or final counts."""
    inv_orig = _invoice("INV-007", "01-04-2024", 118000, [_item(100000, cgst=9000, sgst=9000)])
    inv_amend = _invoice(
        "INV-007", "15-04-2024", 141600, [_item(120000, cgst=10800, sgst=10800)],
        oinum="INV-007", oidt="01-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_amend])],
    )

    superseded_id = f"00000000-0000-0000-0001-00000000{abs(hash('sc_exclusion-0')) % 10000:04d}"
    effective_id = f"00000000-0000-0000-0001-00000000{abs(hash('sc_exclusion-1')) % 10000:04d}"

    # Spy on process_gstr_records_chunk and execute_phase2_and_3 during execute_reconciliation
    phase1_seen_ids = []
    phase23_seen_ids = []

    from app.services import reconciliation as recon_mod
    orig_chunk = recon_mod.process_gstr_records_chunk
    orig_phase23 = recon_mod.execute_phase2_and_3

    def spy_chunk(chunk, *args, **kwargs):
        for r in chunk:
            phase1_seen_ids.append(r.get("id"))
        return orig_chunk(chunk, *args, **kwargs)

    def spy_phase23(gstr_records, *args, **kwargs):
        for r in gstr_records:
            phase23_seen_ids.append(r.get("id"))
        return orig_phase23(gstr_records, *args, **kwargs)

    pr = [{"inum": "INV-007", "dt": "2024-04-15", "taxable_paise": 12000000, "tax_paise": 2160000}]
    with patch("app.worker.reconciliation_task.process_gstr_records_chunk", side_effect=spy_chunk), \
         patch("app.worker.reconciliation_task.execute_phase2_and_3", side_effect=spy_phase23):
        out = _run_pipeline_for_scenario("sc_exclusion", payload, pr)

    # 1. Phase 1 exclusion check
    assert superseded_id not in phase1_seen_ids, "Superseded ID leaked into Phase 1 chunk processing!"
    assert effective_id in phase1_seen_ids, "Effective ID missing from Phase 1 chunk processing!"

    # 2. Phase 2/3 exclusion check (if any fall through)
    assert superseded_id not in phase23_seen_ids, "Superseded ID leaked into Phase 2/3!"

    # 3. Final counts check
    assert out["superseded_count"] == 1
    assert out["effective_count"] == 1
    assert out["matched_count"] + out["missed_itc_count"] + out["review_count"] == 1


def test_cross_period_prevents_duplicate_itc_event():
    """Verify cross-period reconciliation never creates a duplicate ITC event."""
    # Case A: Combined multi-period import containing Jan original AND Apr amendment
    inv_jan = _invoice("INV-2024-001", "15-01-2024", 118000, [_item(100000, cgst=9000, sgst=9000)])
    inv_apr = _invoice(
        "INV-2024-001", "20-04-2024", 141600, [_item(120000, cgst=10800, sgst=10800)],
        oinum="INV-2024-001", oidt="15-01-2024", supprd="012024"
    )
    payload_combined = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_jan])],
        b2ba=[_supplier(SUPPLIER, [inv_apr])],
    )
    # PR has the amended value
    pr_amended = [{"inum": "INV-2024-001", "dt": "2024-04-20", "taxable_paise": 12000000, "tax_paise": 2160000}]

    out = _run_pipeline_for_scenario("sc_cross_period_combined", payload_combined, pr_amended)
    # The two periods are consolidated into 1 effective event
    assert out["raw_count"] == 2
    assert out["effective_count"] == 1
    assert out["superseded_count"] == 1
    assert out["matched_count"] == 1
    assert out["missed_itc_count"] == 0
    # ITC claimed only once for the effective value
    matched_row = out["payload"]["engine"]["matched"][0]
    assert matched_row["gstr_id"] is not None

    # Case B: Standalone April period where original Jan is in earlier month DB
    payload_apr_only = _make_gstn_payload(b2ba=[_supplier(SUPPLIER, [inv_apr])])
    out_apr = _run_pipeline_for_scenario("sc_cross_period_apr_only", payload_apr_only, pr_amended)
    # Exactly 1 record is imported and matched; no ghost original is fabricated
    assert out_apr["raw_count"] == 1
    assert out_apr["effective_count"] == 1
    assert out_apr["matched_count"] == 1


def test_lineage_invoices_downstream_matcher_alias_limitation():
    """Verify that downstream matcher matches PR holding old invoice number to amended GSTR invoice via oinum."""
    inv_orig = _invoice("INV-008", "01-04-2024", 59000, [_item(50000, cgst=4500, sgst=4500)])
    inv_amend = _invoice(
        "INV-008-NEW", "12-04-2024", 59000, [_item(50000, cgst=4500, sgst=4500)],
        oinum="INV-008", oidt="01-04-2024", supprd="042024"
    )
    payload = _make_gstn_payload(
        b2b=[_supplier(SUPPLIER, [inv_orig])],
        b2ba=[_supplier(SUPPLIER, [inv_amend])],
    )
    # PR holds the OLD invoice number "INV-008", but GSTR effective has "INV-008-NEW"
    pr_with_old_number = [{"inum": "INV-008", "dt": "2024-04-12", "taxable_paise": 5000000, "tax_paise": 900000}]

    out = _run_pipeline_for_scenario("sc_lineage_limit", payload, pr_with_old_number)

    # In amendment summary, lineage_invoices contains both numbers
    chain = out["amendment_summary"]["chains"][0]
    assert chain["effective_invoice"] == "INV-008-NEW"
    assert chain["original_invoice"] in ("INV8", "INV-008")

    # Downstream PR matcher links the amendment to the PR invoice via original_invoice_number
    assert out["matched_count"] == 1
    assert out["missed_itc_count"] == 0

