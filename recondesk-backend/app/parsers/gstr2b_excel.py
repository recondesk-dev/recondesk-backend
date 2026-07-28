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
from typing import Any

import pandas as pd

from app.parsers.gstr2b_parser import (
    _GSTIN_IN_TEXT_RE,
    _UNPARSED_IMPG_COUNT_KEY,
    _UNPARSED_ISD_COUNT_KEY,
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
    if norm in _INVOICE_SHEET_NAMES:
        return "invoice"
    if norm in _NOTE_SHEET_NAMES:
        return "note"
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
        rows, _gstin, _hdr = _read_named_sheet(xl, sheet_name)
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


def _dataframe_to_row_dicts(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, series in df.iterrows():
        row: dict[str, Any] = {}
        for col in df.columns:
            key = str(col).strip() if col is not None else ""
            if not key:
                continue
            row[key] = _cell_to_jsonish(series.get(col))
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


def _read_named_sheet(
    xl: pd.ExcelFile, sheet_name: str
) -> tuple[list[dict[str, Any]], str, int]:
    """Return (row dicts, title_gstin, header_row) for one workbook sheet."""
    raw_df = pd.read_excel(xl, sheet_name=sheet_name, header=None, dtype=object)
    if raw_df is None or raw_df.empty:
        return [], "", -1

    body_df, _mapping, header_row = _find_best_header_from_raw(raw_df)
    if body_df is None:
        title = _extract_gstin_from_title_rows(raw_df, max(header_row, 0))
        return [], title, header_row

    title = _extract_gstin_from_title_rows(raw_df, header_row)
    if body_df.empty:
        return [], title, header_row
    return _dataframe_to_row_dicts(body_df), title, header_row


def excel_to_alt_2b_dict(file_content: bytes, filename: str = "gstr2b.xlsx") -> dict:
    """Convert workbook bytes into the alt flat-JSON dict shape.

    Returns::

        {
          "invoice": [...],
          "note": [...],
          "gstin": "<optional from title>",
          "_unparsed_isd_count": int,
          "_unparsed_impg_count": int,
        }
    """
    del filename  # reserved for future engine hints; extension handled by callers
    if not file_content:
        raise ValueError("empty_gstr2b_excel")

    try:
        xl = pd.ExcelFile(io.BytesIO(file_content))
    except Exception as exc:
        raise ValueError(f"invalid_gstr2b_excel: {exc}") from exc

    invoice_rows: list[dict[str, Any]] = []
    note_rows: list[dict[str, Any]] = []
    title_gstin = ""
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
            rows, gstin, _hdr = _read_named_sheet(xl, sheet_name)
        except Exception as exc:
            logger.warning("GSTR-2B Excel sheet %r failed: %s", sheet_name, exc)
            continue
        if gstin and not title_gstin:
            title_gstin = gstin
        if kind == "invoice":
            invoice_rows.extend(rows)
        else:
            note_rows.extend(rows)

    if not invoice_rows and not note_rows:
        raise ValueError(
            "gstr2b_excel_no_invoice_sheet: expected an 'invoice' (and optional "
            "'note') sheet with Sr / GSTIN / Invoice No columns"
        )

    payload: dict[str, Any] = {
        "invoice": invoice_rows,
        "note": note_rows,
        _UNPARSED_ISD_COUNT_KEY: int(isd_count),
        _UNPARSED_IMPG_COUNT_KEY: int(impg_count),
    }
    if title_gstin:
        payload["gstin"] = title_gstin
    return payload


def parse_2b_excel(
    file_content: bytes,
    filename: str = "gstr2b.xlsx",
    *,
    fallback_buyer_gstin: str | None = None,
) -> dict:
    """Parse alt-schema GSTR-2B Excel into portal-shaped ``{"data": ...}``.

    Field mapping and blank-``Sr`` skipping are delegated to
    ``normalize_alt_2b_schema`` (same path as flat JSON exports).
    """
    alt = excel_to_alt_2b_dict(file_content, filename)
    isd_count = int(alt.pop(_UNPARSED_ISD_COUNT_KEY, 0) or 0)
    impg_count = int(alt.pop(_UNPARSED_IMPG_COUNT_KEY, 0) or 0)
    portal = normalize_alt_2b_schema(alt, fallback_buyer_gstin=fallback_buyer_gstin)
    portal[_UNPARSED_ISD_COUNT_KEY] = isd_count
    portal[_UNPARSED_IMPG_COUNT_KEY] = impg_count
    return portal


def load_gstr2b_upload_payload(
    body: bytes,
    filename: str | None = None,
    *,
    fallback_buyer_gstin: str | None = None,
) -> dict:
    """Load GSTR-2B upload bytes (JSON or Excel) into a parse-ready dict.

    Excel → ``normalize_alt_2b_schema`` portal shape (may include
    ``_alt_buyer_gstin_source`` and unparsed ISD/IMPG counts). JSON is returned
    as a parsed ``dict`` for ``parse_gstr2b`` to handle (portal or alt).
    """
    name = filename or ""
    if is_gstr2b_excel_filename(name) or (
        not name.lower().endswith(".json") and is_gstr2b_excel_bytes(body)
    ):
        return parse_2b_excel(
            body, name or "gstr2b.xlsx", fallback_buyer_gstin=fallback_buyer_gstin
        )

    try:
        data = json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as e:
        if is_gstr2b_excel_bytes(body):
            return parse_2b_excel(
                body, name or "gstr2b.xlsx", fallback_buyer_gstin=fallback_buyer_gstin
            )
        raise ValueError(f"invalid_utf8: {e}") from e
    except json.JSONDecodeError as e:
        if is_gstr2b_excel_bytes(body):
            return parse_2b_excel(
                body, name or "gstr2b.xlsx", fallback_buyer_gstin=fallback_buyer_gstin
            )
        raise ValueError(
            f"invalid_json at line {e.lineno}, column {e.colno}: {e.msg}"
        ) from e
    if not isinstance(data, dict):
        raise ValueError("invalid_data_structure")
    return data
