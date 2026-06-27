import os
import sys
import asyncio
from app.database import get_supabase
from app.services.reconciliation_outcomes import load_payload

async def main():
    sb = get_supabase()
    res = sb.table("reconciliation_run").select("*").order("created_at", desc=True).limit(1).execute()
    run = res.data[0]
    rid = run["id"]
    print(f"Run ID: {rid}")
    
    payload = load_payload(sb, rid)
    engine = payload.get("engine", {})
    
    matched = engine.get("matched", [])
    duplicates = engine.get("duplicates", [])
    missed = engine.get("missed_itc", [])
    wrongful = engine.get("wrongful_itc_risk", [])
    
    print(f"Matched count: {len(matched)}")
    print(f"Review Required count: {len(duplicates)}")
    print(f"Missed ITC count: {len(missed)}")
    print(f"Wrongful ITC count: {len(wrongful)}")
    
    missed_val = sum(int(x.get("total_tax_paise") or 0) for x in missed)
    wrong_val = sum(int(x.get("total_tax_paise") or 0) for x in wrongful)
    
    print(f"Missed ITC paise: {missed_val}")
    print(f"Wrongful ITC paise: {wrong_val}")

asyncio.run(main())
