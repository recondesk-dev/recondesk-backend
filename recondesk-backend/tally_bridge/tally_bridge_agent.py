#!/usr/bin/env python3
"""ReconDesk Tally Bridge — local agent.

Exports:
  1. Bills Payable (still-unpaid bill refs — never a settle trigger)
  2. Day Book Payment vouchers with Agst Ref bill allocations (settle evidence)

Pushes both to ReconDesk. Auto-settle happens only from Payment Agst Ref lines
when party-name confidence clears the server-side gate.

Usage (Windows .exe — preferred for CAs):
  ReconDeskTallyBridge.exe --config tally_bridge.config.json --test
  ReconDeskTallyBridge.exe --config tally_bridge.config.json --once
  ReconDeskTallyBridge.exe --config tally_bridge.config.json

Usage (Python):
  python tally_bridge_agent.py --config tally_bridge.config.json --test
  python tally_bridge_agent.py --config tally_bridge.config.json --once

When frozen (PyInstaller), default config and out-dir resolve next to the .exe.
Test mode fetches both exports, parses row counts, and saves XML/JSON —
nothing is pushed. Zero-row exports are logged as warnings.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_CONFIG = {
    "api_key": "",
    "recondesk_endpoint": "https://api.recondesk.in/api/tally-sync/outstanding",
    "pr_sync_endpoint": "https://api.recondesk.in/api/tally-sync/purchase-register",
    "tally_host": "localhost",
    "tally_port": 9000,
    "sync_interval_minutes": 60,
    "lookback_days": 200,
    "company_name": "",
    "client_gstin_id": "",
}

TALLY_UNREACHABLE_MSG = (
    "Tally is not reachable on {host}:{port}. "
    "Open Tally, load the company, and enable the XML server under "
    "F1 > Settings > Connectivity (ODBC / XML port). "
    "Then retry."
)

_PAYMENT_VOUCHER_ALIASES = {
    "payment",
    "pymt",
    "bank payment",
    "cash payment",
}


def _is_frozen() -> bool:
    """True when running as a PyInstaller (or similar) bundled executable."""
    return bool(getattr(sys, "frozen", False))


def _app_dir() -> Path:
    """Directory containing the .exe (frozen) or this script (dev)."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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
    cfg["lookback_days"] = max(1, int(cfg.get("lookback_days") or 200))
    cfg["tally_host"] = str(cfg.get("tally_host") or "localhost").strip()
    cfg["company_name"] = str(cfg.get("company_name") or "").strip()
    cfg["api_key"] = str(cfg.get("api_key") or "").strip()
    cfg["recondesk_endpoint"] = str(
        cfg.get("recondesk_endpoint") or DEFAULT_CONFIG["recondesk_endpoint"]
    ).strip()
    return cfg


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _company_static_xml(company_name: str) -> str:
    if not company_name:
        return ""
    return f"<SVCURRENTCOMPANY>{_xml_escape(company_name)}</SVCURRENTCOMPANY>\n"


def build_bills_payable_xml(company_name: str) -> str:
    """Company-wide payables outstanding (pending due per bill ref)."""
    company_xml = _company_static_xml(company_name)
    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Bills Payable</REPORTNAME>
    <STATICVARIABLES>
     <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
     {company_xml}    </STATICVARIABLES>
   </REQUESTDESC>
  </EXPORTDATA>
 </BODY>
</ENVELOPE>
"""


def build_daybook_payments_xml(
    company_name: str,
    from_date: str,
    to_date: str,
) -> str:
    """Day Book filtered to Payment vouchers for the lookback window.

    Dates must be YYYYMMDD (Tally native). Filter uses TDL formula on
    VoucherTypeName so custom payment voucher aliases still need a name
    containing 'Payment' (or known aliases are accepted at parse time).
    """
    company_xml = _company_static_xml(company_name)
    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Day Book</REPORTNAME>
    <STATICVARIABLES>
     <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
     <SVFROMDATE>{from_date}</SVFROMDATE>
     <SVTODATE>{to_date}</SVTODATE>
     {company_xml}    </STATICVARIABLES>
   </REQUESTDESC>
  </EXPORTDATA>
 </BODY>
</ENVELOPE>
"""


def build_purchase_register_xml(
    company_name: str,
    from_date: str,
    to_date: str,
) -> str:
    """Purchase Register for the period. Dates must be YYYYMMDD (Tally native).
    Mirrors build_bills_payable_xml's structure, adding the date-range
    STATICVARIABLES the same way build_daybook_payments_xml does."""
    company_xml = _company_static_xml(company_name)
    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <TALLYREQUEST>Export Data</TALLYREQUEST>
 </HEADER>
 <BODY>
  <EXPORTDATA>
   <REQUESTDESC>
    <REPORTNAME>Purchase Register</REPORTNAME>
    <STATICVARIABLES>
     <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
     <SVFROMDATE>{from_date}</SVFROMDATE>
     <SVTODATE>{to_date}</SVTODATE>
     {company_xml}    </STATICVARIABLES>
   </REQUESTDESC>
  </EXPORTDATA>
 </BODY>
</ENVELOPE>
"""


def fetch_tally_xml(
    host: str,
    port: int,
    body_xml: str,
    timeout: float = 60.0,
) -> str:
    url = f"http://{host}:{port}"
    body = body_xml.encode("utf-8")
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


def _find_direct_text(el: ET.Element, names: tuple[str, ...]) -> str:
    wanted = {n.upper() for n in names}
    for child in list(el):
        if _local(child.tag).upper() in wanted:
            t = _text(child)
            if t:
                return t
    return ""


def _parse_amount(raw: str) -> float | None:
    s = (raw or "").strip().replace(",", "").replace("₹", "").replace("Rs.", "")
    if not s:
        return None
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
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    for sep in ("-", "/", "."):
        parts = s.split(sep)
        if len(parts) == 3 and all(parts):
            d, m, y = parts[0].zfill(2), parts[1].zfill(2), parts[2]
            if len(y) == 2:
                y = f"20{y}"
            if len(y) == 4:
                return f"{y}-{m}-{d}"
    return None


# Matches numeric character references whose code-point is illegal in XML 1.0
# (all C0 controls except tab/LF/CR, plus the surrogate range and a few others).
_ILLEGAL_XML_CHARREF = re.compile(
    r"&#(?:x[0-9A-Fa-f]+|[0-9]+);"
    r"|[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]"
    r"|\uFFFE|\uFFFF"
)


def _strip_illegal_xml_charrefs(text: str) -> str:
    """Remove numeric character references and bare control characters that are
    illegal in XML 1.0 and cause ET.ParseError before we even reach the tree.
    Tally occasionally emits these (e.g. &#4; in narration fields).
    """
    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        raw = m.group(0)
        if raw.startswith("&#"):
            try:
                cp = int(raw[3:-1], 16) if raw[2] == "x" else int(raw[2:-1])
                return chr(cp) if 0x20 <= cp <= 0xD7FF or cp in (0x9, 0xA, 0xD) else ""
            except ValueError:
                return ""
        return ""  # bare control character — strip it

    return _ILLEGAL_XML_CHARREF.sub(_replace, text)


def _parse_root(xml_text: str) -> ET.Element:
    xml_text = _strip_illegal_xml_charrefs(xml_text)
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        return ET.fromstring(f"<ROOT>{xml_text}</ROOT>")


def parse_outstanding_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse Bills Payable / bill-wise outstanding XML.

    ``amount`` is remaining due (pending), never amount paid.
    """
    root = _parse_root(xml_text)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    bill_tags = {
        "BILLALLOCATIONS.LIST",
        "BILLFIXED",
        "BILLOUTSTANDINGS.LIST",
        "BILLCL",
        "BILLWISEDETAILS.LIST",
        "BILLDETAILS",
    }
    current_party = ""
    for el in root.iter():
        tag = _local(el.tag).upper()
        if tag in {"LEDGERNAME", "PARTYLEDGERNAME", "PARTYNAME"} and _text(el):
            current_party = _text(el)

        if tag not in bill_tags and not tag.startswith("BILL"):
            continue

        bill_ref = (
            _find_text(el, ("BILLNAME", "NAME", "BILLREF", "BILLREFERENCENUMBER"))
            or (el.attrib.get("NAME") or "").strip()
        )
        if not bill_ref:
            continue

        child_bill_containers = [
            c
            for c in list(el)
            if _local(c.tag).upper() in bill_tags
        ]
        if child_bill_containers and tag.endswith(".LIST"):
            continue

        amount = None
        for name in ("AMOUNT", "CLOSINGBALANCE", "BILLAMOUNT", "PENDINGAMOUNT"):
            amount = _parse_amount(_find_text(el, (name,)))
            if amount is not None:
                break

        bill_date = _normalize_date(
            _find_text(el, ("BILLDATE", "DATE", "VOUCHERDATE", "INVOICEDATE"))
        )
        party = (
            _find_text(el, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
            or current_party
        )
        if party.upper() in {"BILL-WISE DETAILS", "BILLS PAYABLE", "LEDGER OUTSTANDINGS"}:
            party = current_party

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

    if not records:
        current_party = ""
        for el in root.iter():
            tag = _local(el.tag).upper()
            if tag in {"LEDGERNAME", "LEDGER"} and _text(el):
                current_party = _text(el)
            if tag == "BILLNAME" and _text(el):
                records.append(
                    {
                        "party": current_party,
                        "bill_ref": _text(el),
                        "bill_date": None,
                        "amount": None,
                    }
                )

    return records


def _is_payment_voucher_type(name: str) -> bool:
    n = (name or "").strip().lower()
    if not n:
        return False
    if n in _PAYMENT_VOUCHER_ALIASES:
        return True
    return "payment" in n


def _is_agst_ref(bill_type: str) -> bool:
    t = (bill_type or "").strip().lower().replace(".", "")
    t = " ".join(t.split())
    return t in {"agst ref", "against ref", "against reference", "agstref"}


def parse_payment_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse Day Book XML into Payment Agst Ref allocation rows.

    Only BILLTYPE=Agst Ref lines are emitted. On Account / Advance / New Ref
    are ignored (not settle evidence for a specific bill).
    """
    root = _parse_root(xml_text)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue
        vtype = _find_direct_text(voucher, ("VOUCHERTYPENAME",)) or _find_text(
            voucher, ("VOUCHERTYPENAME",)
        )
        if not _is_payment_voucher_type(vtype):
            continue

        payment_date = _normalize_date(
            _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
            or _find_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
        )

        for entry in voucher.iter():
            etag = _local(entry.tag).upper()
            if etag not in {
                "ALLLEDGERENTRIES.LIST",
                "LEDGERENTRIES.LIST",
                "LEDGERENTRY",
            }:
                continue
            party = (
                _find_direct_text(entry, ("LEDGERNAME", "PARTYLEDGERNAME"))
                or _find_text(entry, ("LEDGERNAME", "PARTYLEDGERNAME"))
            )
            for alloc in entry.iter():
                if _local(alloc.tag).upper() != "BILLALLOCATIONS.LIST":
                    continue
                bill_type = (
                    _find_direct_text(alloc, ("BILLTYPE", "TYPE"))
                    or _find_text(alloc, ("BILLTYPE", "TYPE"))
                )
                if not _is_agst_ref(bill_type):
                    continue
                bill_ref = (
                    _find_direct_text(alloc, ("NAME", "BILLNAME", "BILLREF"))
                    or (alloc.attrib.get("NAME") or "").strip()
                    or _find_text(alloc, ("NAME", "BILLNAME", "BILLREF"))
                )
                if not bill_ref:
                    continue
                amount = _parse_amount(
                    _find_direct_text(alloc, ("AMOUNT",))
                    or _find_text(alloc, ("AMOUNT",))
                )
                rec = {
                    "party": party or "",
                    "bill_ref": bill_ref,
                    "amount": abs(amount) if amount is not None else None,
                    "payment_date": payment_date,
                    "voucher_number": voucher_number or "",
                    "voucher_type": vtype or "Payment",
                }
                key = (
                    rec["party"],
                    rec["bill_ref"],
                    rec["payment_date"] or "",
                    rec["voucher_number"],
                    "" if rec["amount"] is None else f"{rec['amount']:.2f}",
                )
                if key in seen:
                    continue
                seen.add(key)
                records.append(rec)

    return records


def parse_purchase_register_records(xml_text: str) -> list:
    """Parse Day Book XML into Purchase Register rows.

    Source is the same Day Book fetch used by parse_payment_records() —
    the dedicated "Purchase Register" report returns monthly summary
    totals, not itemized vouchers, so it is the wrong source.

    Vouchers with ACTION="Cancel" are skipped (deleted/superseded entries).
    """
    root = _parse_root(xml_text)
    records = []
    seen = set()

    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue
        if (voucher.attrib.get("ACTION") or "").strip().lower() == "cancel":
            continue

        voucher_date = _normalize_date(
            _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
            or _find_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
        )
        party = (
            _find_direct_text(voucher, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
            or _find_text(voucher, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
        )
        party_gstin = (
            _find_direct_text(voucher, ("PARTYGSTIN", "GSTIN", "GSTREGISTRATIONNUMBER"))
            or _find_text(voucher, ("PARTYGSTIN", "GSTIN", "GSTREGISTRATIONNUMBER"))
        )

        taxable_amt = 0.0
        cgst_amt = 0.0
        sgst_amt = 0.0
        igst_amt = 0.0

        for entry in voucher.iter():
            etag = _local(entry.tag).upper()
            if etag not in {"ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST", "LEDGERENTRY"}:
                continue
            ledger_name = (
                _find_direct_text(entry, ("LEDGERNAME",))
                or _find_text(entry, ("LEDGERNAME",))
            )
            amount = _parse_amount(
                _find_direct_text(entry, ("AMOUNT",)) or _find_text(entry, ("AMOUNT",))
            )
            if amount is None:
                continue
            name_upper = (ledger_name or "").upper()
            if "CGST" in name_upper:
                cgst_amt += abs(amount)
            elif "SGST" in name_upper or "UTGST" in name_upper:
                sgst_amt += abs(amount)
            elif "IGST" in name_upper:
                igst_amt += abs(amount)
            elif ledger_name and ledger_name != party:
                taxable_amt += abs(amount)

        gross_total = taxable_amt + cgst_amt + sgst_amt + igst_amt

        rec = {
            "GSTIN/UIN": party_gstin or "",
            "Party's A/c Name": party or "",
            "Inv No.": voucher_number or "",
            "Inv Date": voucher_date or "",
            "Taxable Amt": f"{taxable_amt:.2f}",
            "IGST Amt": f"{igst_amt:.2f}",
            "CGST Amt": f"{cgst_amt:.2f}",
            "SGST Amt": f"{sgst_amt:.2f}",
            "Gross Total": f"{gross_total:.2f}",
        }
        key = (rec["Inv No."], rec["GSTIN/UIN"])
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)

    return records


def push_sync_payload(
    endpoint: str,
    api_key: str,
    company_name: str,
    outstanding: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    timeout: float = 60.0,
) -> dict[str, Any]:
    payload = json.dumps(
        {
            "company_name": company_name,
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "outstanding": outstanding,
            "payments": payments,
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


def push_purchase_register_payload(
    endpoint: str,
    api_key: str,
    client_gstin_id: str,
    period: str,  # "YYYY-MM"
    company_name: str,
    rows: list,
    timeout: float = 60.0,
) -> dict:
    payload = json.dumps(
        {
            "client_gstin_id": client_gstin_id,
            "period": period,
            "company_name": company_name,
            "rows": rows,
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


def _lookback_window(lookback_days: int) -> tuple[str, str]:
    to_dt = datetime.now().date()
    from_dt = to_dt - timedelta(days=max(1, int(lookback_days)))
    return from_dt.strftime("%Y%m%d"), to_dt.strftime("%Y%m%d")


def _group_purchase_rows_by_period(rows: list) -> dict:
    """Groups rows by 'YYYY-MM' derived from each row's 'Inv Date'
    (already normalized to YYYY-MM-DD by parse_purchase_register_records).
    Rows with missing/unparseable dates are dropped into a "" bucket and
    logged as a warning by the caller — they can't be attached to a
    period-scoped run."""
    grouped: dict = {}
    for row in rows:
        inv_date = row.get("Inv Date") or ""
        period = inv_date[:7] if len(inv_date) >= 7 else ""
        grouped.setdefault(period, []).append(row)
    return grouped


def run_once(
    cfg: dict[str, Any],
    logger: logging.Logger,
    *,
    test_mode: bool,
    out_dir: Path,
) -> int:
    host = cfg["tally_host"]
    port = int(cfg["tally_port"])
    company = cfg["company_name"]
    lookback = int(cfg["lookback_days"])
    from_ymd, to_ymd = _lookback_window(lookback)

    logger.info(
        "Fetching Bills Payable from Tally at %s:%s (company=%r)",
        host,
        port,
        company,
    )
    try:
        outstanding_xml = fetch_tally_xml(
            host, port, build_bills_payable_xml(company)
        )
    except ConnectionError as exc:
        logger.error("%s", exc)
        return 2

    logger.info(
        "Fetching Day Book payments %s→%s (lookback_days=%s)",
        from_ymd,
        to_ymd,
        lookback,
    )
    try:
        payments_xml = fetch_tally_xml(
            host,
            port,
            build_daybook_payments_xml(company, from_ymd, to_ymd),
            timeout=120.0,
        )
    except ConnectionError as exc:
        logger.error("%s", exc)
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outstanding_path = out_dir / f"tally_bills_payable_{stamp}.xml"
    payments_path = out_dir / f"tally_daybook_payments_{stamp}.xml"
    outstanding_path.write_text(outstanding_xml, encoding="utf-8")
    payments_path.write_text(payments_xml, encoding="utf-8")
    outstanding_bytes = len(outstanding_xml.encode("utf-8"))
    payments_bytes = len(payments_xml.encode("utf-8"))
    logger.info(
        "Saved raw XML → %s (%d bytes), %s (%d bytes)",
        outstanding_path,
        outstanding_bytes,
        payments_path,
        payments_bytes,
    )

    try:
        outstanding = parse_outstanding_records(outstanding_xml)
        payments = parse_payment_records(payments_xml)
    except ET.ParseError as exc:
        logger.error("Failed to parse Tally XML: %s", exc)
        return 3

    purchase_rows = parse_purchase_register_records(payments_xml)
    purchase_by_period = _group_purchase_rows_by_period(purchase_rows)

    unattached = purchase_by_period.pop("", [])
    if unattached:
        logger.warning(
            "%d purchase row(s) had no parseable Inv Date \u2014 skipped, not pushed",
            len(unattached),
        )

    logger.info(
        "Purchase Register \u2192 %d row(s) across %d period(s): %s",
        len(purchase_rows), len(purchase_by_period), sorted(purchase_by_period.keys()),
    )

    outstanding_n = len(outstanding)
    payments_n = len(payments)
    logger.info(
        "Export summary: Bills Payable → %d outstanding row(s) "
        "(%d raw bytes); Day Book Payment Agst Ref → %d payment row(s) "
        "(%d raw bytes)",
        outstanding_n,
        outstanding_bytes,
        payments_n,
        payments_bytes,
    )
    if outstanding_n == 0:
        logger.warning(
            "Bills Payable parsed 0 rows — report may be empty, wrong "
            "REPORTNAME for this Tally version, or XML shape not recognized. "
            "Inspect %s",
            outstanding_path,
        )
    if payments_n == 0:
        logger.warning(
            "Day Book Payment Agst Ref parsed 0 rows — no Payment vouchers "
            "in lookback, voucher filter mismatch, or no Agst Ref allocations. "
            "Inspect %s",
            payments_path,
        )
    if outstanding_bytes == 0:
        logger.warning("Bills Payable raw XML is empty (0 bytes)")
    if payments_bytes == 0:
        logger.warning("Day Book payments raw XML is empty (0 bytes)")

    parsed_path = out_dir / f"tally_bridge_{stamp}.json"
    parsed_path.write_text(
        json.dumps(
            {"outstanding": outstanding, "payments": payments},
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("Saved parsed payload → %s", parsed_path)

    if test_mode:
        logger.info(
            "--test mode: parse complete; NOT pushing to ReconDesk. "
            "Bills Payable = unpaid check only; Payment Agst Ref = settle evidence."
        )
        print("")
        print("=== Tally Bridge --test summary ===")
        print(f"Bills Payable:     {outstanding_n} outstanding row(s)  [{outstanding_path.name}]")
        print(f"Day Book Payments: {payments_n} Agst Ref payment row(s)  [{payments_path.name}]")
        if outstanding_n == 0 or payments_n == 0:
            print("WARNING: one or both exports returned zero parsed rows — do not enable push until fixed.")
        print(f"Parsed JSON:       {parsed_path.name}")
        print("--- Bills Payable XML preview (first 2k) ---")
        print(outstanding_xml[:2000] or "(empty)")
        print("--- Day Book payments XML preview (first 2k) ---")
        print(payments_xml[:2000] or "(empty)")
        print(f"Purchase Register:  {len(purchase_rows)} row(s) across "
              f"{len(purchase_by_period)} period(s)  {sorted(purchase_by_period.keys())}  [from Day Book]")
        return 0

    if not cfg["api_key"]:
        logger.error("api_key missing in config — cannot push")
        return 4
    if not cfg["recondesk_endpoint"]:
        logger.error("recondesk_endpoint missing in config — cannot push")
        return 4

    try:
        result = push_sync_payload(
            cfg["recondesk_endpoint"],
            cfg["api_key"],
            company,
            outstanding,
            payments,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        logger.error("Push failed HTTP %s: %s", exc.code, detail or exc.reason)
        return 5
    except urllib.error.URLError as exc:
        logger.error("Push failed: %s", exc)
        return 5

    logger.info("Push OK: %s", result)

    if not cfg.get("client_gstin_id"):
        logger.warning("client_gstin_id not set in config \u2014 skipping purchase register push")
    elif not cfg.get("pr_sync_endpoint"):
        logger.warning("pr_sync_endpoint not set in config \u2014 skipping purchase register push")
    else:
        for period, period_rows in purchase_by_period.items():
            try:
                pr_result = push_purchase_register_payload(
                    cfg["pr_sync_endpoint"],
                    cfg["api_key"],
                    cfg["client_gstin_id"],
                    period,
                    company,
                    period_rows,
                )
                logger.info("Purchase register push OK for %s: %s", period, pr_result)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                logger.error("Purchase register push failed for %s HTTP %s: %s",
                             period, exc.code, detail or exc.reason)
            except urllib.error.URLError as exc:
                logger.error("Purchase register push failed for %s: %s", period, exc)

    return 0


def main(argv: list[str] | None = None) -> int:
    app_dir = _app_dir()
    default_config = str(app_dir / "tally_bridge.config.json")
    default_out = str(app_dir)

    parser = argparse.ArgumentParser(description="ReconDesk Tally Bridge local agent")
    parser.add_argument(
        "--config",
        default=default_config,
        help=(
            "Path to JSON config "
            f"(default: {default_config} — next to the .exe when frozen)"
        ),
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Fetch + parse both exports and print row counts; do not push",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single sync then exit (default in --test mode)",
    )
    parser.add_argument(
        "--out-dir",
        default=default_out,
        help=(
            "Directory for logs and saved XML/JSON "
            f"(default: {default_out} — next to the .exe when frozen)"
        ),
    )
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = _setup_logging(out_dir / "tally_bridge.log")

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        logger.error("Config not found: %s", config_path)
        example = {
            **DEFAULT_CONFIG,
            "api_key": "rdb_…",
            "company_name": "Your Company",
        }
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
