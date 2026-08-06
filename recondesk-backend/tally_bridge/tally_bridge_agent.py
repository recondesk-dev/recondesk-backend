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


def _collection_attrs(top: int | None = None, start: int | None = None) -> str:
    if top is not None and top > 0:
        s = start if (start is not None and start > 0) else 1
        return f' TOP="{top}" START="{s}"'
    return ""


def build_daybook_payments_xml(
    company_name: str,
    from_date: str,
    to_date: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    company_xml = _company_static_xml(company_name)
    date_math = "($$YearOfDate:$Date * 10000 + $$MonthOfDate:$Date * 100 + $$DayOfDate:$Date)"
    date_filter = f"NOT $$IsEmpty:$Date AND {date_math} &gt;= {from_date} AND {date_math} &lt;= {to_date}"

    filters = ["RD_IsPayment", "RD_InDateRange"]
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filters.append("RD_MinAlterId")
        alter_formula = f'\n     <SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>'

    filters_str = ",".join(filters)
    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_PaymentVouchers</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_PaymentVouchers" ISMODIFY="No"{coll_attrs}>
      <TYPE>Voucher</TYPE>
      <FILTERS>{filters_str}</FILTERS>
      <FETCH>Date,VoucherTypeName,VoucherNumber,PartyledgerName,ALTERID,MASTERID,ISCANCELLED,ISDELETED,
AllLedgerEntries.LedgerName,AllLedgerEntries.Amount,
AllLedgerEntries.BillAllocations.Name,
AllLedgerEntries.BillAllocations.BillType,
AllLedgerEntries.BillAllocations.Amount,
AllLedgerEntries.CategoryAllocations.Category,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount</FETCH>
     </COLLECTION>
     <SYSTEM TYPE="Formulae" NAME="RD_IsPayment">$$IsPayment:$VoucherTypeName</SYSTEM>
     <SYSTEM TYPE="Formulae" NAME="RD_InDateRange">{date_filter}</SYSTEM>{alter_formula}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_purchase_register_xml(
    company_name: str,
    from_date: str,
    to_date: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    company_xml = _company_static_xml(company_name)
    date_math = "($$YearOfDate:$Date * 10000 + $$MonthOfDate:$Date * 100 + $$DayOfDate:$Date)"
    date_filter = f"NOT $$IsEmpty:$Date AND {date_math} &gt;= {from_date} AND {date_math} &lt;= {to_date}"

    filters = ["RD_IsPurchase", "RD_InDateRange"]
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filters.append("RD_MinAlterId")
        alter_formula = f'\n     <SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>'

    filters_str = ",".join(filters)
    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_PurchaseVouchers</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_PurchaseVouchers" ISMODIFY="No"{coll_attrs}>
      <TYPE>Voucher</TYPE>
      <FILTERS>{filters_str}</FILTERS>
      <FETCH>Date,ReferenceDate,Reference,VoucherNumber,VoucherTypeName,
PartyledgerName,PartyGstin,ALTERID,MASTERID,ISCANCELLED,ISDELETED,
AllLedgerEntries.LedgerName,AllLedgerEntries.Amount,
AllLedgerEntries.CategoryAllocations.Category,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount,
AllInventoryEntries.StockItemName,AllInventoryEntries.BilledQty,AllInventoryEntries.Rate,AllInventoryEntries.Amount,
InventoryEntries.StockItemName,InventoryEntries.BilledQty,InventoryEntries.Rate,InventoryEntries.Amount</FETCH>
     </COLLECTION>
     <SYSTEM TYPE="Formulae" NAME="RD_IsPurchase">$$IsPurchase:$VoucherTypeName</SYSTEM>
     <SYSTEM TYPE="Formulae" NAME="RD_InDateRange">{date_filter}</SYSTEM>{alter_formula}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_sales_register_xml(
    company_name: str,
    from_date: str,
    to_date: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    company_xml = _company_static_xml(company_name)
    date_math = "($$YearOfDate:$Date * 10000 + $$MonthOfDate:$Date * 100 + $$DayOfDate:$Date)"
    date_filter = f"NOT $$IsEmpty:$Date AND {date_math} &gt;= {from_date} AND {date_math} &lt;= {to_date}"

    filters = ["RD_IsSales", "RD_InDateRange"]
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filters.append("RD_MinAlterId")
        alter_formula = f'\n     <SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>'

    filters_str = ",".join(filters)
    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_SalesVouchers</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_SalesVouchers" ISMODIFY="No"{coll_attrs}>
      <TYPE>Voucher</TYPE>
      <FILTERS>{filters_str}</FILTERS>
      <FETCH>Date,ReferenceDate,Reference,VoucherNumber,VoucherTypeName,
PartyledgerName,PartyGstin,ALTERID,MASTERID,ISCANCELLED,ISDELETED,
AllLedgerEntries.LedgerName,AllLedgerEntries.Amount,
AllLedgerEntries.CategoryAllocations.Category,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount,
AllInventoryEntries.StockItemName,AllInventoryEntries.BilledQty,AllInventoryEntries.Rate,AllInventoryEntries.Amount,
InventoryEntries.StockItemName,InventoryEntries.BilledQty,InventoryEntries.Rate,InventoryEntries.Amount</FETCH>
     </COLLECTION>
     <SYSTEM TYPE="Formulae" NAME="RD_IsSales">$$IsSales:$VoucherTypeName</SYSTEM>
     <SYSTEM TYPE="Formulae" NAME="RD_InDateRange">{date_filter}</SYSTEM>{alter_formula}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_credit_debit_notes_xml(
    company_name: str,
    from_date: str,
    to_date: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    company_xml = _company_static_xml(company_name)
    date_math = "($$YearOfDate:$Date * 10000 + $$MonthOfDate:$Date * 100 + $$DayOfDate:$Date)"
    date_filter = f"NOT $$IsEmpty:$Date AND {date_math} &gt;= {from_date} AND {date_math} &lt;= {to_date}"

    filters = ["RD_IsCDN", "RD_InDateRange"]
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filters.append("RD_MinAlterId")
        alter_formula = f'\n     <SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>'

    filters_str = ",".join(filters)
    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_CreditDebitNotes</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_CreditDebitNotes" ISMODIFY="No"{coll_attrs}>
      <TYPE>Voucher</TYPE>
      <FILTERS>{filters_str}</FILTERS>
      <FETCH>Date,ReferenceDate,Reference,VoucherNumber,VoucherTypeName,
PartyledgerName,PartyGstin,ALTERID,MASTERID,ISCANCELLED,ISDELETED,
AllLedgerEntries.LedgerName,AllLedgerEntries.Amount,
AllLedgerEntries.CategoryAllocations.Category,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount,
AllInventoryEntries.StockItemName,AllInventoryEntries.BilledQty,AllInventoryEntries.Rate,AllInventoryEntries.Amount,
InventoryEntries.StockItemName,InventoryEntries.BilledQty,InventoryEntries.Rate,InventoryEntries.Amount</FETCH>
     </COLLECTION>
     <SYSTEM TYPE="Formulae" NAME="RD_IsCDN">$$IsCreditNote:$VoucherTypeName OR $$IsDebitNote:$VoucherTypeName</SYSTEM>
     <SYSTEM TYPE="Formulae" NAME="RD_InDateRange">{date_filter}</SYSTEM>{alter_formula}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_receipt_journal_contra_xml(
    company_name: str,
    from_date: str,
    to_date: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    """Fetch Receipt, Journal, and Contra vouchers via TDL COLLECTION."""
    company_xml = _company_static_xml(company_name)
    date_math = "($$YearOfDate:$Date * 10000 + $$MonthOfDate:$Date * 100 + $$DayOfDate:$Date)"
    date_filter = f"NOT $$IsEmpty:$Date AND {date_math} &gt;= {from_date} AND {date_math} &lt;= {to_date}"

    filters = ["RD_IsRJC", "RD_InDateRange"]
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filters.append("RD_MinAlterId")
        alter_formula = f'\n     <SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>'

    filters_str = ",".join(filters)
    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_ReceiptJournalContra</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    <SVFROMDATE>{from_date}</SVFROMDATE>
    <SVTODATE>{to_date}</SVTODATE>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_ReceiptJournalContra" ISMODIFY="No"{coll_attrs}>
      <TYPE>Voucher</TYPE>
      <FILTERS>{filters_str}</FILTERS>
      <FETCH>Date,ReferenceDate,Reference,VoucherNumber,VoucherTypeName,
PartyledgerName,PartyGstin,GUID,ALTERID,MASTERID,ISCANCELLED,ISDELETED,
AllLedgerEntries.LedgerName,AllLedgerEntries.Amount,
AllLedgerEntries.CategoryAllocations.Category,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Name,
AllLedgerEntries.CategoryAllocations.CostCentreAllocations.Amount</FETCH>
     </COLLECTION>
     <SYSTEM TYPE="Formulae" NAME="RD_IsRJC">$$IsReceipt:$VoucherTypeName OR $$IsJournal:$VoucherTypeName OR $$IsContra:$VoucherTypeName</SYSTEM>
     <SYSTEM TYPE="Formulae" NAME="RD_InDateRange">{date_filter}</SYSTEM>{alter_formula}
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_open_companies_xml() -> str:
    """Fetch currently loaded/open companies in Tally via TDL COLLECTION."""
    return """<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_OpenCompanies</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
   </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_OpenCompanies" ISMODIFY="No">
      <TYPE>Company</TYPE>
      <FETCH>NAME,COMPANYNUMBER,GUID,GSTREGISTRATIONNUMBER,STARTINGFROM</FETCH>
     </COLLECTION>
    </TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def parse_open_companies_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse TDL Company Collection XML into open company metadata records."""
    if not xml_text:
        return []
    try:
        root = _parse_root(xml_text)
    except ET.ParseError:
        return []

    records = []
    seen = set()
    for elem in root.iter():
        if _local(elem.tag).upper() != "COMPANY":
            continue
        name = (
            _find_direct_text(elem, ("NAME", "COMPANYNAME"))
            or _find_text(elem, ("NAME", "COMPANYNAME"))
            or (elem.attrib.get("NAME") or "").strip()
        )
        if not name or name in seen:
            continue
        seen.add(name)

        comp_no = _find_direct_text(elem, ("COMPANYNUMBER",)) or _find_text(elem, ("COMPANYNUMBER",))
        guid = _find_direct_text(elem, ("GUID",)) or _find_text(elem, ("GUID",))
        gstin = _find_direct_text(elem, ("GSTREGISTRATIONNUMBER", "PARTYGSTIN")) or _find_text(elem, ("GSTREGISTRATIONNUMBER", "PARTYGSTIN"))

        records.append({
            "name": name,
            "company_number": comp_no or "",
            "guid": guid or "",
            "gstin": (gstin or "").strip().upper(),
        })
    return records


def build_ledger_master_xml(
    company_name: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    company_xml = _company_static_xml(company_name)
    filter_tag = ""
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filter_tag = "<FILTERS>RD_MinAlterId</FILTERS>\n       "
        alter_formula = f'<SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>\n      '

    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_LedgerMaster</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_LedgerMaster" ISMODIFY="No"{coll_attrs}>
      <TYPE>Ledger</TYPE>
      {filter_tag}<FETCH>NAME,PARENT,GSTIN,PARTYGSTIN,GSTREGISTRATIONNUMBER,LEDSTATENAME,STATENAME,OPENINGBALANCE,CLOSINGBALANCE,ALTERID,MASTERID,LEDGSTREGDETAILS.LIST,LEDMAILINGDETAILS.LIST</FETCH>
     </COLLECTION>
      {alter_formula}</TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_stock_master_xml(
    company_name: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    """Fetch Stock Item masters via TDL COLLECTION."""
    company_xml = _company_static_xml(company_name)
    filter_tag = ""
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filter_tag = "<FILTERS>RD_MinAlterId</FILTERS>\n       "
        alter_formula = f'<SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>\n      '

    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_StockMaster</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_StockMaster" ISMODIFY="No"{coll_attrs}>
      <TYPE>StockItem</TYPE>
      {filter_tag}<FETCH>NAME,PARENT,CATEGORY,GSTHSNNAME,HSNCODE,HSNSACCODE,GSTRATE,OPENINGBALANCE,CLOSINGBALANCE,BASEUNITS,ALTERID,MASTERID</FETCH>
     </COLLECTION>
      {alter_formula}</TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""


def build_cost_centre_master_xml(
    company_name: str,
    min_alter_id: int | None = None,
    top: int | None = None,
    start: int | None = None,
) -> str:
    """Fetch Cost Centre masters via TDL COLLECTION."""
    company_xml = _company_static_xml(company_name)
    filter_tag = ""
    alter_formula = ""
    if min_alter_id is not None and min_alter_id > 0:
        filter_tag = "<FILTERS>RD_MinAlterId</FILTERS>\n       "
        alter_formula = f'<SYSTEM TYPE="Formulae" NAME="RD_MinAlterId">$ALTERID &gt; {min_alter_id}</SYSTEM>\n      '

    coll_attrs = _collection_attrs(top, start)

    return f"""<?xml version="1.0"?>
<ENVELOPE>
 <HEADER>
  <VERSION>1</VERSION>
  <TALLYREQUEST>Export</TALLYREQUEST>
  <TYPE>Collection</TYPE>
  <ID>RD_CostCentreMaster</ID>
 </HEADER>
 <BODY>
  <DESC>
   <STATICVARIABLES>
    <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
    {company_xml}  </STATICVARIABLES>
   <TDL>
    <TDLMESSAGE>
     <COLLECTION NAME="RD_CostCentreMaster" ISMODIFY="No"{coll_attrs}>
      <TYPE>CostCentre</TYPE>
      {filter_tag}<FETCH>NAME,CATEGORY,PARENT,ALTERID,MASTERID</FETCH>
     </COLLECTION>
      {alter_formula}</TDLMESSAGE>
   </TDL>
  </DESC>
 </BODY>
</ENVELOPE>
"""



def fetch_tally_xml(
    host: str,
    port: int,
    body_xml: str,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> str:
    url = f"http://{host}:{port}"
    body = body_xml.encode("utf-8")

    last_exc = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Content-Type": "application/xml", "Content-Length": str(len(body))},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            for encoding in ("utf-8", "utf-16", "latin-1"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2.0 ** (attempt + 1)
                logging.getLogger("tally_bridge").warning(
                    "Tally request to %s:%d failed (attempt %d/%d): %s. Retrying in %.1fs…",
                    host,
                    port,
                    attempt + 1,
                    max_retries,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

    raise ConnectionError(
        TALLY_UNREACHABLE_MSG.format(host=host, port=port)
    ) from last_exc


def fetch_tally_xml_paginated(
    host: str,
    port: int,
    builder_fn: Any,
    *args: Any,
    batch_size: int = 1000,
    timeout: float = 120.0,
    **kwargs: Any,
) -> str:
    """Paginate TDL COLLECTION requests in batches of batch_size using TOP and START attributes.

    Prevents Tally timeouts and RAM exhaustion on massive databases (50k+ records).
    Merges batch XML envelopes into a single combined TDL response envelope.
    """
    first_resp_xml = ""
    first_root: ET.Element | None = None
    collection_node: ET.Element | None = None
    seen_page_starts: set[str] = set()
    start = 1

    while True:
        kwargs_batch = dict(kwargs)
        kwargs_batch["top"] = batch_size
        kwargs_batch["start"] = start

        batch_req_xml = builder_fn(*args, **kwargs_batch)
        resp_xml = fetch_tally_xml(host, port, batch_req_xml, timeout=timeout)

        if not resp_xml:
            break

        try:
            root = _parse_root(resp_xml)
        except ET.ParseError:
            if start == 1:
                return resp_xml
            break

        coll_elem = None
        for elem in root.iter():
            if _local(elem.tag).upper() == "COLLECTION":
                coll_elem = elem
                break

        records = [e for e in coll_elem] if coll_elem is not None else []
        if not records:
            if start == 1:
                return resp_xml
            break

        page_id = (
            records[0].attrib.get("REMOTEID")
            or records[0].attrib.get("NAME")
            or _find_direct_text(records[0], ("GUID", "MASTERID", "ALTERID", "NAME"))
            or _find_text(records[0], ("GUID", "MASTERID", "ALTERID", "NAME"))
            or f"page_{start}"
        )
        if page_id in seen_page_starts:
            break
        seen_page_starts.add(page_id)

        if first_root is None:
            first_resp_xml = resp_xml
            first_root = root
            collection_node = coll_elem
        else:
            if collection_node is not None:
                for r in records:
                    collection_node.append(r)

        if len(records) < batch_size:
            break

        start += batch_size

    if first_root is not None:
        return ET.tostring(first_root, encoding="utf-8").decode("utf-8")
    return first_resp_xml or fetch_tally_xml(host, port, builder_fn(*args, **kwargs), timeout=timeout)


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


_MONTH_ABBR: dict[str, str] = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04",
    "may": "05", "jun": "06", "jul": "07", "aug": "08",
    "sep": "09", "oct": "10", "nov": "11", "dec": "12",
}


def _normalize_date(raw: str) -> str | None:
    """Normalise a Tally date string to YYYY-MM-DD.

    Handles:
      - YYYYMMDD        (20260401)
      - YYYY-MM-DD      (already ISO)
      - D-Mon-YY / DD-Mon-YYYY  (1-Apr-26, 01-Apr-2026) — Tally default
      - D/M/YY, D.M.YY, D-M-YY (numeric separators)

    Month names use an explicit abbreviation lookup (case-insensitive) so
    behaviour is identical regardless of the Python locale or platform.
    """
    s = (raw or "").strip()
    if not s:
        return None

    # YYYYMMDD
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"

    # Already ISO: YYYY-MM-DD[…]
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]

    # Split on any of the common Tally separators: - / .
    for sep in ("-", "/", "."):
        parts = s.split(sep)
        if len(parts) != 3 or not all(parts):
            continue
        d_raw, m_raw, y_raw = parts[0], parts[1], parts[2]

        # Resolve month: numeric or 3-letter abbreviation.
        m_lower = m_raw.lower()
        if m_lower in _MONTH_ABBR:
            # Month-name format: D-Mon-YY or D-Mon-YYYY
            m = _MONTH_ABBR[m_lower]
        elif m_raw.isdigit():
            m = m_raw.zfill(2)
        else:
            continue  # unrecognised month token

        d = d_raw.zfill(2)
        y = y_raw
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

    Tally's Bills Payable export is FLAT: each bill is a <BILLFIXED> block
    (containing BILLDATE/BILLREF/BILLPARTY) immediately followed by sibling
    <BILLCL> (pending amount), <BILLDUE>, <BILLOVERDUE> elements — NOT nested
    inside BILLFIXED. A bill record is assembled by walking siblings in document
    order via a dedicated flat-sibling pass.

    A first pass handles alternate nested-schema Tally exports (e.g. TDL
    customisations with BILLWISEDETAILS.LIST containers). If that pass finds
    records whose amounts are all None, the flat-sibling pass takes over.

    ``amount`` is remaining due (pending), never amount paid.
    """
    root = _parse_root(xml_text)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()

    # ── Pass 1: nested-schema / other Tally variants ───────────────────────
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

        # Skip container nodes that hold child bill containers — they are
        # grouping wrappers, not individual bill records.
        child_bill_containers = [
            c for c in list(el) if _local(c.tag).upper() in bill_tags
        ]
        if child_bill_containers and tag.endswith(".LIST"):
            continue

        # Use _find_direct_text so we only look at direct children of this
        # element, not descendants that belong to a sibling bill block.
        amount = None
        for name in ("AMOUNT", "CLOSINGBALANCE", "BILLAMOUNT", "PENDINGAMOUNT"):
            amount = _parse_amount(_find_direct_text(el, (name,)))
            if amount is not None:
                break

        bill_date = _normalize_date(
            _find_direct_text(el, ("BILLDATE", "DATE", "VOUCHERDATE", "INVOICEDATE"))
        )
        party = (
            _find_direct_text(el, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
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

    # Fallback: bare BILLNAME scan for very sparse exports.
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

    # ── Pass 2: flat-sibling walk (canonical Bills Payable format) ─────────
    # Tally's standard Bills Payable XML is FLAT: <BILLFIXED> is immediately
    # followed by sibling <BILLCL> — NOT nested inside BILLFIXED — so Pass 1
    # (which uses _find_direct_text on the BILLFIXED element) cannot see the
    # amount. When Pass 1 found records but every amount is None, rebuild from
    # the flat structure instead.
    if records and all(r["amount"] is None for r in records):
        records.clear()
        seen.clear()

        def _flush_flat(cur: dict[str, Any] | None) -> None:
            if cur is None or not cur.get("bill_ref"):
                return
            rec = {
                "party": cur.get("party") or "",
                "bill_ref": cur["bill_ref"],
                "bill_date": cur.get("bill_date"),
                "amount": cur.get("amount"),
            }
            key = (
                rec["party"], rec["bill_ref"], rec["bill_date"] or "",
                "" if rec["amount"] is None else f"{rec['amount']:.2f}",
            )
            if key not in seen:
                seen.add(key)
                records.append(rec)

        # Locate the parent whose direct children include BILLFIXED blocks.
        flat_elements: list[ET.Element] = []
        for parent in root.iter():
            children = list(parent)
            if any(_local(c.tag).upper() == "BILLFIXED" for c in children):
                flat_elements = children
                break

        current_flat: dict[str, Any] | None = None
        for el in flat_elements:
            tag = _local(el.tag).upper()
            if tag == "BILLFIXED":
                _flush_flat(current_flat)
                current_flat = {
                    "bill_ref": _find_text(
                        el, ("BILLREF", "BILLNAME", "NAME", "BILLREFERENCENUMBER")
                    ),
                    "party": _find_text(
                        el, ("BILLPARTY", "PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME")
                    ),
                    "bill_date": _normalize_date(
                        _find_text(el, ("BILLDATE", "DATE", "VOUCHERDATE", "INVOICEDATE"))
                    ),
                    "amount": None,
                }
                continue
            if current_flat is None:
                continue
            if tag in ("BILLCL", "AMOUNT", "CLOSINGBALANCE", "BILLAMOUNT", "PENDINGAMOUNT"):
                amt = _parse_amount(_text(el))
                if amt is not None and current_flat.get("amount") is None:
                    current_flat["amount"] = abs(amt)
        _flush_flat(current_flat)

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

        guid = (
            _find_direct_text(voucher, ("GUID",))
            or _find_text(voucher, ("GUID",))
            or ""
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
                    "guid": guid,
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


def _is_voucher_cancelled_or_deleted(voucher) -> bool:
    """Check if a Tally voucher is marked as cancelled or deleted."""
    action = (voucher.attrib.get("ACTION") or "").strip().lower()
    if action in {"cancel", "delete"}:
        return True
    is_cancelled = (
        _find_direct_text(voucher, ("ISCANCELLED",))
        or _find_text(voucher, ("ISCANCELLED",))
        or ""
    ).strip().lower()
    if is_cancelled in {"yes", "true", "1"}:
        return True
    is_deleted = (
        _find_direct_text(voucher, ("ISDELETED", "ISDELETEDVCHRETAINED"))
        or _find_text(voucher, ("ISDELETED", "ISDELETEDVCHRETAINED"))
        or ""
    ).strip().lower()
    if is_deleted in {"yes", "true", "1"}:
        return True
    return False


def parse_purchase_register_records(xml_text: str) -> list:
    """Parse Day Book XML into Purchase Register rows.

    Source is the same Day Book fetch used by parse_payment_records() —
    the dedicated "Purchase Register" report returns monthly summary
    totals, not itemized vouchers, so it is the wrong source.
    """
    root = _parse_root(xml_text)
    records = []
    seen = set()

    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue

        is_cancelled = _is_voucher_cancelled_or_deleted(voucher)
        guid = (
            _find_direct_text(voucher, ("GUID",))
            or _find_text(voucher, ("GUID",))
            or ""
        )

        voucher_date = _normalize_date(
            _find_direct_text(voucher, ("REFERENCEDATE",))
            or _find_text(voucher, ("REFERENCEDATE",))
            or _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("REFERENCE",))
            or _find_text(voucher, ("REFERENCE",))
            or _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
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
            "Is Cancelled": is_cancelled,
            "Voucher GUID": guid,
        }
        key = (rec["Inv No."], rec["GSTIN/UIN"])
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)

    return records


def parse_sales_register_records(xml_text: str) -> list:
    """Parse Day Book XML into Sales Register rows."""
    root = _parse_root(xml_text)
    records = []
    seen = set()

    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue

        is_cancelled = _is_voucher_cancelled_or_deleted(voucher)
        guid = (
            _find_direct_text(voucher, ("GUID",))
            or _find_text(voucher, ("GUID",))
            or ""
        )

        voucher_date = _normalize_date(
            _find_direct_text(voucher, ("REFERENCEDATE",))
            or _find_text(voucher, ("REFERENCEDATE",))
            or _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("REFERENCE",))
            or _find_text(voucher, ("REFERENCE",))
            or _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
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

        items = []
        for entry in voucher.iter():
            etag = _local(entry.tag).upper()
            if etag in {"ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST", "INVENTORYENTRY"}:
                stock_item = (
                    _find_direct_text(entry, ("STOCKITEMNAME", "STOCKITEM"))
                    or _find_text(entry, ("STOCKITEMNAME", "STOCKITEM"))
                    or ""
                )
                hsn = (
                    _find_direct_text(entry, ("HSNCODE", "HSNSACCODE", "GSTHSNNAME"))
                    or _find_text(entry, ("HSNCODE", "HSNSACCODE", "GSTHSNNAME"))
                    or ""
                )
                qty = (
                    _find_direct_text(entry, ("BILLEDQTY", "ACTUALQTY", "QTY"))
                    or _find_text(entry, ("BILLEDQTY", "ACTUALQTY", "QTY"))
                    or ""
                )
                rate = (
                    _find_direct_text(entry, ("RATE",))
                    or _find_text(entry, ("RATE",))
                    or ""
                )
                amt = _parse_amount(
                    _find_direct_text(entry, ("AMOUNT",)) or _find_text(entry, ("AMOUNT",))
                )
                if stock_item or amt is not None:
                    items.append({
                        "stock_item": stock_item,
                        "hsn": hsn,
                        "qty": qty,
                        "rate": rate,
                        "amount": f"{abs(amt):.2f}" if amt is not None else "0.00",
                    })

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
            "Items": items,
            "Is Cancelled": is_cancelled,
            "Voucher GUID": guid,
        }
        key = (rec["Inv No."], rec["GSTIN/UIN"])
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)

    return records


def parse_credit_debit_note_records(xml_text: str) -> list:
    """Parse Day Book XML into Credit Note / Debit Note (CDNR) rows."""
    root = _parse_root(xml_text)
    records = []
    seen = set()

    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue

        is_cancelled = _is_voucher_cancelled_or_deleted(voucher)
        guid = (
            _find_direct_text(voucher, ("GUID",))
            or _find_text(voucher, ("GUID",))
            or ""
        )

        vtype = (
            _find_direct_text(voucher, ("VOUCHERTYPENAME", "VOUCHERTYPE"))
            or _find_text(voucher, ("VOUCHERTYPENAME", "VOUCHERTYPE"))
            or ""
        )

        voucher_date = _normalize_date(
            _find_direct_text(voucher, ("REFERENCEDATE",))
            or _find_text(voucher, ("REFERENCEDATE",))
            or _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("REFERENCE",))
            or _find_text(voucher, ("REFERENCE",))
            or _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER"))
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
            "voucher_type": vtype,
            "GSTIN/UIN": party_gstin or "",
            "Party's A/c Name": party or "",
            "Note No.": voucher_number or "",
            "Note Date": voucher_date or "",
            "Taxable Amt": f"{taxable_amt:.2f}",
            "IGST Amt": f"{igst_amt:.2f}",
            "CGST Amt": f"{cgst_amt:.2f}",
            "SGST Amt": f"{sgst_amt:.2f}",
            "Gross Total": f"{gross_total:.2f}",
            "Is Cancelled": is_cancelled,
            "Voucher GUID": guid,
        }
        key = (rec["Note No."], rec["GSTIN/UIN"], rec["voucher_type"])
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)

    return records



_GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra & Nagar Haveli and Daman & Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}

_NON_PARTY_NAMES: set[str] = {
    "CASH",
    "PROFIT & LOSS A/C",
    "PROFIT AND LOSS A/C",
    "SUNDRY CREDITORS",
    "SUNDRY DEBTORS",
    "CASH-IN-HAND",
    "BANK ACCOUNTS",
}


def parse_ledger_master_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse Ledger Master XML into structured party ledger records.

    Extracts name, parent_group, gstin, state, opening_balance, closing_balance.
    Filters out system ledgers and root group header ledgers.
    """
    root = _parse_root(xml_text)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for el in root.iter():
        if _local(el.tag).upper() != "LEDGER":
            continue

        name = (el.attrib.get("NAME") or "").strip()
        if not name:
            name = _find_direct_text(el, ("MAILINGNAME", "NAME")) or _find_text(el, ("MAILINGNAME",))
        if not name:
            continue

        name_upper = name.upper()
        if name_upper in _NON_PARTY_NAMES:
            continue

        parent_group = _find_direct_text(el, ("PARENT",)) or _find_text(el, ("PARENT",))

        # GSTIN lives in LEDGSTREGDETAILS.LIST -> GSTIN in TallyPrime 3.x+
        gst_details = el.find("LEDGSTREGDETAILS.LIST")
        gstin = _find_direct_text(gst_details, ("GSTIN",)) if gst_details is not None else ""
        if not gstin:
            gstin = _find_direct_text(el, ("GSTIN", "PARTYGSTIN")) or _find_text(el, ("GSTIN", "PARTYGSTIN"))

        # State extraction priority:
        # 1. LEDGSTREGDETAILS.LIST > STATE
        # 2. LEDMAILINGDETAILS.LIST > STATE
        # 3. Top-level STATENAME
        state_gst = _find_direct_text(gst_details, ("STATE",)) if gst_details is not None else ""

        mailing_details = el.find("LEDMAILINGDETAILS.LIST")
        state_mailing = _find_direct_text(mailing_details, ("STATE",)) if mailing_details is not None else ""

        state_top = _find_direct_text(el, ("STATENAME", "LEDSTATENAME", "STATE"))

        state = state_gst or state_mailing or state_top

        if not state and len(gstin) >= 2:
            state = _GST_STATE_CODES.get(gstin[:2], "")

        opening_balance = _parse_amount(_find_direct_text(el, ("OPENINGBALANCE",)))
        closing_balance = _parse_amount(_find_direct_text(el, ("CLOSINGBALANCE",)))

        rec = {
            "name": name,
            "parent_group": parent_group or "",
            "gstin": gstin or "",
            "state": state or "",
            "opening_balance": abs(opening_balance) if opening_balance is not None else None,
            "closing_balance": abs(closing_balance) if closing_balance is not None else None,
        }

        if rec["name"] in seen:
            continue
        seen.add(rec["name"])
        records.append(rec)

    return records


def parse_stock_master_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse TDL StockItem Collection XML into canonical stock master records."""
    if not xml_text:
        return []
    try:
        root = _parse_root(xml_text)
    except ET.ParseError:
        return []

    records = []
    seen = set()
    for elem in root.iter():
        if _local(elem.tag).upper() != "STOCKITEM":
            continue
        name = (
            _find_direct_text(elem, ("NAME", "STOCKITEMNAME"))
            or _find_text(elem, ("NAME", "STOCKITEMNAME"))
            or (elem.attrib.get("NAME") or "").strip()
        )
        if not name or name in seen:
            continue
        seen.add(name)

        parent = (
            _find_direct_text(elem, ("PARENT", "STOCKGROUPNAME"))
            or _find_text(elem, ("PARENT", "STOCKGROUPNAME"))
            or ""
        )
        category = (
            _find_direct_text(elem, ("CATEGORY", "STOCKCATEGORYNAME"))
            or _find_text(elem, ("CATEGORY", "STOCKCATEGORYNAME"))
            or ""
        )
        hsn = (
            _find_direct_text(elem, ("HSNCODE", "HSNSACCODE", "GSTHSNNAME"))
            or _find_text(elem, ("HSNCODE", "HSNSACCODE", "GSTHSNNAME"))
            or ""
        )
        unit = (
            _find_direct_text(elem, ("BASEUNITS", "UNITS", "UNIT"))
            or _find_text(elem, ("BASEUNITS", "UNITS", "UNIT"))
            or ""
        )
        op_bal = _find_direct_text(elem, ("OPENINGBALANCE",)) or _find_text(elem, ("OPENINGBALANCE",))
        cl_bal = _find_direct_text(elem, ("CLOSINGBALANCE",)) or _find_text(elem, ("CLOSINGBALANCE",))
        alter_id = _find_direct_text(elem, ("ALTERID",)) or _find_text(elem, ("ALTERID",))

        records.append({
            "name": name,
            "parent_group": parent,
            "category": category,
            "hsn_code": hsn,
            "base_unit": unit,
            "opening_balance": op_bal or "",
            "closing_balance": cl_bal or "",
            "alter_id": int(alter_id) if alter_id and alter_id.isdigit() else None,
        })
    return records


def parse_cost_centre_master_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse TDL CostCentre Collection XML into canonical rows."""
    if not xml_text:
        return []
    try:
        root = _parse_root(xml_text)
    except ET.ParseError:
        return []

    records = []
    seen = set()
    for elem in root.iter():
        if _local(elem.tag).upper() != "COSTCENTRE":
            continue
        name = (
            _find_direct_text(elem, ("NAME", "COSTCENTRENAME"))
            or _find_text(elem, ("NAME", "COSTCENTRENAME"))
            or (elem.attrib.get("NAME") or "").strip()
        )
        if not name or name in seen:
            continue
        seen.add(name)

        category = (
            _find_direct_text(elem, ("CATEGORY", "COSTCATEGORY"))
            or _find_text(elem, ("CATEGORY", "COSTCATEGORY"))
            or ""
        )
        parent = (
            _find_direct_text(elem, ("PARENT",))
            or _find_text(elem, ("PARENT",))
            or ""
        )
        alter_id = _find_direct_text(elem, ("ALTERID",)) or _find_text(elem, ("ALTERID",))

        records.append({
            "name": name,
            "category": category,
            "parent": parent,
            "alter_id": int(alter_id) if alter_id and alter_id.isdigit() else None,
        })
    return records


def parse_receipt_journal_contra_records(xml_text: str) -> list[dict[str, Any]]:
    """Parse TDL Receipt/Journal/Contra Collection XML into canonical rows."""
    if not xml_text:
        return []
    try:
        root = _parse_root(xml_text)
    except ET.ParseError:
        return []

    records = []
    seen = set()
    for voucher in root.iter():
        if _local(voucher.tag).upper() != "VOUCHER":
            continue

        is_cancelled = _is_voucher_cancelled_or_deleted(voucher)
        vtype = (
            _find_direct_text(voucher, ("VOUCHERTYPENAME", "VOUCHERTYPE"))
            or _find_text(voucher, ("VOUCHERTYPENAME", "VOUCHERTYPE"))
            or ""
        )
        voucher_date = _normalize_date(
            _find_direct_text(voucher, ("DATE", "VOUCHERDATE"))
            or _find_text(voucher, ("DATE", "VOUCHERDATE"))
        )
        voucher_number = (
            _find_direct_text(voucher, ("VOUCHERNUMBER", "NUMBER", "REFERENCE"))
            or _find_text(voucher, ("VOUCHERNUMBER", "NUMBER", "REFERENCE"))
        )
        party = (
            _find_direct_text(voucher, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
            or _find_text(voucher, ("PARTYLEDGERNAME", "PARTYNAME", "LEDGERNAME"))
        )
        guid = (
            _find_direct_text(voucher, ("GUID",))
            or _find_text(voucher, ("GUID",))
            or ""
        )

        entries = []
        total_amt = 0.0
        for entry in voucher.iter():
            etag = _local(entry.tag).upper()
            if etag not in {"ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST", "LEDGERENTRY"}:
                continue
            lname = (
                _find_direct_text(entry, ("LEDGERNAME",))
                or _find_text(entry, ("LEDGERNAME",))
            )
            amt = _parse_amount(
                _find_direct_text(entry, ("AMOUNT",)) or _find_text(entry, ("AMOUNT",))
            )
            if lname and amt is not None:
                entries.append({"ledger_name": lname, "amount": f"{abs(amt):.2f}"})
                total_amt += abs(amt)

        rec = {
            "voucher_type": vtype,
            "voucher_number": voucher_number or "",
            "voucher_date": voucher_date or "",
            "party_name": party or "",
            "total_amount": f"{(total_amt / 2.0):.2f}" if total_amt > 0 else "0.00",
            "is_cancelled": is_cancelled,
            "guid": guid,
            "entries": entries,
        }
        key = (rec["voucher_number"], rec["voucher_type"], rec["voucher_date"])
        if key in seen:
            continue
        seen.add(key)
        records.append(rec)
    return records





def _post_with_retry(
    endpoint: str,
    headers: dict[str, str],
    payload: bytes,
    timeout: float = 60.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    idempotency_key = hashlib.sha256(payload).hexdigest()
    req_headers = dict(headers)
    req_headers["Idempotency-Key"] = idempotency_key

    last_exc = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            endpoint,
            data=payload,
            method="POST",
            headers=req_headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {"raw": body}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2.0 ** (attempt + 1)
                logging.getLogger("tally_bridge").warning(
                    "ReconDesk push to %s failed (attempt %d/%d): %s. Retrying in %.1fs…",
                    endpoint,
                    attempt + 1,
                    max_retries,
                    exc,
                    backoff,
                )
                time.sleep(backoff)

    if last_exc:
        raise last_exc
    return {}


def push_sync_payload(
    endpoint: str,
    api_key: str,
    company_name: str,
    outstanding: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    ledgers: list[dict[str, Any]] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    payload_dict = {
        "company_name": company_name,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "outstanding": outstanding,
        "payments": payments,
    }
    if ledgers is not None:
        payload_dict["ledgers"] = ledgers
    payload = json.dumps(payload_dict).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return _post_with_retry(endpoint, headers, payload, timeout=timeout)


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
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return _post_with_retry(endpoint, headers, payload, timeout=timeout)


def push_sales_register_payload(
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
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    return _post_with_retry(endpoint, headers, payload, timeout=timeout)


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


def parse_max_alter_id(xml_text: str) -> int:
    """Parse maximum ALTERID from a Tally XML response envelope."""
    if not xml_text:
        return 0
    try:
        root = _parse_root(xml_text)
    except Exception:
        return 0
    max_id = 0
    for elem in root.iter():
        if _local(elem.tag).upper() in {"ALTERID", "MASTERID"}:
            val = (elem.text or "").strip()
            if val.isdigit():
                max_id = max(max_id, int(val))
    return max_id


def run_once(
    cfg: dict[str, Any],
    logger: logging.Logger,
    *,
    test_mode: bool,
    out_dir: Path,
    config_file: Path | None = None,
) -> int:
    host = cfg["tally_host"]
    port = int(cfg["tally_port"])
    company_cfg = cfg.get("company_name", "")
    lookback = int(cfg.get("lookback_days", 200))
    min_alter_id = cfg.get("last_alter_id")
    if min_alter_id is not None:
        try:
            min_alter_id = int(min_alter_id)
        except (ValueError, TypeError):
            min_alter_id = None

    from_ymd, to_ymd = _lookback_window(lookback)

    open_companies = []
    try:
        companies_xml = fetch_tally_xml(host, port, build_open_companies_xml(), timeout=30.0)
        open_companies = parse_open_companies_records(companies_xml)
        if open_companies:
            comp_names = [c["name"] for c in open_companies]
            logger.info("Auto-discovered %d open Tally company(ies): %s", len(open_companies), comp_names)
    except Exception as exc:
        logger.warning("Auto-discovery of open companies failed: %s", exc)

    target_companies = (
        [c["name"] for c in open_companies]
        if (company_cfg.lower() in ("", "auto", "all") and open_companies)
        else [company_cfg]
    )

    for company in target_companies:
        logger.info(
            "Syncing Tally company=%r at %s:%s (min_alter_id=%s)",
            company,
            host,
            port,
            min_alter_id,
        )
        try:
            outstanding_xml = fetch_tally_xml(
                host, port, build_bills_payable_xml(company), timeout=120.0
            )
        except ConnectionError as exc:
            logger.error("%s", exc)
            return 2

        logger.info(
            "Fetching Day Book payments %s→%s (lookback_days=%s, min_alter_id=%s)",
            from_ymd,
            to_ymd,
            lookback,
            min_alter_id,
        )
        try:
            payments_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_daybook_payments_xml,
                company,
                from_ymd,
                to_ymd,
                min_alter_id=min_alter_id,
                batch_size=1000,
                timeout=120.0,
            )
        except ConnectionError as exc:
            logger.error("%s", exc)
            return 2

        logger.info("Fetching Ledger Master from Tally at %s:%s (company=%r)", host, port, company)
        try:
            ledgers_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_ledger_master_xml,
                company,
                min_alter_id=min_alter_id,
                batch_size=1000,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Ledger Master: %s", exc)
            ledgers_xml = ""

        logger.info(
            "Fetching Sales Register %s→%s (lookback_days=%s, min_alter_id=%s)",
            from_ymd,
            to_ymd,
            lookback,
            min_alter_id,
        )
        try:
            sales_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_sales_register_xml,
                company,
                from_ymd,
                to_ymd,
                min_alter_id=min_alter_id,
                batch_size=1000,
                timeout=120.0,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Sales Register: %s", exc)
            sales_xml = ""

        logger.info(
            "Fetching Credit/Debit Notes %s→%s (lookback_days=%s, min_alter_id=%s)",
            from_ymd,
            to_ymd,
            lookback,
            min_alter_id,
        )
        try:
            cdn_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_credit_debit_notes_xml,
                company,
                from_ymd,
                to_ymd,
                min_alter_id=min_alter_id,
                batch_size=1000,
                timeout=120.0,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Credit/Debit Notes: %s", exc)
            cdn_xml = ""

        logger.info("Fetching Stock Master from Tally at %s:%s (company=%r)", host, port, company)
        try:
            stock_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_stock_master_xml,
                company,
                min_alter_id=min_alter_id,
                batch_size=1000,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Stock Master: %s", exc)
            stock_xml = ""

        logger.info(
            "Fetching Receipt/Journal/Contra %s→%s (lookback_days=%s, min_alter_id=%s)",
            from_ymd,
            to_ymd,
            lookback,
            min_alter_id,
        )
        try:
            rjc_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_receipt_journal_contra_xml,
                company,
                from_ymd,
                to_ymd,
                min_alter_id=min_alter_id,
                batch_size=1000,
                timeout=120.0,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Receipt/Journal/Contra: %s", exc)
            rjc_xml = ""

        logger.info("Fetching Cost Centre Master from Tally at %s:%s (company=%r)", host, port, company)
        try:
            cost_centres_xml = fetch_tally_xml_paginated(
                host,
                port,
                build_cost_centre_master_xml,
                company,
                min_alter_id=min_alter_id,
                batch_size=1000,
            )
        except ConnectionError as exc:
            logger.error("Failed to fetch Cost Centre Master: %s", exc)
            cost_centres_xml = ""

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outstanding_path = out_dir / f"tally_bills_payable_{stamp}.xml"
    payments_path = out_dir / f"tally_daybook_payments_{stamp}.xml"
    ledgers_path = out_dir / f"tally_ledger_master_{stamp}.xml"
    stock_path = out_dir / f"tally_stock_master_{stamp}.xml"
    sales_path = out_dir / f"tally_sales_register_{stamp}.xml"
    cdn_path = out_dir / f"tally_cdn_notes_{stamp}.xml"
    rjc_path = out_dir / f"tally_rjc_vouchers_{stamp}.xml"
    outstanding_path.write_text(outstanding_xml, encoding="utf-8")
    payments_path.write_text(payments_xml, encoding="utf-8")
    if ledgers_xml:
        ledgers_path.write_text(ledgers_xml, encoding="utf-8")
    if stock_xml:
        stock_path.write_text(stock_xml, encoding="utf-8")
    if sales_xml:
        sales_path.write_text(sales_xml, encoding="utf-8")
    if cdn_xml:
        cdn_path.write_text(cdn_xml, encoding="utf-8")
    if rjc_xml:
        rjc_path.write_text(rjc_xml, encoding="utf-8")

    outstanding_bytes = len(outstanding_xml.encode("utf-8"))
    payments_bytes = len(payments_xml.encode("utf-8"))
    ledgers_bytes = len(ledgers_xml.encode("utf-8")) if ledgers_xml else 0
    sales_bytes = len(sales_xml.encode("utf-8")) if sales_xml else 0
    cdn_bytes = len(cdn_xml.encode("utf-8")) if cdn_xml else 0
    logger.info(
        "Saved raw XML → %s (%d bytes), %s (%d bytes), %s (%d bytes), %s (%d bytes), %s (%d bytes)",
        outstanding_path,
        outstanding_bytes,
        payments_path,
        payments_bytes,
        ledgers_path,
        ledgers_bytes,
        sales_path,
        sales_bytes,
        cdn_path,
        cdn_bytes,
    )

    try:
        outstanding = parse_outstanding_records(outstanding_xml)
        payments = parse_payment_records(payments_xml)
        ledgers = parse_ledger_master_records(ledgers_xml) if ledgers_xml else []
    except ET.ParseError as exc:
        logger.error("Failed to parse Tally XML: %s", exc)
        return 3

    purchase_rows = parse_purchase_register_records(payments_xml)
    purchase_by_period = _group_purchase_rows_by_period(purchase_rows)

    unattached = purchase_by_period.pop("", [])
    if unattached:
        logger.warning(
            "%d purchase row(s) had no parseable Inv Date — skipped, not pushed",
            len(unattached),
        )

    logger.info(
        "Purchase Register → %d row(s) across %d period(s): %s",
        len(purchase_rows), len(purchase_by_period), sorted(purchase_by_period.keys()),
    )

    pr_parsed_path = out_dir / f"tally_purchase_register_parsed_{stamp}.json"
    pr_parsed_path.write_text(
        json.dumps(purchase_by_period, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved purchase register rows → %s", pr_parsed_path)

    sales_rows = parse_sales_register_records(sales_xml) if sales_xml else []
    sales_by_period = _group_purchase_rows_by_period(sales_rows)
    unattached_sales = sales_by_period.pop("", [])
    if unattached_sales:
        logger.warning(
            "%d sales row(s) had no parseable Inv Date — skipped",
            len(unattached_sales),
        )

    logger.info(
        "Sales Register → %d row(s) across %d period(s): %s",
        len(sales_rows), len(sales_by_period), sorted(sales_by_period.keys()),
    )

    sr_parsed_path = out_dir / f"tally_sales_register_parsed_{stamp}.json"
    sr_parsed_path.write_text(
        json.dumps(sales_by_period, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved sales register rows → %s", sr_parsed_path)

    cdn_rows = parse_credit_debit_note_records(cdn_xml) if cdn_xml else []
    cdn_by_period = _group_purchase_rows_by_period(cdn_rows)
    cdn_parsed_path = out_dir / f"tally_cdn_notes_parsed_{stamp}.json"
    cdn_parsed_path.write_text(
        json.dumps(cdn_by_period, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved credit/debit note rows → %s", cdn_parsed_path)

    stock_items = parse_stock_master_records(stock_xml) if stock_xml else []
    stock_parsed_path = out_dir / f"tally_stock_master_parsed_{stamp}.json"
    stock_parsed_path.write_text(
        json.dumps(stock_items, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved stock master rows → %s", stock_parsed_path)

    rjc_rows = parse_receipt_journal_contra_records(rjc_xml) if rjc_xml else []
    rjc_parsed_path = out_dir / f"tally_rjc_vouchers_parsed_{stamp}.json"
    rjc_parsed_path.write_text(
        json.dumps(rjc_rows, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved receipt/journal/contra rows → %s", rjc_parsed_path)

    cost_centres = parse_cost_centre_master_records(cost_centres_xml) if cost_centres_xml else []
    cc_parsed_path = out_dir / f"tally_cost_centre_master_parsed_{stamp}.json"
    cc_parsed_path.write_text(
        json.dumps(cost_centres, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info("Saved cost centre master rows → %s", cc_parsed_path)

    outstanding_n = len(outstanding)
    payments_n = len(payments)
    ledgers_n = len(ledgers)
    stock_n = len(stock_items)
    cc_n = len(cost_centres)
    sales_n = len(sales_rows)
    cdn_n = len(cdn_rows)
    rjc_n = len(rjc_rows)
    logger.info(
        "Export summary: Bills Payable → %d outstanding row(s) (%d raw bytes); "
        "Day Book Payment Agst Ref → %d payment row(s) (%d raw bytes); "
        "Ledger Master → %d record(s) (%d raw bytes); "
        "Stock Master → %d record(s); "
        "Cost Centre Master → %d record(s); "
        "Sales Register → %d row(s) (%d raw bytes); "
        "Credit/Debit Notes → %d row(s) (%d raw bytes); "
        "Receipt/Journal/Contra → %d row(s)",
        outstanding_n,
        outstanding_bytes,
        payments_n,
        payments_bytes,
        ledgers_n,
        ledgers_bytes,
        stock_n,
        cc_n,
        sales_n,
        sales_bytes,
        cdn_n,
        cdn_bytes,
        rjc_n,
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
            {"outstanding": outstanding, "payments": payments, "ledgers": ledgers},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.info("Saved parsed payload → %s", parsed_path)

    max_alter = max(
        parse_max_alter_id(outstanding_xml),
        parse_max_alter_id(payments_xml),
        parse_max_alter_id(ledgers_xml),
        parse_max_alter_id(sales_xml),
        parse_max_alter_id(cdn_xml),
    )
    if max_alter > 0 and config_file and config_file.exists():
        try:
            cfg["last_alter_id"] = max_alter
            config_file.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
            logger.info("Updated last_alter_id=%d in config %s", max_alter, config_file)
        except Exception as exc:
            logger.warning("Failed updating last_alter_id in config: %s", exc)

    if test_mode:
        logger.info(
            "--test mode: parse complete; NOT pushing to ReconDesk. "
            "Bills Payable = unpaid check only; Payment Agst Ref = settle evidence."
        )
        print("")
        print("=== Tally Bridge --test summary ===")
        print(f"Bills Payable:     {outstanding_n} outstanding row(s)  [{outstanding_path.name}]")
        print(f"Day Book Payments: {payments_n} Agst Ref payment row(s)  [{payments_path.name}]")
        print(f"Ledger Master:     {ledgers_n} record(s)  [{ledgers_path.name}]")
        print(f"Sales Register:    {sales_n} row(s) across {len(sales_by_period)} period(s) {sorted(sales_by_period.keys())}  [{sales_path.name}]")
        if outstanding_n == 0 or payments_n == 0:
            print("WARNING: one or both exports returned zero parsed rows — do not enable push until fixed.")
        print(f"Parsed JSON:       {parsed_path.name}")
        print("--- Bills Payable XML preview (first 2k) ---")
        print(outstanding_xml[:2000] or "(empty)")
        print("--- Day Book payments XML preview (first 2k) ---")
        print(payments_xml[:2000] or "(empty)")
        print(f"Purchase Register:  {len(purchase_rows)} row(s) across "
              f"{len(purchase_by_period)} period(s)  {sorted(purchase_by_period.keys())}  [from Day Book]")
        print(f"Sales Register:     {len(sales_rows)} row(s) across "
              f"{len(sales_by_period)} period(s)  {sorted(sales_by_period.keys())}  [from Sales Vouchers]")
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
            ledgers=ledgers,
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
        logger.warning("client_gstin_id not set in config — skipping purchase/sales register push")
    else:
        if cfg.get("pr_sync_endpoint"):
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

        if cfg.get("sr_sync_endpoint"):
            for period, period_rows in sales_by_period.items():
                try:
                    sr_result = push_sales_register_payload(
                        cfg["sr_sync_endpoint"],
                        cfg["api_key"],
                        cfg["client_gstin_id"],
                        period,
                        company,
                        period_rows,
                    )
                    logger.info("Sales register push OK for %s: %s", period, sr_result)
                except urllib.error.HTTPError as exc:
                    detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                    logger.error("Sales register push failed for %s HTTP %s: %s",
                                 period, exc.code, detail or exc.reason)
                except urllib.error.URLError as exc:
                    logger.error("Sales register push failed for %s: %s", period, exc)

    return 0


def fetch_ledgers_only(cfg: dict[str, Any], logger: logging.Logger, out_dir: Path) -> int:
    host = cfg["tally_host"]
    port = int(cfg["tally_port"])
    company = cfg["company_name"]
    logger.info("Fetching Ledger Master from Tally at %s:%s (company=%r)", host, port, company)
    try:
        xml_text = fetch_tally_xml(host, port, build_ledger_master_xml(company))
    except ConnectionError as exc:
        logger.error("%s", exc)
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"tally_ledger_master_{stamp}.xml"
    out_path.write_text(xml_text, encoding="utf-8")
    logger.info("Saved raw Ledger Master XML → %s (%d bytes)", out_path, len(xml_text.encode("utf-8")))

    records = parse_ledger_master_records(xml_text)
    logger.info("Parsed %d ledger master record(s)", len(records))

    print("\n=== Parsed Ledger Master Records ===")
    print(json.dumps(records, indent=2, ensure_ascii=False))
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
        "--ledgers",
        action="store_true",
        help="Fetch and print raw Ledger Master XML from Tally then exit",
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

    if args.ledgers:
        return fetch_ledgers_only(cfg, logger, out_dir)

    once = args.once or args.test
    if once:
        return run_once(cfg, logger, test_mode=args.test, out_dir=out_dir, config_file=config_path)

    interval = int(cfg["sync_interval_minutes"]) * 60
    logger.info("Starting timer loop every %s minute(s)", cfg["sync_interval_minutes"])
    while True:
        code = run_once(cfg, logger, test_mode=False, out_dir=out_dir, config_file=config_path)
        if code != 0:
            logger.warning("Sync finished with code %s; will retry after interval", code)
        logger.info("Sleeping %s seconds…", interval)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
