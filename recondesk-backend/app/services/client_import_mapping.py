"""Persistent PR column mappings per client_gstin_id.

Mappings reshape source headers into parser-friendly names before
``parse_purchase_register`` runs. Normalization / matching logic is unchanged.
"""

from __future__ import annotations

import io
import logging
from enum import Enum
from typing import Any, Optional

import pandas as pd
from fastapi import HTTPException, status
from pydantic import BaseModel, Field
from supabase import Client

from app.parsers.purchase_register_parser import (
    ParseError,
    detect_column_mapping,
    normalize_header,
)
from app.services.reconciliation_import_wizard.wizard_service import _read_pr_dataframe

_log = logging.getLogger(__name__)

T_MAPPINGS = "client_import_mappings"

REQUIRED_TARGET_FIELDS = frozenset(
    {"gstin", "invoice_number", "invoice_date", "taxable_value"}
)
TAX_TARGET_FIELDS = frozenset({"cgst", "sgst", "igst", "cess"})
ALL_TARGET_FIELDS = frozenset(
    {
        "gstin",
        "invoice_number",
        "invoice_date",
        "taxable_value",
        "cgst",
        "sgst",
        "igst",
        "cess",
    }
)

# Rename source columns to headers the existing parser already recognizes.
TARGET_TO_PARSER_HEADER: dict[str, str] = {
    "gstin": "Supplier GSTIN",
    "invoice_number": "Invoice Number",
    "invoice_date": "Invoice Date",
    "taxable_value": "Taxable Value",
    "cgst": "CGST",
    "sgst": "SGST",
    "igst": "IGST",
    "cess": "Cess",
}

# Wizard / API target_field → parser standard field used by detect_column_mapping.
TARGET_TO_PARSER_FIELD: dict[str, str] = {
    "gstin": "gstin",
    "invoice_number": "invoice_number",
    "invoice_date": "invoice_date",
    "taxable_value": "taxable_amount",
    "cgst": "cgst",
    "sgst": "sgst",
    "igst": "igst",
    "cess": "cess",
}


class TargetField(str, Enum):
    gstin = "gstin"
    invoice_number = "invoice_number"
    invoice_date = "invoice_date"
    taxable_value = "taxable_value"
    cgst = "cgst"
    sgst = "sgst"
    igst = "igst"
    cess = "cess"


class MappingItem(BaseModel):
    source_column_name: str = Field(..., min_length=1)
    target_field: TargetField


class MappingSaveBody(BaseModel):
    mappings: list[MappingItem]


def validate_mapping_items(items: list[MappingItem]) -> None:
    """Raise 422 if required fields / tax rule / uniqueness fail."""
    if not items:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "At least one mapping is required",
                "missing_required": sorted(REQUIRED_TARGET_FIELDS),
                "missing_tax": True,
            },
        )

    seen_targets: set[str] = set()
    seen_sources: set[str] = set()
    for item in items:
        tf = item.target_field.value
        src = item.source_column_name.strip()
        if not src:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": "source_column_name cannot be empty"},
            )
        if tf not in ALL_TARGET_FIELDS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": f"Invalid target_field: {tf}"},
            )
        if tf in seen_targets:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": f"Duplicate target_field: {tf}"},
            )
        src_key = src.casefold()
        if src_key in seen_sources:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"message": f"Duplicate source_column_name: {src}"},
            )
        seen_targets.add(tf)
        seen_sources.add(src_key)

    missing_required = sorted(REQUIRED_TARGET_FIELDS - seen_targets)
    has_tax = bool(seen_targets & TAX_TARGET_FIELDS)
    if missing_required or not has_tax:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Mapping incomplete: required fields and at least one tax field are required",
                "missing_required": missing_required,
                "missing_tax": not has_tax,
            },
        )


def get_mappings(sb: Optional[Client], client_gstin_id: str) -> list[dict[str, Any]]:
    from app.repositories.wizard import get_wizard_repository
    repo = get_wizard_repository()
    if repo is not None:
        try:
            return repo.get_client_mappings(client_gstin_id)
        except Exception as exc:
            _log.warning("Aurora get_client_mappings failed for %s: %s", client_gstin_id, exc)

    if sb is not None:
        try:
            res = (
                sb.table(T_MAPPINGS)
                .select("id, client_gstin_id, source_column_name, target_field, created_at, updated_at")
                .eq("client_gstin_id", client_gstin_id)
                .order("target_field")
                .execute()
            )
            return list(res.data or [])
        except Exception:
            pass
    return []


def get_mappings_or_none(sb: Optional[Client], client_gstin_id: str) -> Optional[list[dict[str, Any]]]:
    rows = get_mappings(sb, client_gstin_id)
    return rows if rows else None


def save_mappings(
    sb: Optional[Client], client_gstin_id: str, items: list[MappingItem]
) -> list[dict[str, Any]]:
    validate_mapping_items(items)
    from app.repositories.wizard import get_wizard_repository
    repo = get_wizard_repository()
    result = None
    if repo is not None:
        try:
            result = repo.save_client_mappings(client_gstin_id, items)
        except Exception as exc:
            _log.warning("Aurora save_client_mappings failed for %s: %s", client_gstin_id, exc)

    if sb is not None:
        try:
            sb.table(T_MAPPINGS).delete().eq("client_gstin_id", client_gstin_id).execute()
            rows = [
                {
                    "client_gstin_id": client_gstin_id,
                    "source_column_name": item.source_column_name.strip(),
                    "target_field": item.target_field.value,
                }
                for item in items
            ]
            if rows:
                sb.table(T_MAPPINGS).insert(rows).execute()
            if result is None:
                result = get_mappings(sb, client_gstin_id)
        except Exception as exc:
            _log.warning("Supabase save_mappings failed for %s: %s", client_gstin_id, exc)

    return result if result is not None else get_mappings(sb, client_gstin_id)


def delete_mappings(sb: Optional[Client], client_gstin_id: str) -> None:
    from app.repositories.wizard import get_wizard_repository
    repo = get_wizard_repository()
    if repo is not None:
        try:
            repo.delete_client_mappings(client_gstin_id)
        except Exception as exc:
            _log.warning("Aurora delete_client_mappings failed for %s: %s", client_gstin_id, exc)

    if sb is not None:
        try:
            sb.table(T_MAPPINGS).delete().eq("client_gstin_id", client_gstin_id).execute()
        except Exception:
            pass


def mapping_covers_headers(
    mappings: list[dict[str, Any]], headers: list[str]
) -> bool:
    """True when every mapped source column exists in *headers* and required+tax are present."""
    if not mappings:
        return False
    header_set = {h.strip() for h in headers}
    header_norm = {normalize_header(h): h for h in headers}
    targets: set[str] = set()
    for m in mappings:
        src = str(m.get("source_column_name") or "").strip()
        tf = str(m.get("target_field") or "").strip()
        if not src or not tf:
            return False
        if src not in header_set and normalize_header(src) not in header_norm:
            return False
        targets.add(tf)
    if not REQUIRED_TARGET_FIELDS.issubset(targets):
        return False
    if not (targets & TAX_TARGET_FIELDS):
        return False
    return True


def extract_headers_from_file(file_content: bytes, filename: str) -> list[str]:
    """Parse header row only; do not process data rows."""
    if not file_content or not file_content.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    df = _read_pr_dataframe(file_content, filename)
    if df is None or len(df.columns) == 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Could not detect column headers in file",
        )
    return [str(h).strip() for h in df.columns.tolist()]


def columns_match_expected_schema(headers: list[str]) -> bool:
    """True when auto-detect finds required identity + amount fields."""
    if not headers:
        return False
    df = pd.DataFrame(columns=headers)
    try:
        mapping = detect_column_mapping(df)
    except ParseError:
        return False
    has_identity = "gstin" in mapping and "invoice_number" in mapping
    has_date = "invoice_date" in mapping
    has_taxable = "taxable_amount" in mapping
    has_tax = any(k in mapping for k in ("cgst", "sgst", "igst", "total_tax"))
    return bool(has_identity and has_date and has_taxable and has_tax)


def suggest_mapping_for_headers(headers: list[str]) -> list[dict[str, str]]:
    """Return auto-detected mappings [{source_column_name: str, target_field: str}] for headers."""
    if not headers:
        return []
    df = pd.DataFrame(columns=headers)
    try:
        raw_map = detect_column_mapping(df)
    except ParseError:
        return []
    parser_to_target = {v: k for k, v in TARGET_TO_PARSER_FIELD.items()}
    suggested: list[dict[str, str]] = []
    used_targets: set[str] = set()
    for std_field, orig_col in raw_map.items():
        tf = parser_to_target.get(std_field)
        if tf and orig_col in headers and tf not in used_targets:
            used_targets.add(tf)
            suggested.append({
                "source_column_name": orig_col,
                "target_field": tf,
            })
    return suggested


def apply_mapping_to_dataframe(
    df: pd.DataFrame, mappings: list[dict[str, Any]]
) -> pd.DataFrame:
    """Rename mapped source columns to parser-friendly headers; leave others intact."""
    if df is None or df.empty and len(df.columns) == 0:
        return df
    rename: dict[str, str] = {}
    cols_norm = {normalize_header(str(c)): str(c) for c in df.columns}
    used_targets: set[str] = set()
    for m in mappings:
        src = str(m.get("source_column_name") or "").strip()
        tf = str(m.get("target_field") or "").strip()
        if not src or tf not in TARGET_TO_PARSER_HEADER:
            continue
        if tf in used_targets:
            continue
        actual = src if src in df.columns else cols_norm.get(normalize_header(src))
        if not actual:
            continue
        new_name = TARGET_TO_PARSER_HEADER[tf]
        # Avoid colliding with an unmapped column that already has this name.
        if new_name in df.columns and new_name != actual:
            new_name = f"{new_name}__mapped"
        rename[actual] = new_name
        used_targets.add(tf)
    if not rename:
        return df
    return df.rename(columns=rename)


def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def reshape_file_with_mapping(
    file_content: bytes,
    filename: str,
    mappings: list[dict[str, Any]],
) -> tuple[bytes, str]:
    """Read PR file, rename columns via mapping, return CSV bytes + filename."""
    df = _read_pr_dataframe(file_content, filename)
    reshaped = apply_mapping_to_dataframe(df, mappings)
    return dataframe_to_csv_bytes(reshaped), "purchase_register_mapped.csv"


def mapping_rows_to_wizard_columns(
    mappings: list[dict[str, Any]],
    headers: list[str],
    df: Optional[pd.DataFrame] = None,
) -> list[dict[str, Any]]:
    """Convert saved client mappings into wizard ``column_mapping`` rows."""
    by_target = {
        str(m["target_field"]): str(m["source_column_name"])
        for m in mappings
        if m.get("target_field") and m.get("source_column_name")
    }
    # Wizard still uses taxable_value / total_tax / supplier_name shape.
    wizard_fields = [
        "gstin",
        "invoice_number",
        "invoice_date",
        "taxable_value",
        "total_tax",
        "supplier_name",
        "cgst",
        "sgst",
        "igst",
        "cess",
    ]
    out: list[dict[str, Any]] = []
    for field in wizard_fields:
        detected = by_target.get(field)
        if field == "total_tax" and not detected:
            # Derive total_tax from any mapped tax column for wizard compatibility.
            for tax in ("igst", "cgst", "sgst", "cess"):
                if tax in by_target:
                    detected = by_target[tax]
                    break
        samples: list[str] = []
        if detected and df is not None and detected in df.columns:
            ser = df[detected].dropna().head(3)
            samples = [str(x) for x in ser.tolist()]
        confidence = "high" if detected else "not_found"
        out.append(
            {
                "standard_field": field,
                "detected_column": detected,
                "confidence": confidence,
                "sample_values": samples,
                "confirmed": confidence == "high",
            }
        )
    return out
