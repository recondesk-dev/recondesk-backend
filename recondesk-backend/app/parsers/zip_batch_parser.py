"""ZIP batch archive unpacker and aggregator for ReconDesk.

Handles archives containing:
- Multiple monthly registers (.xlsx, .xls, .csv)
- Subfolder structures (e.g. FY2023-24/Q1/April.xlsx)
- Mixed document archives (filters out OS metadata, temporary lock files, and non-tabular items)
- Safe extraction against Zip-Slip and Zip-Bomb attacks
"""

from __future__ import annotations

import io
import logging
import os
import re
import zipfile
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)

SUPPORTED_REGISTER_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls", ".csv"})

# Safety ceilings against denial-of-service / Zip-Bomb attacks
MAX_ZIP_FILES: int = 100
MAX_TOTAL_UNCOMPRESSED_BYTES: int = 250 * 1024 * 1024  # 250 MB
MAX_SINGLE_FILE_BYTES: int = 100 * 1024 * 1024          # 100 MB


def is_zip_content(content: bytes) -> bool:
    """Return True if content has the standard ZIP magic header."""
    return bool(content and len(content) >= 4 and content[:4] == b"PK\x03\x04")


def is_excel_xml_container(zf: zipfile.ZipFile) -> bool:
    """Return True if ZIP is actually an OpenXML .xlsx container, not a user archive."""
    try:
        namelist = zf.namelist()
        return any(n.startswith("xl/") or n == "[Content_Types].xml" for n in namelist)
    except Exception:
        return False


def _natural_sort_key(s: str) -> list[Any]:
    """Sort strings with embedded numbers naturally (e.g., month_1 before month_10)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s)]


def extract_supported_files_from_zip(
    zip_bytes: bytes,
    allowed_extensions: frozenset[str] = SUPPORTED_REGISTER_EXTENSIONS,
) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Extract valid, sanitized data files from a ZIP archive.

    Returns:
        (extracted_files, skipped_warnings) where extracted_files is a list of
        (display_name, file_bytes) sorted naturally by filename.
    """
    if not zip_bytes:
        return [], ["Empty archive"]

    extracted_files: list[tuple[str, bytes]] = []
    warnings: list[str] = []

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            infolist = zf.infolist()
            if len(infolist) > MAX_ZIP_FILES:
                warnings.append(
                    f"Archive contains {len(infolist)} files; capped to first {MAX_ZIP_FILES}."
                )
                infolist = infolist[:MAX_ZIP_FILES]

            total_uncompressed = 0

            # Sort candidate members naturally by filename
            infolist.sort(key=lambda info: _natural_sort_key(info.filename))

            for info in infolist:
                # 1. Skip directories
                if info.is_dir():
                    continue

                raw_name = info.filename
                # Anti-ZipSlip: reject path traversal
                if ".." in raw_name or raw_name.startswith("/") or raw_name.startswith("\\"):
                    warnings.append(f"Ignored insecure archive path: '{raw_name}'")
                    continue

                basename = os.path.basename(raw_name)

                # 2. Skip OS metadata & temporary lock files
                if (
                    raw_name.startswith("__MACOSX/")
                    or basename.startswith("._")
                    or basename.startswith(".")
                    or basename.startswith("~$")
                    or basename.lower() in ("thumbs.db", "desktop.ini", ".ds_store")
                ):
                    continue

                # 3. Check extension
                ext = os.path.splitext(basename)[1].lower()
                if ext not in allowed_extensions:
                    warnings.append(
                        f"Skipped non-register file '{raw_name}' (supported: {', '.join(sorted(allowed_extensions))})"
                    )
                    continue

                # 4. Check uncompressed size limits
                if info.file_size > MAX_SINGLE_FILE_BYTES:
                    warnings.append(
                        f"Skipped '{raw_name}': uncompressed size {info.file_size} exceeds limit of {MAX_SINGLE_FILE_BYTES} bytes."
                    )
                    continue

                total_uncompressed += info.file_size
                if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
                    warnings.append(
                        f"Extraction stopped: total uncompressed archive size exceeded limit of {MAX_TOTAL_UNCOMPRESSED_BYTES} bytes."
                    )
                    break

                # Extract safely into memory
                try:
                    data = zf.read(info)
                    # Display name: keep relative path without leading slash
                    display_name = raw_name.lstrip("/\\")
                    extracted_files.append((display_name, data))
                except Exception as err:
                    warnings.append(f"Failed to read file '{raw_name}': {err}")

    except zipfile.BadZipFile as bzf:
        warnings.append(f"Invalid or corrupted ZIP archive: {bzf}")
    except Exception as exc:
        warnings.append(f"Error opening ZIP archive: {exc}")

    return extracted_files, warnings


def parse_zip_batch(
    file_content: bytes,
    filename: str,
    parser_func: Callable[..., dict[str, Any]],
    client_gstin: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Parse all supported registers within a ZIP and aggregate them into a unified result dict.

    Compatible with both parse_purchase_register and parse_sales_register return shapes.
    """
    combined_result: dict[str, Any] = {
        "success": False,
        "total_rows": 0,
        "valid_rows": 0,
        "records": [],
        "errors": [],
        "warnings": [],
        "sheets_used": [],
        "sheets_skipped": [],
        "missing_invoice_number_count": 0,
        "files_processed": 0,
        "source_files": [],
    }

    files, extract_warnings = extract_supported_files_from_zip(file_content)
    combined_result["warnings"].extend(extract_warnings)

    if not files:
        combined_result["errors"].append(
            f"No valid .xlsx, .xls, or .csv register files found inside '{filename}'."
        )
        return combined_result

    total_rows = 0
    valid_rows = 0
    cumulative_row_number = 0
    missing_inv_count = 0
    any_success = False
    canon_dfs: list[pd.DataFrame] = []

    for inner_filename, inner_bytes in files:
        combined_result["source_files"].append(inner_filename)
        call_kwargs = dict(kwargs)
        import inspect
        sig = inspect.signature(parser_func)
        if "client_gstin" in sig.parameters and client_gstin is not None:
            call_kwargs["client_gstin"] = client_gstin

        try:
            # Call underlying single-file parser
            sub_res = parser_func(
                inner_bytes,
                inner_filename,
                **call_kwargs,
            )
        except Exception as exc:
            logger.exception("Failed to parse inner file '%s'", inner_filename)
            combined_result["errors"].append(f"[{inner_filename}] Parse failed: {exc}")
            continue

        if sub_res.get("success"):
            any_success = True

        file_records = sub_res.get("records") or []
        for rec in file_records:
            cumulative_row_number += 1
            # Additive provenance tracking
            rec["source_file"] = inner_filename
            rec["file_row_number"] = rec.get("row_number")
            rec["row_number"] = cumulative_row_number
            combined_result["records"].append(rec)

        total_rows += sub_res.get("total_rows", 0)
        valid_rows += len(file_records)
        missing_inv_count += sub_res.get("missing_invoice_number_count", 0)

        # Merge errors & warnings with file attribution
        for err in sub_res.get("errors") or []:
            combined_result["errors"].append(f"[{inner_filename}] {err}")
        for warn in sub_res.get("warnings") or []:
            combined_result["warnings"].append(f"[{inner_filename}] {warn}")

        # Merge sheets metadata if present
        for s in sub_res.get("sheets_used") or []:
            combined_result["sheets_used"].append(f"{inner_filename}:{s}")
        for s in sub_res.get("sheets_skipped") or []:
            if isinstance(s, dict):
                combined_result["sheets_skipped"].append(
                    {**s, "file": inner_filename}
                )
            else:
                combined_result["sheets_skipped"].append(f"{inner_filename}:{s}")

        df_canon = sub_res.get("normalized_dataframe")
        if df_canon is not None and isinstance(df_canon, pd.DataFrame) and not df_canon.empty:
            canon_dfs.append(df_canon)

    combined_result["success"] = any_success or bool(combined_result["records"])
    combined_result["total_rows"] = total_rows
    combined_result["valid_rows"] = valid_rows
    combined_result["parsed_rows"] = valid_rows
    combined_result["missing_invoice_number_count"] = missing_inv_count
    combined_result["files_processed"] = len(files)

    if canon_dfs:
        try:
            combined_result["normalized_dataframe"] = pd.concat(canon_dfs, ignore_index=True)
            combined_result["normalized_columns"] = list(combined_result["normalized_dataframe"].columns)
        except Exception:
            combined_result["normalized_dataframe"] = canon_dfs[0]
            combined_result["normalized_columns"] = list(canon_dfs[0].columns)

    return combined_result


def parse_zip_to_dataframe(zip_bytes: bytes) -> pd.DataFrame:
    """Extract and concatenate all tabular files (.csv, .xlsx) in a ZIP into a single DataFrame."""
    from app.parsers.csv_parser import parse_csv
    from app.parsers.excel_parser import parse_excel

    files, _ = extract_supported_files_from_zip(zip_bytes)
    if not files:
        raise ValueError("No supported spreadsheet files found inside ZIP archive.")

    dfs: list[pd.DataFrame] = []
    for fname, data in files:
        lower = fname.lower()
        if lower.endswith((".xlsx", ".xls")):
            dfs.append(parse_excel(data))
        elif lower.endswith(".csv"):
            dfs.append(parse_csv(data))

    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)
