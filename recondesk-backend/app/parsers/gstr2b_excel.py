"""GSTR-2B Excel adapter for third-party flat exports (invoice / note sheets).

Reads ``.xls`` / ``.xlsx`` workbooks whose tabs match the alt JSON schema
(``invoice``, ``note``, …), reuses Purchase Register header-row detection, and
hands the resulting row dicts to ``normalize_alt_2b_schema``.

ISD / IMPG-like sheet tabs are detected (row-counted) but not parsed — counts
are attached so ``parse_gstr2b`` can warn the CA.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from typing import Any

import pandas as pd

from app.parsers.gstr2b_parser import (
    _GSTIN_IN_TEXT_RE,
    _UNPARSED_IMPG_COUNT_KEY,
    _UNPARSED_ISD_COUNT_KEY,
    _alt_invoice_date_portal,
    _alt_parse_period_to_rtnprd,
    _alt_row_get,
    normalize_alt_2b_schema,
)
from app.parsers.purchase_register_parser import (
    _find_best_header_from_raw,
    normalize_header,
)

logger = logging.getLogger(__name__)

_EXCEL_EXTS = frozenset({".xls", ".xlsx"})

# Sheet tabs we import (IMS tabs ignored for now — same as alt JSON path).
_INVOICE_SHEET_NAMES = frozenset({"invoice", "invoices", "b2b"})
_NOTE_SHEET_NAMES = frozenset({"note", "notes", "cdn", "cdnr"})

# Unparsed section tabs — detect + count only.
_ISD_SHEET_COMPACT = frozenset({"isd", "isda"})
_IMPG_SHEET_COMPACT = frozenset({"impg", "impga", "impgsez", "impgseza"})


def is_gstr2b_excel_filename(filename: str | None) -> bool:
    if not filename:
        return False
    lower = filename.lower().strip()
    return any(lower.endswith(ext) for ext in _EXCEL_EXTS)


def is_gstr2b_excel_bytes(raw: bytes) -> bool:
    """True for OLE ``.xls`` or ZIP ``.xlsx`` magic (ignores extension)."""
    if not raw or len(raw) < 4:
        return False
    # ZIP / OOXML (.xlsx)
    if raw[:2] == b"PK":
        return True
    # OLE Compound Document (.xls)
    if raw[:4] == b"\xd0\xcf\x11\xe0":
        return True
    return False


def _sheet_kind(sheet_name: str) -> str | None:
    norm = normalize_header(str(sheet_name))
    compact = norm.replace(" ", "")
    if norm in _INVOICE_SHEET_NAMES or compact in _INVOICE_SHEET_NAMES:
        return "invoice"
    if norm in _NOTE_SHEET_NAMES or compact in _NOTE_SHEET_NAMES:
        return "note"
    # GSTN portal uses compound names: "B2B-CDNR", "B2B, Credit/Debit Notes",
    # "B2B, Credit/Debit Notes(Amendment)"
    if compact.startswith("b2b") and ("cdnr" in compact or "credit" in compact or "debit" in compact):
        return "note"
    # "B2BA" = B2B amendment — treat as invoice
    if compact in {"b2ba"}:
        return "invoice"
    # CDNRA = note amendment
    if compact in {"cdnra"}:
        return "note"
    # Plain "b2b" prefix without cdnr/credit/debit is an invoice sheet
    if compact.startswith("b2b"):
        return "invoice"
    return None


def _unparsed_sheet_kind(sheet_name: str) -> str | None:
    """Return ``isd`` / ``impg`` for unparsed section-like sheet names."""
    compact = normalize_header(str(sheet_name)).replace(" ", "")
    if not compact:
        return None
    if compact in _ISD_SHEET_COMPACT or compact.startswith("isd"):
        return "isd"
    if compact in _IMPG_SHEET_COMPACT or compact.startswith("impg"):
        return "impg"
    if "importofgoods" in compact or "importgoods" in compact:
        return "impg"
    return None


def _count_nonempty_sheet_rows(xl: pd.ExcelFile, sheet_name: str) -> int:
    """Count data rows on an unparsed sheet (header-aware when possible)."""
    try:
        rows, _gstin, _period, _hdr = _read_named_sheet(xl, sheet_name)
        if rows:
            return len(rows)
    except Exception as exc:
        logger.warning(
            "GSTR-2B Excel unparsed sheet %r header-read failed: %s",
            sheet_name,
            exc,
        )
    try:
        raw_df = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
    except Exception as exc:
        logger.warning(
            "GSTR-2B Excel unparsed sheet %r raw-read failed: %s",
            sheet_name,
            exc,
        )
        return 0
    if raw_df is None or raw_df.empty:
        return 0
    # Count rows with at least one non-null / non-blank cell.
    n = 0
    for _, series in raw_df.iterrows():
        has_val = False
        for val in series.tolist():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            if str(val).strip() == "":
                continue
            has_val = True
            break
        if has_val:
            n += 1
    # Subtract one for a likely header row when we couldn't map columns.
    return max(0, n - 1) if n > 1 else n


def _cell_to_jsonish(val: Any) -> Any:
    """Convert Excel cell values into JSON-friendly scalars for alt normalizer."""
    if val is None:
        return ""
    if isinstance(val, float) and pd.isna(val):
        return ""
    if isinstance(val, str):
        return val
    if hasattr(val, "strftime") and not isinstance(val, (int, float, bool)):
        try:
            return val.strftime("%d-%b-%y")
        except Exception:
            return str(val)
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        if isinstance(val, float) and val == int(val) and abs(val) < 1e15:
            return int(val)
        return val
    return str(val)


_CANONICAL_FIELD_TO_STD_KEY: tuple[tuple[str, str], ...] = (
    ("gstin", "GSTIN"),
    ("supplier_name", "Party"),
    ("invoice_number", "Invoice No"),
    ("invoice_date", "Invoice Date"),
    ("taxable_amount", "Taxable Value"),
    ("total_amount", "Invoice Value"),
    ("igst", "Integrated Tax"),
    ("cgst", "Central Tax"),
    ("sgst", "State/UT Tax"),
    ("cess", "Cess"),
    ("total_tax", "Total Tax"),
    ("place_of_supply", "POS"),
    ("reverse_charge", "Reverse Charge"),
    ("itc_eligibility", "ITC Available"),
    ("note_number", "Note Number"),
    ("note_amount", "Note Value"),
    ("note_type", "Note Type"),
    ("note_reason", "Reason"),
    ("original_invoice_number", "Original Invoice Number"),
)


def _dataframe_to_row_dicts(
    df: pd.DataFrame, mapping: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        row: dict[str, Any] = {}
        for col in df.columns:
            key = str(col).strip() if col is not None else ""
            if not key:
                continue
            row[key] = _cell_to_jsonish(series.get(col))
        if mapping:
            for std_field, target_key in _CANONICAL_FIELD_TO_STD_KEY:
                col_name = mapping.get(std_field)
                if col_name and col_name in df.columns:
                    val = _cell_to_jsonish(series.get(col_name))
                    if val != "" and val is not None:
                        row.setdefault(target_key, val)
        rows.append(row)
    return rows


def _extract_gstin_from_title_rows(raw_df: pd.DataFrame, header_row: int) -> str:
    """Scan rows above the header for ``NAME (GSTIN) (F.Y.:…)`` style titles."""
    if header_row < 0:
        header_row = 0
    limit = min(header_row, len(raw_df))
    for r in range(limit):
        for c in range(min(8, raw_df.shape[1])):
            val = raw_df.iat[r, c]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            text = str(val).strip()
            if not text:
                continue
            m = _GSTIN_IN_TEXT_RE.search(text)
            if m:
                return m.group(1).upper()
    return ""


def _extract_period_from_title_or_filename(
    raw_df: pd.DataFrame, header_row: int, filename: str = ""
) -> str:
    """Scan title rows or filename for return period."""
    if header_row < 0:
        header_row = 0
    limit = min(header_row, len(raw_df))
    for r in range(limit):
        for c in range(min(8, raw_df.shape[1])):
            val = raw_df.iat[r, c]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            text = str(val).strip()
            if not text:
                continue
            m = re.search(
                r"(?:return\s*period|filing\s*period|period|month)\s*[:\-]?\s*([A-Za-z]{3,9}\s*,?\s*\d{4}|\d{1,2}[-/]\d{4}|\d{4}[-/]\d{1,2})",
                text,
                re.IGNORECASE,
            )
            if m:
                p = _alt_parse_period_to_rtnprd(m.group(1))
                if p:
                    return p
    if filename:
        fn = os.path.basename(filename)
        m_fn = re.search(
            r"(?:_|-|\b)([A-Za-z]{3,9}[-_]?\d{4}|\d{4}[-_]\d{2}|\d{2}[-_]\d{4}|\d{6})(?:_|-|\.|\b)",
            fn,
            re.IGNORECASE,
        )
        if m_fn:
            token = m_fn.group(1).replace("_", "-")
            p = _alt_parse_period_to_rtnprd(token)
            if p:
                return p
    return ""


def _read_named_sheet(
    xl: pd.ExcelFile,
    sheet_name: str,
    filename: str = "",
    client_gstin: str | None = None,
) -> tuple[list[dict[str, Any]], str, str, int]:
    """Return (row dicts, title_gstin, title_period, header_row) for one workbook sheet."""
    raw_df = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
    if raw_df is None or raw_df.empty:
        return [], "", "", -1

    body_df, _mapping, header_row = _find_best_header_from_raw(
        raw_df, client_gstin=client_gstin
    )
    if body_df is None:
        title = _extract_gstin_from_title_rows(raw_df, max(header_row, 0))
        period = _extract_period_from_title_or_filename(
            raw_df, max(header_row, 0), filename
        )
        return [], title, period, header_row

    title = _extract_gstin_from_title_rows(raw_df, header_row)
    period = _extract_period_from_title_or_filename(raw_df, header_row, filename)
    if body_df.empty:
        return [], title, period, header_row
    return _dataframe_to_row_dicts(body_df, mapping=_mapping), title, period, header_row


# Disallowed words/compact names in sheet name for GSTR-2B invoice content candidate
_DISALLOWED_INVOICE_SHEET_SUBSTRINGS = (
    "summary",
    "dashboard",
    "total",
    "instruction",
    "readme",
    "help",
    "blank",
    "purchase",
    "purchases",
    "pur reg",
    "sales",
    "sale",
    "ledger",
    "bank",
)

_DISALLOWED_INVOICE_SHEET_COMPACT = frozenset(
    {"pr", "pur", "purchaseregister", "sr", "salesregister"}
)

_PR_TITLE_PHRASES = (
    "purchase register",
    "purchase book",
    "purchase journal",
    "purchase voucher",
    "purchases for the period",
    "purchase report",
)

_PR_COLUMN_MARKERS = (
    "voucher no",
    "voucher number",
    "vch no",
    "vch num",
    "voucher type",
    "vch type",
    "party s a c name",
    "party a c name",
    "party ac name",
    "payment status",
    "paid status",
    "payment date",
    "amount paid",
    "purchase account",
    "purchase ledger",
    "purchase type",
)


def _is_gstr2b_invoice_sheet_by_content(
    xl: pd.ExcelFile,
    sheet_name: str,
    filename: str = "",
    client_gstin: str | None = None,
) -> tuple[bool, list[dict[str, Any]], str, str]:
    """Inspect a workbook sheet by content to see if it qualifies as a GSTR-2B invoice sheet.

    Returns (is_valid, rows, title_gstin, title_period).

    A sheet qualifies ONLY when:
    1. Sheet name is not disqualified (not summary, help, PR, SR, etc.)
    2. Sheet title rows do not indicate a Purchase Register
    3. Sheet header mapping detects:
       - supplier GSTIN (mapping['gstin'])
       - invoice number (mapping['invoice_number'])
       - at least one relevant invoice/tax field: invoice_date, taxable_amount/total_amount,
         or tax amount (igst, cgst, sgst, cess, total_tax)
    4. Sheet does not contain internal accounting PR markers (e.g. voucher no,
       payment status, purchase ledger, or PR itc_eligibility)
    5. Sheet contains at least 1 non-empty data row.
    """
    str_name = str(sheet_name)
    norm_name = normalize_header(str_name)
    compact_name = norm_name.replace(" ", "")

    if compact_name in _DISALLOWED_INVOICE_SHEET_COMPACT:
        return False, [], "", ""
    if any(sub in norm_name for sub in _DISALLOWED_INVOICE_SHEET_SUBSTRINGS):
        return False, [], "", ""

    try:
        raw_df = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
    except Exception as exc:
        logger.warning(
            "Failed reading sheet %r for content inspection: %s", sheet_name, exc
        )
        return False, [], "", ""

    if raw_df is None or raw_df.empty:
        return False, [], "", ""

    # Scan title rows for PR indicators
    limit_r = min(15, len(raw_df))
    for r in range(limit_r):
        for c in range(min(8, raw_df.shape[1])):
            val = raw_df.iat[r, c]
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            text = str(val).strip().lower()
            if any(phrase in text for phrase in _PR_TITLE_PHRASES):
                return False, [], "", ""

    body_df, mapping, header_row = _find_best_header_from_raw(
        raw_df, client_gstin=client_gstin
    )
    if body_df is None or mapping is None or body_df.empty:
        return False, [], "", ""

    # Check sufficient GSTR-2B invoice fields
    has_gstin = "gstin" in mapping
    has_invoice_num = "invoice_number" in mapping
    has_date = "invoice_date" in mapping
    has_taxable = "taxable_amount" in mapping or "total_amount" in mapping
    has_tax = any(k in mapping for k in ("igst", "cgst", "sgst", "cess", "total_tax"))

    if not (has_gstin and has_invoice_num and (has_date or has_taxable or has_tax)):
        return False, [], "", ""

    # Check for PR-specific column markers
    if "itc_eligibility" in mapping:
        return False, [], "", ""

    col_norms = [
        normalize_header(str(col)) for col in body_df.columns if col is not None
    ]
    for cn in col_norms:
        if any(marker in cn for marker in _PR_COLUMN_MARKERS):
            return False, [], "", ""
        if any(
            pr_term in cn
            for pr_term in (
                "itc eligibility",
                "itc claimed",
                "itc availed",
                "eligible for itc",
            )
        ):
            return False, [], "", ""

    rows = _dataframe_to_row_dicts(body_df, mapping=mapping)
    if not rows:
        return False, [], "", ""

    title = _extract_gstin_from_title_rows(raw_df, header_row)
    period = _extract_period_from_title_or_filename(raw_df, header_row, filename)
    return True, rows, title, period


def excel_to_alt_2b_dict(
    file_content: bytes,
    filename: str = "gstr2b.xlsx",
    client_gstin: str | None = None,
) -> dict:
    """Convert workbook bytes into the alt flat-JSON dict shape.

    Returns::

        {
          "invoice": [...],
          "note": [...],
          "gstin": "<optional from title>",
          "period": "<optional from title/filename>",
          "_unparsed_isd_count": int,
          "_unparsed_impg_count": int,
        }
    """
    if not file_content:
        raise ValueError("empty_gstr2b_excel")

    try:
        xl = pd.ExcelFile(io.BytesIO(file_content))
    except Exception as exc:
        raise ValueError(f"invalid_gstr2b_excel: {exc}") from exc

    invoice_rows: list[dict[str, Any]] = []
    note_rows: list[dict[str, Any]] = []
    title_gstin = ""
    title_period = ""
    isd_count = 0
    impg_count = 0

    for sheet_name in xl.sheet_names:
        kind = _sheet_kind(str(sheet_name))
        if kind is None:
            unparsed = _unparsed_sheet_kind(str(sheet_name))
            if unparsed == "isd":
                isd_count += _count_nonempty_sheet_rows(xl, sheet_name)
            elif unparsed == "impg":
                impg_count += _count_nonempty_sheet_rows(xl, sheet_name)
            continue
        try:
            rows, gstin, period, _hdr = _read_named_sheet(
                xl, sheet_name, filename=filename, client_gstin=client_gstin
            )
        except Exception as exc:
            logger.warning("GSTR-2B Excel sheet %r failed: %s", sheet_name, exc)
            continue
        if gstin and not title_gstin:
            title_gstin = gstin
        if period and not title_period:
            title_period = period
        if kind == "invoice":
            invoice_rows.extend(rows)
        else:
            note_rows.extend(rows)

    # Fallback: If no invoice sheet was found by name, inspect workbook sheets by CONTENT.
    if not invoice_rows:
        for sheet_name in xl.sheet_names:
            str_name = str(sheet_name)
            if (
                _sheet_kind(str_name) == "note"
                or _unparsed_sheet_kind(str_name) is not None
            ):
                continue
            is_valid, rows, gstin, period = _is_gstr2b_invoice_sheet_by_content(
                xl, sheet_name, filename=filename, client_gstin=client_gstin
            )
            if is_valid:
                logger.info(
                    "GSTR-2B Excel sheet %r identified as invoice sheet by content (%d rows)",
                    sheet_name,
                    len(rows),
                )
                invoice_rows.extend(rows)
                if gstin and not title_gstin:
                    title_gstin = gstin
                if period and not title_period:
                    title_period = period
                break

    if not invoice_rows and not note_rows:
        raise ValueError(
            "gstr2b_excel_no_invoice_sheet: expected an 'invoice' (and optional "
            "'note') sheet with Sr / GSTIN / Invoice No columns"
        )

    # Inspect auxiliary sheets (e.g. Metadata, Summary, Info) if title_gstin or title_period is missing
    if not title_gstin or not title_period:
        for sheet_name in xl.sheet_names:
            str_name = str(sheet_name).lower()
            if any(term in str_name for term in ("meta", "sum", "info", "about", "header", "control")):
                try:
                    meta_df = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
                    if meta_df is not None and not meta_df.empty:
                        for r in range(min(len(meta_df), 30)):
                            for c in range(min(meta_df.shape[1], 10)):
                                cell_val = str(meta_df.iat[r, c] or "").strip()
                                if not title_gstin and any(k in cell_val.lower() for k in ("recipient gstin", "buyer gstin", "taxpayer gstin", "gstin")):
                                    for dc, dr in [(1, 0), (0, 1)]:
                                        nr, nc = r + dr, c + dc
                                        if nr < len(meta_df) and nc < meta_df.shape[1]:
                                            cand = str(meta_df.iat[nr, nc] or "").strip().upper()
                                            m_g = _GSTIN_IN_TEXT_RE.search(cand)
                                            if m_g:
                                                title_gstin = m_g.group(1).upper()
                                                break
                                    if not title_gstin:
                                        m_g = _GSTIN_IN_TEXT_RE.search(cell_val.upper())
                                        if m_g:
                                            title_gstin = m_g.group(1).upper()
                                if not title_period and any(k in cell_val.lower() for k in ("return period", "filing period", "period", "month")):
                                    for dc, dr in [(1, 0), (0, 1)]:
                                        nr, nc = r + dr, c + dc
                                        if nr < len(meta_df) and nc < meta_df.shape[1]:
                                            cand = str(meta_df.iat[nr, nc] or "").strip()
                                            p_cand = _alt_parse_period_to_rtnprd(cand)
                                            if p_cand:
                                                title_period = p_cand
                                                break
                except Exception:
                    pass

    # Fallback for period: derive from invoice dates in rows if still missing
    if not title_period and invoice_rows:
        date_votes: list[str] = []
        for row in invoice_rows[:100]:
            d_val = _alt_invoice_date_portal(
                _alt_row_get(
                    row, "Invoice Date", "invoice_date", "idt",
                    "Document Date", "Doc Date", "Date"
                )
            )
            if d_val and len(d_val) == 10 and d_val[2] == "-" and d_val[5] == "-":
                date_votes.append(d_val[3:5] + d_val[6:])
        if date_votes:
            title_period = max(set(date_votes), key=date_votes.count)

    payload: dict[str, Any] = {
        "invoice": invoice_rows,
        "note": note_rows,
        _UNPARSED_ISD_COUNT_KEY: int(isd_count),
        _UNPARSED_IMPG_COUNT_KEY: int(impg_count),
    }
    if title_gstin:
        payload["gstin"] = title_gstin
    if title_period:
        payload["period"] = title_period
    return payload


def parse_2b_excel(
    file_content: bytes,
    filename: str = "gstr2b.xlsx",
    *,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> dict:
    """Parse alt-schema GSTR-2B Excel into portal-shaped ``{"data": ...}``.

    Field mapping and blank-``Sr`` skipping are delegated to
    ``normalize_alt_2b_schema`` (same path as flat JSON exports).
    """
    alt = excel_to_alt_2b_dict(
        file_content, filename, client_gstin=fallback_buyer_gstin
    )
    isd_count = int(alt.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
    impg_count = int(alt.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
    portal = normalize_alt_2b_schema(
        alt,
        fallback_buyer_gstin=fallback_buyer_gstin,
        fallback_period=fallback_period,
    )
    portal[_UNPARSED_ISD_COUNT_KEY] = isd_count
    portal[_UNPARSED_IMPG_COUNT_KEY] = impg_count
    return portal


def load_gstr2b_upload_payload(
    body: bytes,
    filename: str | None = None,
    *,
    fallback_buyer_gstin: str | None = None,
    fallback_period: str | None = None,
) -> dict:
    """Load GSTR-2B upload bytes (JSON or Excel) into a parse-ready dict.

    Excel → ``normalize_alt_2b_schema`` portal shape (may include
    ``_alt_buyer_gstin_source`` and unparsed ISD/IMPG counts). JSON is returned
    as a parsed ``dict`` for ``parse_gstr2b`` to handle (portal or alt).
    """
    name = filename or ""
    import zipfile
    if (name.lower().endswith(".zip") or body[:4] == b"PK\x03\x04") and not is_gstr2b_excel_filename(name):
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                if any(n.startswith("xl/") or n == "[Content_Types].xml" for n in zf.namelist()):
                    return parse_2b_excel(
                        body,
                        name or "gstr2b.xlsx",
                        fallback_buyer_gstin=fallback_buyer_gstin,
                        fallback_period=fallback_period,
                    )
                members = [
                    m for m in zf.namelist()
                    if not m.startswith("__MACOSX/") and not os.path.basename(m).startswith(".") and not m.endswith("/")
                ]
                json_members = [m for m in members if m.lower().endswith(".json")]
                if json_members:
                    json_members.sort()
                    merged_payload = None
                    for jm in json_members:
                        chunk_bytes = zf.read(jm)
                        chunk_data = json.loads(chunk_bytes.decode("utf-8"))
                        if merged_payload is None:
                            merged_payload = chunk_data
                        else:
                            base_data = merged_payload.get("data") if isinstance(merged_payload.get("data"), dict) else merged_payload
                            c_data = chunk_data.get("data") if isinstance(chunk_data.get("data"), dict) else chunk_data
                            for key in ("b2b", "cdnr", "b2ba", "cdnra"):
                                if isinstance(c_data.get(key), list):
                                    if key not in base_data or not isinstance(base_data.get(key), list):
                                        base_data[key] = []
                                    base_data[key].extend(c_data[key])
                    return merged_payload

                excel_members = [m for m in members if any(m.lower().endswith(ext) for ext in _EXCEL_EXTS)]
                if excel_members:
                    excel_bytes = zf.read(excel_members[0])
                    return parse_2b_excel(
                        excel_bytes,
                        os.path.basename(excel_members[0]),
                        fallback_buyer_gstin=fallback_buyer_gstin,
                        fallback_period=fallback_period,
                    )
        except (zipfile.BadZipFile, Exception):
            pass

    if is_gstr2b_excel_filename(name) or (
        not name.lower().endswith(".json") and is_gstr2b_excel_bytes(body)
    ):
        return parse_2b_excel(
            body,
            name or "gstr2b.xlsx",
            fallback_buyer_gstin=fallback_buyer_gstin,
            fallback_period=fallback_period,
        )

    try:
        data = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as e:
        if is_gstr2b_excel_bytes(body):
            return parse_2b_excel(
                body,
                name or "gstr2b.xlsx",
                fallback_buyer_gstin=fallback_buyer_gstin,
                fallback_period=fallback_period,
            )
        raise ValueError(f"invalid_utf8: {e}") from e
    except json.JSONDecodeError as e:
        if is_gstr2b_excel_bytes(body):
            return parse_2b_excel(
                body,
                name or "gstr2b.xlsx",
                fallback_buyer_gstin=fallback_buyer_gstin,
                fallback_period=fallback_period,
            )
        raise ValueError(
            f"invalid_json at line {e.lineno}, column {e.colno}: {e.msg}"
        ) from e
    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")
    return data
