#!/usr/bin/env python3
"""ReconDesk Tally Bridge — local agent.

Pulls bill-wise Ledger Outstandings from Tally's local XML service
(localhost:9000 by default) and pushes parsed records to ReconDesk so
Rule 37 open invoices can be auto-marked as settled.

Usage:
  python tally_bridge_agent.py --config tally_bridge.config.json
  python tally_bridge_agent.py --config tally_bridge.config.json --test
  python tally_bridge_agent.py --config tally_bridge.config.json --once

Test mode fetches and saves the raw Tally XML only — nothing is pushed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "api_key": "",
    "recondesk_endpoint": "https://api.recondesk.in/api/tally-sync/outstanding",
    "tally_host": "localhost",
    "tally_port": 9000,
    "sync_interval_minutes": 60,
    "company_name": "",
}

TALLY_UNREACHABLE_MSG = (
    "Tally is not reachable on {host}:{port}. "
    "Open Tally, load the company, and enable the XML server under "
    "F1 > Settings > Connectivity (ODBC / XML port). "
    "Then retry."
)


def _setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("tally_bridge")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def load_config(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")
    cfg = {**DEFAULT_CONFIG, **raw}
    cfg["tally_port"] = int(cfg.get("tally_port") or 9000)
    cfg["sync_interval_minutes"] = max(1, int(cfg.get("sync_interval_minutes") or 60))
    cfg["tally_host"] = str(cfg.get("tally_host") or "localhost").strip()
    cfg["company_name"] = str(cfg.get("company_name") or "").strip()
    cfg["api_key"] = str(cfg.get("api_key") or "").strip()
    cfg["recondesk_endpoint"] = str(
        cfg.get("recondesk_endpoint") or DEFAULT_CONFIG["recondesk_endpoint"]
    ).strip()
    return cfg


def build_export_xml(company_name: str) -> str:
    """Tally Export Data request for bill-wise Ledger Outstandings."""
    company_xml = ""
    if company_name:
        # Escape minimal XML specials in company name
        safe = (
            company_name.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
        company_xml = f"<SVCURRENTCOMPANY>{safe}</SVCURRENTCOMPANY>\n"

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Ledger Outstandings</REPORTNAME>
    <STATICVARIABLES>
     <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
     {company_xml}    </STATICVARIABLES>
   </REQUESTDESC>
  </EXPORTDATA>
 </BODY>
</ENVELOPE>
"""


def fetch_tally_xml(host: str, port: int, company_name: str, timeout: float = 30.0) -> str:
    url = f"http://{host}:{port}"
    body = build_export_xml(company_name).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/xml", "Content-Length": str(len(body))},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.URLError as exc:
        raise ConnectionError(
            TALLY_UNREACHABLE_MSG.format(host=host, port=port)
        ) from exc
    except TimeoutError as exc:
        raise ConnectionError(
            TALLY_UNREACHABLE_MSG.format(host=host, port=port)
        ) from exc

    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _text(el: ET.Element | None) -> str:
    if el is None or el.text is None:
        return ""
    return str(el.text).strip()


def _find_text(el: ET.Element, names: tuple[str, ...]) -> str:
    wanted = {n.upper() for n in names}
    for child in el.iter():
        if _local(child.tag).upper() in wanted:
            t = _text(child)
            if t:
                return t
    return ""


def _parse_amount(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", "")
    if not s:
        return None
    # Tally sometimes suffixes Dr/Cr
    for suffix in ("Dr", "Cr", "DR", "CR"):
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    try:
        return float(s)
    except ValueError:
        return None


def _normalize_date(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    # YYYYMMDD (Tally native)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    # DD-MM-YYYY or DD/MM/YYYY
    for sep in ("-", "/", "."):
        parts = s.split(sep)
        if len(parts) == 3 and all(parts):
            d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(y) == 2:
                y = f"20{y}"
            if len(y) == 4:
                return f"{y}-{m}-{d}"
    return None


def parse_outstanding_records(xml_text: str) -> list[dict[str, Any]]:
    """Best-effort parse of Tally bill-wise XML into party/bill_ref/bill_date/amount.

    Real Tally XML shapes vary by version and report; --test mode is the
    source of truth for refining this parser against a live instance.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # Some Tally responses wrap multiple roots; try a soft envelope
        wrapped = f"<ROOT>{xml_text}</ROOT>"
        root = ET.fromstring(wrapped)

    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    # Walk bill-allocation style nodes and bill collections
    bill_tags = {
        "BILLALLOCATIONS.LIST",
        "BILLFIXED",
        "BILLOUTSTANDINGS.LIST",
        "BILLCL",
        "BILLWISEDETAILS.LIST",
    }
    for el in root.iter():
        tag = _local(el.tag).upper()
        if tag not in bill_tags and not tag.startswith("BILL"):
            continue
        # Prefer leaf bill rows that carry a name/ref
        bill_ref = (
            _find_text(el, ("BILLNAME", "NAME", "BILLREF", "BILLREFERENCENUMBER"))
            or (el.attrib.get("NAME") or "").strip()
        )
        if not bill_ref:
            continue
        # Skip container-only nodes that also nest children with their own refs
        child_bill_refs = [
            c
            for c in list(el)
            if _local(c.tag).upper() in bill_tags
            or _find_text(c, ("BILLNAME", "NAME", "BILLREF"))
        ]
        if child_bill_refs and _local(el.tag).upper().endswith(".LIST"):
            continue

        amount_raw = _find_text(
            el,
            ("AMOUNT", "BILLCREDITPERIOD", "CLOSINGBALANCE", "BILLAMOUNT", "PENDINGAMOUNT"),
        )
        # BILLCREDITPERIOD is often a period string — prefer numeric amount fields
        amount = None
        for name in ("AMOUNT", "CLOSINGBALANCE", "BILLAMOUNT", "PENDINGAMOUNT"):
            amount = _parse_amount(_find_text(el, (name,)))
            if amount is not None:
                break
        if amount is None:
            amount = _parse_amount(amount_raw)

        bill_date = _normalize_date(
            _find_text(el, ("BILLDATE", "DATE", "VOUCHERDATE", "INVOICEDATE"))
        )

        # Party: walk ancestors for LEDGERNAME / PARENT / PARTYNAME
        party = ""
        parent = el
        for _ in range(8):
            p = None
            # ElementTree has no .getparent(); scan by re-walking is expensive —
            # instead look at nested siblings first, then try common fields on self.
            party = _find_text(
                parent,
                ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME", "PARENT", "LEDGER"),
            )
            if party and party.upper() not in {"BILL-WISE DETAILS", "LEDGER OUTSTANDINGS"}:
                break
            party = ""
            break

        # Secondary pass: search nearby parent-ish text via full-tree heuristics
        if not party:
            # Look for preceding LEDGER entries by scanning the full path string
            party = _find_text(el, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))

        rec = {
            "party": party or "",
            "bill_ref": bill_ref,
            "bill_date": bill_date,
            "amount": abs(amount) if amount is not None else None,
        }
        key = (
            rec["party"],
            rec["bill_ref"],
            rec["bill_date"] or "",
            "" if rec["amount"] is None else f"{rec['amount']:.2f}",
        )
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)

    # Fallback: flat NAME+AMOUNT pairs under LEDGER nodes (simpler exports)
    if not records:
        current_party = ""
        for el in root.iter():
            tag = _local(el.tag).upper()
            if tag in {"LEDGERNAME", "LEDGER"} and _text(el):
                current_party = _text(el)
            if tag == "BILLNAME" and _text(el):
                bill_ref = _text(el)
                amount = None
                bill_date = None
                # sibling scan
                parent = None  # no parent link; use next siblings via iter only
                records.append(
                    {
                        "party": current_party,
                        "bill_ref": bill_ref,
                        "bill_date": bill_date,
                        "amount": amount,
                    }
                )

    return records


def push_records(
    endpoint: str,
    api_key: str,
    company_name: str,
    records: list[dict[str, Any]],
    timeout: float = 60.0,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "company_name": company_name,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "records": records,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}


def run_once(cfg: dict[str, Any], logger: logging.Logger, *, test_mode: bool, out_dir: Path) -> int:
    host = cfg["tally_host"]
    port = int(cfg["tally_port"])
    company = cfg["company_name"]
    logger.info("Fetching Ledger Outstandings from Tally at %s:%s (company=%r)", host, port, company)
    try:
        xml_text = fetch_tally_xml(host, port, company)
    except ConnectionError as exc:
        logger.error("%s", exc)
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"tally_outstanding_{stamp}.xml"
    raw_path.write_text(xml_text, encoding="utf-8")
    logger.info("Saved raw Tally XML → %s (%d bytes)", raw_path, len(xml_text.encode("utf-8")))

    if test_mode:
        logger.info("--test mode: skipping parse/push. Inspect the XML file above.")
        print(xml_text[:4000])
        if len(xml_text) > 4000:
            print(f"\n… truncated ({len(xml_text)} chars total); full file at {raw_path}")
        return 0

    try:
        records = parse_outstanding_records(xml_text)
    except ET.ParseError as exc:
        logger.error("Failed to parse Tally XML: %s", exc)
        return 3

    logger.info("Parsed %d bill-wise record(s)", len(records))
    parsed_path = out_dir / f"tally_outstanding_{stamp}.json"
    parsed_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    logger.info("Saved parsed records → %s", parsed_path)

    if not cfg["api_key"]:
        logger.error("api_key missing in config — cannot push")
        return 4
    if not cfg["recondesk_endpoint"]:
        logger.error("recondesk_endpoint missing in config — cannot push")
        return 4

    try:
        result = push_records(
            cfg["recondesk_endpoint"],
            cfg["api_key"],
            company,
            records,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        logger.error("Push failed HTTP %s: %s", exc.code, detail or exc.reason)
        return 5
    except urllib.error.URLError as exc:
        logger.error("Push failed: %s", exc)
        return 5

    logger.info("Push OK: %s", result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ReconDesk Tally Bridge local agent")
    parser.add_argument(
        "--config",
        default="tally_bridge.config.json",
        help="Path to JSON config (default: tally_bridge.config.json)",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Fetch and save raw Tally XML only; do not parse/push",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync then exit (default in --test mode)",
    )
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Directory for logs and saved XML/JSON (default: cwd)",
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = _setup_logging(out_dir / "tally_bridge.log")

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        logger.error("Config not found: %s", config_path)
        example = {**DEFAULT_CONFIG, "api_key": "rdb_…", "company_name": "Your Company"}
        logger.info("Example config:\n%s", json.dumps(example, indent=2))
        return 1

    try:
        cfg = load_config(config_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Invalid config: %s", exc)
        return 1

    once = args.once or args.test
    if once:
        return run_once(cfg, logger, test_mode=args.test, out_dir=out_dir)

    interval = int(cfg["sync_interval_minutes"]) * 60
    logger.info("Starting timer loop every %s minute(s)", cfg["sync_interval_minutes"])
    while True:
        code = run_once(cfg, logger, test_mode=False, out_dir=out_dir)
        if code != 0:
            logger.warning("Sync finished with code %s; will retry after interval", code)
        logger.info("Sleeping %s seconds…", interval)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
