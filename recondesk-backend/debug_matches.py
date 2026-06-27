import os
import sys
import asyncio
from app.database import get_supabase
from app.services.reconciliation_outcomes import load_payload
from app.worker.reconciliation_task import _load_pr_matcher_and_raw
from app.services.matcher import _match_gstr_to_pr_pair

def _load_gstr_matcher(client, run_id):
    out = []
    offset = 0
    while True:
        res = client.table("gstr_records").select("id, record_data").eq("run_id", run_id).order("id").range(offset, offset + 999).execute()
        rows = res.data or []
        if not rows: break
        for row in rows:
            rd = row.get("record_data") or {}
            from app.services.reconciliation_record_adapter import gstr_db_row_to_matcher_row
            out.append(gstr_db_row_to_matcher_row(row))
        offset += len(rows)
        if len(rows) < 1000: break
    return out

async def main():
    sb = get_supabase()
    res = sb.table("reconciliation_run").select("*").order("created_at", desc=True).limit(1).execute()
    run = res.data[0]
    rid = run["id"]
    
    pr_current, _ = _load_pr_matcher_and_raw(sb, rid)
    gstr_matcher = _load_gstr_matcher(sb, rid)
    
    payload = load_payload(sb, rid)
    engine = payload.get("engine", {})
    
    matched = engine.get("matched", [])
    duplicates = engine.get("duplicates", [])
    
    consumed_gstr_ids = {m["gstr_id"] for m in matched} | {m["gstr_id"] for m in duplicates}
    consumed_pr_ids = {m["pr_id"] for m in matched} | {m["pr_id"] for m in duplicates}
    
    unconsumed_gstr = [g for g in gstr_matcher if str(g["id"]) not in consumed_gstr_ids]
    unconsumed_pr = [p for p in pr_current if str(p["id"]) not in consumed_pr_ids]
    
    found_l3 = 0
    found_l4 = 0
    found_l5 = 0
    for g in unconsumed_gstr:
        best_level = 6
        for p in unconsumed_pr:
            res = _match_gstr_to_pr_pair(g, p)
            if res.level < best_level:
                best_level = res.level
        if best_level == 3:
            found_l3 += 1
        elif best_level == 4:
            found_l4 += 1
        elif best_level == 5:
            found_l5 += 1
            
    print(f"Old logic on orphans would find L3 matches: {found_l3}")
    print(f"Old logic on orphans would find L4 matches: {found_l4}")
    print(f"Old logic on orphans would find L5 matches: {found_l5}")

asyncio.run(main())
