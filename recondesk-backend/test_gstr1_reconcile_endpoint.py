#!/usr/bin/env python3
"""Standalone end-to-end probe for POST /api/gstr1-reconcile/.

Uploads Sales Register + GSTR-1 + GSTR-3B sample files as multipart
form-data and prints a readable summary of mismatches and the
GSTR-1 vs 3B tie-out section.

Usage (server must already be running on localhost:8000)::

    # With an existing JWT:
    RECONDESK_TOKEN='<jwt>' python test_gstr1_reconcile_endpoint.py

    # Or login with email/password:
    RECONDESK_EMAIL='you@example.com' RECONDESK_PASSWORD='...' \\
        python test_gstr1_reconcile_endpoint.py

    # Or mint a local HS256 token from app settings (dev only):
    python test_gstr1_reconcile_endpoint.py --mint-local-token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

# ── Defaults ──────────────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "http://localhost:8000"
ENDPOINT_PATH = "/api/gstr1-reconcile"

SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = SCRIPT_DIR / "tests" / "sample_gstr1_3b_test"

# Candidate locations for each input file (first hit wins).
SR_CANDIDATES = [
    SAMPLE_DIR / "Sales_Register_Sample_Corrected.xlsx",
    Path.home() / "Downloads" / "Sales_Register_Sample_Corrected.xlsx",
    SCRIPT_DIR / "Sales_Register_Sample_Corrected.xlsx",
]
GSTR1_CANDIDATES = [
    SAMPLE_DIR / "sample_gstr1.json",
    SCRIPT_DIR / "sample_gstr1.json",
    Path.home() / "Downloads" / "sample_gstr1.json",
]
GSTR3B_CANDIDATES = [
    SAMPLE_DIR / "sample_gstr3b.json",
    SCRIPT_DIR / "sample_gstr3b.json",
    Path.home() / "Downloads" / "sample_gstr3b.json",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(candidates: list[Path], label: str) -> Path:
    for path in candidates:
        if path.is_file():
            return path
    searched = "\n  ".join(str(p) for p in candidates)
    print(f"ERROR: Could not find {label}. Searched:\n  {searched}", file=sys.stderr)
    sys.exit(1)


def _mint_local_token() -> str:
    """Mint a short-lived HS256 JWT using the backend's local signing key."""
    try:
        # Ensure backend package is importable when run from repo root / backend dir.
        if str(SCRIPT_DIR) not in sys.path:
            sys.path.insert(0, str(SCRIPT_DIR))
        from app.auth import create_access_token
    except Exception as exc:  # noqa: BLE001
        print(
            f"ERROR: Failed to mint local token ({exc}). "
            "Set RECONDESK_TOKEN or use --email/--password instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    return create_access_token(
        "00000000-0000-0000-0000-000000000001",
        {"email": "gstr1-e2e@local.dev", "role": "admin"},
    )


def _login(base_url: str, email: str, password: str) -> str:
    url = base_url.rstrip("/") + "/api/v1/auth/login"
    try:
        resp = requests.post(
            url,
            json={"email": email, "password": password},
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        print(
            f"ERROR: Could not connect to {url}\n"
            "Is the server running? Start it, then retry.",
            file=sys.stderr,
        )
        sys.exit(1)

    if resp.status_code != 200:
        print(
            f"ERROR: Login failed — HTTP {resp.status_code}\n{resp.text[:500]}",
            file=sys.stderr,
        )
        sys.exit(1)

    data = resp.json()
    token = data.get("access_token")
    if not token:
        print(f"ERROR: Login response missing access_token: {data}", file=sys.stderr)
        sys.exit(1)
    return token


def _obtain_token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("RECONDESK_TOKEN") or os.environ.get("AUTH_TOKEN")
    if token:
        return token.strip()

    email = args.email or os.environ.get("RECONDESK_EMAIL")
    password = args.password or os.environ.get("RECONDESK_PASSWORD")
    if email and password:
        return _login(args.base_url, email, password)

    if args.mint_local_token or os.environ.get("RECONDESK_MINT_LOCAL_TOKEN") == "1":
        return _mint_local_token()

    print(
        "ERROR: No auth token provided.\n"
        "  export RECONDESK_TOKEN='<jwt>'\n"
        "  # or\n"
        "  export RECONDESK_EMAIL='...' RECONDESK_PASSWORD='...'\n"
        "  # or\n"
        "  python test_gstr1_reconcile_endpoint.py --mint-local-token",
        file=sys.stderr,
    )
    sys.exit(1)


def _mismatch_type_key(item: dict[str, Any]) -> str:
    """Normalise mismatch type to G1M1…G1M10 (or full code if unknown)."""
    raw = (
        item.get("mismatch_type")
        or item.get("decision_rule")
        or item.get("rule_id")
        or "?"
    )
    raw = str(raw)
    for code in (
        "G1M1", "G1M2", "G1M3", "G1M4", "G1M5", "G1M6",
        "G1M7", "G1M8", "G1M9", "G1M10",
    ):
        if code in raw:
            return code
    return raw


def _print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def _print_tie_out(tie_out: dict[str, Any]) -> None:
    _print_section("GSTR-1 vs GSTR-3B tie-out")
    print(f"  ret_period      : {tie_out.get('ret_period')}")
    print(f"  is_clean        : {tie_out.get('is_clean')}")
    print(f"  variance_count  : {tie_out.get('variance_count')}")
    print(f"  gstr1_records   : {tie_out.get('gstr1_record_count')}")

    g1 = tie_out.get("gstr1") or {}
    g3 = tie_out.get("gstr3b") or {}
    print()
    print("  Aggregates (paise → shown as ₹):")
    for field in (
        "taxable_value_paise",
        "igst_paise",
        "cgst_paise",
        "sgst_paise",
        "cess_paise",
        "total_tax_paise",
    ):
        g1v = (g1.get(field) or 0) / 100
        g3v = (g3.get(field) or 0) / 100
        print(f"    {field.replace('_paise', ''):<16}  GSTR-1={g1v:>14,.2f}  3B={g3v:>14,.2f}")

    variances = tie_out.get("variances") or []
    print()
    if not variances:
        print("  Variances: (none)")
    else:
        print(f"  Variances ({len(variances)}):")
        for v in variances:
            print(
                f"    - {v.get('field')}: GSTR-1={v.get('gstr1')}  "
                f"3B={v.get('gstr3b')}  diff={v.get('diff')} ({v.get('direction')})"
            )

    decisions = tie_out.get("mismatch_decisions") or []
    if decisions:
        print()
        print(f"  Tie-out mismatch decisions ({len(decisions)}):")
        for d in decisions:
            print(
                f"    - {d.get('mismatch_type')}: {d.get('decision_what')}"
            )


def _print_response(data: dict[str, Any]) -> None:
    summary = data.get("summary") or {}
    mismatches = data.get("mismatches") or []

    _print_section("Summary")
    for key in (
        "sr_total_records",
        "gstr1_total_records",
        "matched_count",
        "unmatched_sr_count",
        "unmatched_gstr1_count",
        "mismatch_count",
        "tie_out_clean",
        "tie_out_variance_count",
    ):
        if key in summary:
            print(f"  {key}: {summary[key]}")
    print(f"  elapsed_seconds: {data.get('elapsed_seconds')}")
    print(f"  success: {data.get('success')}")

    counts = Counter(_mismatch_type_key(m) for m in mismatches)
    _print_section("Mismatches (G1M1–G1M10)")
    print(f"  Total mismatches found: {len(mismatches)}")
    if not counts:
        print("  (no invoice-level mismatches classified)")
    else:
        print("  Counts by type:")
        known = {
            "G1M1", "G1M2", "G1M3", "G1M4", "G1M5", "G1M6",
            "G1M7", "G1M8", "G1M9", "G1M10",
        }
        for code in (
            "G1M1", "G1M2", "G1M3", "G1M4", "G1M5", "G1M6",
            "G1M7", "G1M8", "G1M9", "G1M10",
        ):
            if code in counts:
                print(f"    {code}: {counts[code]}")
        # Any unexpected keys
        for code, n in sorted(counts.items()):
            if code not in known:
                print(f"    {code}: {n}")

    docs = data.get("documents_issued") or {}
    if docs:
        _print_section("Table 13 – Documents Issued Summary")
        print(f"  source: {docs.get('source')}")
        print(f"  series: {docs.get('total_series')}")
        print(f"  total_issued: {docs.get('total_documents_issued')}")
        print(f"  cancellations_determinable: {docs.get('cancellations_determinable')}")
        for row in docs.get("series") or []:
            print(
                f"    - {row.get('document_type')} [{row.get('series_prefix') or '(numeric)'}] "
                f"{row.get('opening_number')} → {row.get('closing_number')} "
                f"issued={row.get('total_issued')} cancelled={row.get('cancelled')} "
                f"net={row.get('net_issued')}"
            )

    # Short WHAT lines for each mismatch
    if mismatches:
        print()
        print("  Detail:")
        for m in mismatches:
            print(
                f"    [{_mismatch_type_key(m)}] {m.get('decision_what') or m.get('mismatch_type')}"
            )

    tie_out = data.get("tie_out") or {}
    _print_tie_out(tie_out)

    _print_section("Full JSON response")
    print(json.dumps(data, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("RECONDESK_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--token", help="Bearer JWT (or set RECONDESK_TOKEN)")
    parser.add_argument("--email", help="Login email (or set RECONDESK_EMAIL)")
    parser.add_argument("--password", help="Login password (or set RECONDESK_PASSWORD)")
    parser.add_argument(
        "--mint-local-token",
        action="store_true",
        help="Mint a local HS256 JWT from app settings (dev only)",
    )
    parser.add_argument(
        "--filing-period",
        default=os.environ.get("GSTR1_FILING_PERIOD", "042025"),
        help="Optional gstr1_filing_period form field (MMYYYY). Default: 042025",
    )
    parser.add_argument(
        "--no-full-json",
        action="store_true",
        help="Skip dumping the full JSON body (print summaries only)",
    )
    args = parser.parse_args()

    sr_path = _resolve(SR_CANDIDATES, "Sales_Register_Sample_Corrected.xlsx")
    gstr1_path = _resolve(GSTR1_CANDIDATES, "sample_gstr1.json")
    gstr3b_path = _resolve(GSTR3B_CANDIDATES, "sample_gstr3b.json")

    print("Input files:")
    print(f"  sales_register_file : {sr_path}")
    print(f"  gstr1_json          : {gstr1_path}")
    print(f"  gstr3b_json         : {gstr3b_path}")

    token = _obtain_token(args)
    url = args.base_url.rstrip("/") + ENDPOINT_PATH
    print(f"\nPOST {url}")

    files = {
        "sales_register_file": (
            sr_path.name,
            sr_path.open("rb"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        "gstr1_json": (gstr1_path.name, gstr1_path.open("rb"), "application/json"),
        "gstr3b_json": (gstr3b_path.name, gstr3b_path.open("rb"), "application/json"),
    }
    data = {}
    if args.filing_period:
        data["gstr1_filing_period"] = args.filing_period

    headers = {"Authorization": f"Bearer {token}"}

    try:
        resp = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    except requests.exceptions.ConnectionError:
        print(
            f"\nERROR: Could not connect to {url}\n"
            "The server does not appear to be running on localhost:8000.\n"
            "Start the API (e.g. uvicorn app.main:app --reload --port 8000), then retry.",
            file=sys.stderr,
        )
        return 1
    except requests.exceptions.Timeout:
        print("\nERROR: Request timed out after 120s.", file=sys.stderr)
        return 1
    finally:
        for _, fh, _ in files.values():
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass

    print(f"HTTP {resp.status_code}")

    if resp.status_code != 200:
        print("\nERROR: Non-200 response from /api/gstr1-reconcile/", file=sys.stderr)
        ctype = resp.headers.get("content-type", "")
        if "application/json" in ctype:
            try:
                print(json.dumps(resp.json(), indent=2, default=str), file=sys.stderr)
            except Exception:  # noqa: BLE001
                print(resp.text[:2000], file=sys.stderr)
        else:
            print(resp.text[:2000], file=sys.stderr)
        return 1

    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: Response is not valid JSON: {exc}", file=sys.stderr)
        print(resp.text[:2000], file=sys.stderr)
        return 1

    if args.no_full_json:
        # Temporarily strip full dump by calling printers selectively
        summary = payload.get("summary") or {}
        mismatches = payload.get("mismatches") or []
        _print_section("Summary")
        for key, val in summary.items():
            print(f"  {key}: {val}")
        counts = Counter(_mismatch_type_key(m) for m in mismatches)
        _print_section("Mismatches (G1M1–G1M10)")
        print(f"  Total mismatches found: {len(mismatches)}")
        for code in (
            "G1M1", "G1M2", "G1M3", "G1M4", "G1M5", "G1M6",
            "G1M7", "G1M8", "G1M9", "G1M10",
        ):
            if code in counts:
                print(f"    {code}: {counts[code]}")
        for m in mismatches:
            print(f"    [{_mismatch_type_key(m)}] {m.get('decision_what')}")
        _print_tie_out(payload.get("tie_out") or {})
    else:
        _print_response(payload)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
