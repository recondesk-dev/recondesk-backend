"""
RCM (Reverse Charge Mechanism) applicability detector for Purchase Register records.

Scans purchase register records against HSN/SAC codes and text keywords in
ledger names, item descriptions, and remarks to identify inward supplies
liable to Reverse Charge under Notification 4/2017-CT(Rate) (goods),
Notification 13/2017-CT(Rate) (services), Notification 10/2017-IT(Rate) (imports),
and Section 9(4) CGST Act.

Follows the same read-only advisory pattern as app/services/blocked_credit_checker.py.
Assigns confidence tiers (HIGH, MEDIUM, LOW) and reason codes.
Ambiguous keyword-only matches are tagged for manual review (pending_review=True).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# Reason Codes & Confidence Tiers
# ══════════════════════════════════════════════════════════════════════════════

REASON_PR_REVERSE_CHARGE_FLAG = "PR_REVERSE_CHARGE_FLAG"
REASON_NOTIFIED_GOODS = "RCM_NOTIFIED_GOODS"
REASON_NOTIFIED_SERVICES = "RCM_NOTIFIED_SERVICES"
REASON_IMPORT_OF_SERVICES = "RCM_IMPORT_OF_SERVICES"
REASON_UNREGISTERED_SUPPLIER = "RCM_UNREGISTERED_SUPPLIER"
REASON_KEYWORD_MATCH = "RCM_KEYWORD_MATCH"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

# ══════════════════════════════════════════════════════════════════════════════
# Notified Goods (Notification No. 4/2017-Central Tax (Rate) as amended)
# ══════════════════════════════════════════════════════════════════════════════

NOTIFIED_GOODS_HSN: dict[str, dict[str, Any]] = {
    "0801": {
        "category": "Cashew nuts, not shelled or peeled -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Cashew nuts (not shelled or peeled) supplied by agriculturist",
    },
    "1404": {
        "category": "Bidi wrapper leaves (tendu) -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Bidi wrapper leaves (tendu) supplied by agriculturist",
    },
    "2401": {
        "category": "Tobacco leaves -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Tobacco leaves supplied by agriculturist",
    },
    "5004": {
        "category": "Silk yarn -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Silk yarn manufactured from raw silk or silk worm cocoons",
    },
    "5005": {
        "category": "Silk yarn -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Yarn spun from silk waste",
    },
    "5006": {
        "category": "Silk yarn -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Silk yarn and yarn spun from silk waste, put up for retail sale",
    },
    "5201": {
        "category": "Raw cotton -- Notification 4/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_GOODS,
        "description": "Raw cotton supplied by agriculturist",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# Notified Services (Notification No. 13/2017-Central Tax (Rate) as amended)
# ══════════════════════════════════════════════════════════════════════════════

NOTIFIED_SERVICES_SAC: dict[str, dict[str, Any]] = {
    "9965": {
        "category": "Goods Transport Agency (GTA) -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Freight/transport services supplied by GTA where recipient is liable to pay tax under RCM",
    },
    "9967": {
        "category": "Goods Transport Agency / Supporting Transport Services -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Cargo handling and transport services under GTA RCM",
    },
    "9982": {
        "category": "Legal services from advocate/firm / Arbitral tribunal -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_HIGH,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Legal services directly or indirectly provided by an advocate or firm of advocates",
    },
    "9983": {
        "category": "Director services / Sponsorship services -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_MEDIUM,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Services by a director to body corporate, or sponsorship services",
    },
    "9966": {
        "category": "Renting of motor vehicle -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_MEDIUM,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Services provided by way of renting of any motor vehicle designed to carry passengers",
    },
    "9985": {
        "category": "Security services / Security personnel -- Notification 13/2017-CT(Rate)",
        "confidence": CONFIDENCE_MEDIUM,
        "reason_code": REASON_NOTIFIED_SERVICES,
        "description": "Security services (supply of security personnel) provided to a registered person",
    },
}

# ══════════════════════════════════════════════════════════════════════════════
# Text Keyword Scanning Definitions
# ══════════════════════════════════════════════════════════════════════════════

# Tuple format: (keyword_pattern, category, reason_code, confidence, pending_review)
RCM_KEYWORD_RULES: list[tuple[str, str, str, str, bool]] = [
    (
        r"\bDIRECTOR\s+(REMUNERATION|SITTING\s+FEES?|COMMISSION|FEES?)\b",
        "Services by Director to Company -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bDIRECTOR\s+FEES?\b",
        "Services by Director to Company -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bLEGAL\s+(FEES?|CHARGES?|EXPENSES?|COUNSEL|CONSULTATION)\b",
        "Legal Services by Advocate/Firm -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bADVOCATE\b",
        "Legal Services by Advocate/Firm -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bARBITRAL\s+TRIBUNAL\b",
        "Services by Arbitral Tribunal -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bIMPORT\s+OF\s+SERVICE(S)?\b",
        "Import of Services -- Section 5(3) IGST Act / Notification 10/2017-IT(Rate)",
        REASON_IMPORT_OF_SERVICES,
        CONFIDENCE_HIGH,
        False,
    ),
    (
        r"\bSPONSORSHIP\s+(FEES?|CHARGES?|SERVICES?|AMOUNT)?\b",
        "Sponsorship Services -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\b(GTA|FREIGHT|CARTAGE|TRANSPORT|TRANSPORTATION)\b",
        "Goods Transport Agency (GTA) Freight -- Notification 13/2017-CT(Rate)",
        REASON_NOTIFIED_SERVICES,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\bBIDI\s+WRAPPER|TENDU\s+LEAF|TENDU\s+LEAVES\b",
        "Bidi wrapper leaves (tendu) -- Notification 4/2017-CT(Rate)",
        REASON_NOTIFIED_GOODS,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\bCASHEW\s+NUT(S)?\b",
        "Cashew nuts (raw/unshelled) -- Notification 4/2017-CT(Rate)",
        REASON_NOTIFIED_GOODS,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\bTOBACCO\s+LEAF|TOBACCO\s+LEAVES\b",
        "Tobacco leaves -- Notification 4/2017-CT(Rate)",
        REASON_NOTIFIED_GOODS,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\bRAW\s+COTTON\b",
        "Raw cotton -- Notification 4/2017-CT(Rate)",
        REASON_NOTIFIED_GOODS,
        CONFIDENCE_MEDIUM,
        True,
    ),
    (
        r"\bSILK\s+YARN\b",
        "Silk yarn -- Notification 4/2017-CT(Rate)",
        REASON_NOTIFIED_GOODS,
        CONFIDENCE_MEDIUM,
        True,
    ),
]

_TRUE_VALUES = frozenset({"y", "yes", "true", "1", 1, True, "rcm"})

# ══════════════════════════════════════════════════════════════════════════════
# Helper Functions
# ══════════════════════════════════════════════════════════════════════════════

def _extract_hsn_prefix(record: Mapping[str, Any]) -> str | None:
    """Extract 4-digit HSN/SAC chapter code from record or nested items."""
    for key in ("hsn", "hsn_code", "hsn_sc", "sac", "sac_code"):
        val = record.get(key)
        if val is not None and str(val).strip():
            digits = re.sub(r"\D", "", str(val))
            if digits:
                return digits[:4]
            # Fallback to string slice if non-digit characters exist
            clean = str(val).strip()
            if len(clean) >= 4:
                return clean[:4]

    items = record.get("items")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            for key in ("hsn", "hsn_code", "hsn_sc", "sac", "sac_code"):
                val = item.get(key)
                if val is not None and str(val).strip():
                    digits = re.sub(r"\D", "", str(val))
                    if digits:
                        return digits[:4]
                    clean = str(val).strip()
                    if len(clean) >= 4:
                        return clean[:4]
    return None


def _is_explicit_rcm(record: Mapping[str, Any]) -> bool:
    """Check if record has explicit RCM flag set in PR columns."""
    for key in ("reverse_charge", "is_reverse_charge", "rcm", "reverse_charge_flag", "rcm_applicable"):
        val = record.get(key)
        if val is not None:
            s = str(val).strip().lower()
            if s in _TRUE_VALUES:
                return True
    return False


def _safe_amount_paise(record: Mapping[str, Any], *keys: str) -> int:
    """Extract amount in paise from record."""
    for k in keys:
        v = record.get(k)
        if v is not None:
            try:
                if k.endswith("_paise"):
                    return int(v)
                return int(round(float(v) * 100))
            except (TypeError, ValueError):
                pass
    return 0


def _build_description_string(record: Mapping[str, Any]) -> str:
    """Concatenate text fields for keyword scanning."""
    parts = [
        str(record.get("ledger_name") or ""),
        str(record.get("item_name") or ""),
        str(record.get("item_description") or ""),
        str(record.get("description") or ""),
        str(record.get("remarks") or ""),
        str(record.get("supplier_name") or ""),
    ]
    return " ".join([p for p in parts if p]).strip()


def _unwrap_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Unwrap outcome dictionary if wrapped in {"matcher": ..., "record_data": ...}."""
    if not isinstance(record, dict):
        return dict(record)
    out: dict[str, Any] = {}
    if "record_data" in record and isinstance(record["record_data"], dict):
        out.update(record["record_data"])
    if "matcher" in record and isinstance(record["matcher"], dict):
        out.update(record["matcher"])
    for k, v in record.items():
        if k not in ("matcher", "record_data") and k not in out:
            out[k] = v
    return out or dict(record)


# ══════════════════════════════════════════════════════════════════════════════
# Main Detection Function
# ══════════════════════════════════════════════════════════════════════════════

def detect_rcm_inward_supplies(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Scan purchase register records for RCM applicability.

    Parameters
    ----------
    records : Sequence[Mapping[str, Any]]
        Parsed purchase register rows.

    Returns
    -------
    list[dict[str, Any]]
        List of flagged RCM-applicable row objects containing:
        - invoice_number, supplier_gstin, supplier_name, invoice_date
        - taxable_value_paise, total_tax_paise, igst_paise, cgst_paise, sgst_paise, cess_paise
        - category, reason_code, confidence, flag_source, pending_review, explanation
    """
    flagged: list[dict[str, Any]] = []

    for raw_rec in records:
        rec = _unwrap_record(raw_rec)
        inv_num = (
            rec.get("invoice_number_normalized")
            or rec.get("invoice_number")
            or rec.get("inv_no")
            or rec.get("doc_no")
            or ""
        )
        supplier_gstin = str(
            rec.get("supplier_gstin")
            or rec.get("gstin")
            or rec.get("vendor_gstin")
            or ""
        ).strip().upper()

        taxable_paise = _safe_amount_paise(rec, "taxable_amount_paise", "taxable_value_paise", "taxable_value", "taxable_amount")
        igst_paise = _safe_amount_paise(rec, "igst_paise", "igst")
        cgst_paise = _safe_amount_paise(rec, "cgst_paise", "cgst")
        sgst_paise = _safe_amount_paise(rec, "sgst_paise", "sgst")
        cess_paise = _safe_amount_paise(rec, "cess_paise", "cess")

        total_tax_paise = (
            _safe_amount_paise(rec, "total_tax_paise", "total_tax")
            or (igst_paise + cgst_paise + sgst_paise + cess_paise)
        )

        hsn = _extract_hsn_prefix(rec)
        desc_text = _build_description_string(rec)
        is_explicit = _is_explicit_rcm(rec)

        flag_info: dict[str, Any] | None = None

        # 1. Explicit PR reverse charge column flag
        if is_explicit:
            flag_info = {
                "category": "Explicitly marked RCM in Purchase Register",
                "reason_code": REASON_PR_REVERSE_CHARGE_FLAG,
                "confidence": CONFIDENCE_HIGH,
                "flag_source": "pr_flag",
                "pending_review": False,
                "explanation": "Purchase register row has reverse charge column set to Yes/True.",
            }

        # 2. HSN / SAC match against Notified Goods
        elif hsn in NOTIFIED_GOODS_HSN:
            rule = NOTIFIED_GOODS_HSN[hsn]
            flag_info = {
                "category": rule["category"],
                "reason_code": rule["reason_code"],
                "confidence": rule["confidence"],
                "flag_source": "hsn",
                "pending_review": False,
                "explanation": f"HSN {hsn}: {rule['description']}",
            }

        # 3. HSN / SAC match against Notified Services
        elif hsn in NOTIFIED_SERVICES_SAC:
            rule = NOTIFIED_SERVICES_SAC[hsn]
            flag_info = {
                "category": rule["category"],
                "reason_code": rule["reason_code"],
                "confidence": rule["confidence"],
                "flag_source": "sac",
                "pending_review": rule["confidence"] != CONFIDENCE_HIGH,
                "explanation": f"SAC {hsn}: {rule['description']}",
            }

        # 4. Text Keyword Scan
        elif desc_text:
            upper_desc = desc_text.upper()
            for pattern, cat, reason, conf, pending in RCM_KEYWORD_RULES:
                if re.search(pattern, upper_desc, re.IGNORECASE):
                    clean_pattern = pattern.replace(r"\b", "").replace(r"\s+", " ")
                    flag_info = {
                        "category": cat,
                        "reason_code": reason,
                        "confidence": conf,
                        "flag_source": "keyword",
                        "pending_review": pending,
                        "explanation": f"Matched keyword in description/ledger: '{clean_pattern}'",
                    }
                    break

        # 5. Unregistered supplier RCM check (if supplier GSTIN is missing/URP and taxable > 0)
        elif not supplier_gstin and taxable_paise > 0 and str(rec.get("supplier_name", "")).upper() not in ("", "CASH"):
            # Unregistered purchase check
            if str(rec.get("supply_type", "")).upper() == "URP" or "URP" in desc_text.upper():
                flag_info = {
                    "category": "Unregistered Supplier Inward Supply -- Section 9(4)",
                    "reason_code": REASON_UNREGISTERED_SUPPLIER,
                    "confidence": CONFIDENCE_MEDIUM,
                    "flag_source": "unregistered",
                    "pending_review": True,
                    "explanation": "Inward supply from unregistered person (URP). Verify applicability under Section 9(4).",
                }

        if flag_info:
            flagged.append({
                "invoice_number": inv_num,
                "supplier_gstin": supplier_gstin,
                "supplier_name": str(rec.get("supplier_name") or "").strip(),
                "invoice_date": str(rec.get("invoice_date") or "").strip(),
                "hsn_sac": hsn,
                "taxable_value_paise": taxable_paise,
                "igst_paise": igst_paise,
                "cgst_paise": cgst_paise,
                "sgst_paise": sgst_paise,
                "cess_paise": cess_paise,
                "total_tax_paise": total_tax_paise,
                "category": flag_info["category"],
                "reason_code": flag_info["reason_code"],
                "confidence": flag_info["confidence"],
                "flag_source": flag_info["flag_source"],
                "pending_review": flag_info["pending_review"],
                "explanation": flag_info["explanation"],
                "raw_record": dict(rec),
            })

    return flagged
