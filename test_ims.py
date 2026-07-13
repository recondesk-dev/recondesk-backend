#!/usr/bin/env python3
"""Quick IMS invoice-count smoke test against Sandbox using a live client_gstins token."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_ROOT = REPO_ROOT / "recondesk-backend"

sys.path.insert(0, str(BACKEND_ROOT))
os.chdir(BACKEND_ROOT)

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

from app.database import get_supabase
from app.services.sandbox_gst_client import make_sandbox_client

CLIENT_GSTIN_ID = "bf298560-cf88-4fd5-9900-1542139ded56"


def main() -> None:
    sb = get_supabase()
    res = (
        sb.table("client_gstins")
        .select("gstin, gstn_access_token")
        .eq("id", CLIENT_GSTIN_ID)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise SystemExit(f"client_gstins row not found for id={CLIENT_GSTIN_ID}")

    row = res.data[0]
    gstin = (row.get("gstin") or "").strip()
    access_token = row.get("gstn_access_token")
    if not gstin:
        raise SystemExit("client_gstins row has no gstin")
    if not access_token:
        raise SystemExit("client_gstins row has no gstn_access_token")

    os.environ["SANDBOX_ACCESS_TOKEN"] = str(access_token)

    client = make_sandbox_client()
    result = client.get_invoice_count(gstin=gstin, year=2026, month=6)

    print(f"gstin={gstin}")
    print(f"total={result.total()}")
    print(f"total_by_status={result.total_by_status()}")
    print("counts=")
    print(json.dumps(result.counts, indent=2))
    print("raw_payload=")
    print(json.dumps(result.raw_payload, indent=2))


if __name__ == "__main__":
    main()
