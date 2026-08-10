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
_FALSE_VALUES = frozenset({"n", "no", "false", "0", 0, False})
_INVALID_GSTIN_STRINGS = frozenset({"NAN", "NONE", "NULL", "N/A", "NA", "UNDEFINED", "UNKNOWN", "URP", ""})

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
    """Check if record has explicit RCM flag set to Yes/True in PR columns."""
    for key in ("reverse_charge", "is_reverse_charge", "rcm", "reverse_charge_flag", "rcm_applicable"):
        val = record.get(key)
        if val is not None:
            s = str(val).strip().lower()
            if s in _TRUE_VALUES:
                return True
    return False


def _is_explicit_non_rcm(record: Mapping[str, Any]) -> bool:
    """Check if record explicitly sets reverse charge flag to No/False in PR columns."""
    for key in ("reverse_charge", "is_reverse_charge", "rcm", "reverse_charge_flag", "rcm_applicable"):
        val = record.get(key)
        if val is not None:
            s = str(val).strip().lower()
            if s in _FALSE_VALUES:
                return True
    return False


def _normalize_and_validate_gstin(raw: Any) -> tuple[str, bool]:
    """Normalize supplier GSTIN and check if it conforms to valid 15-char GSTIN format.

    Returns (clean_gstin_str, is_valid_gstin_format_bool).
    Treats 'NAN', 'NONE', 'NULL', 'N/A', empty strings, and non-GSTIN patterns as invalid.
    """
    if raw is None:
        return "", False
    s = str(raw).strip().upper()
    if s in _INVALID_GSTIN_STRINGS:
        return "", False
    if len(s) == 15 and re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$", s):
        return s, True
    return s, False


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


def _estimate_rcm_tax_paise(
    hsn: str | None, category: str, record: Mapping[str, Any], taxable_paise: int
) -> tuple[int, float, bool]:
    """Estimate self-assessed RCM tax liability in paise when PR invoice has 0 billed tax.

    Returns (rcm_tax_paise, applicable_rate, is_estimated_bool).
    Uses explicit tax_rate / gst_rate from record if present; otherwise applies standard
    GST RCM notification rates (5% for GTA / notified goods, 18% for services / unregistered).
    """
    for key in ("tax_rate", "gst_rate", "rate", "applicable_rate"):
        val = record.get(key)
        if val is not None:
            try:
                rate = float(val)
                if rate > 0:
                    return int(round(taxable_paise * (rate / 100.0))), rate, False
            except (TypeError, ValueError):
                pass

    h = (hsn or "").strip()
    cat = (category or "").upper()

    if h == "9965" or "GTA" in cat or "FREIGHT" in cat or "TRANSPORT" in cat:
        rate = 5.0  # 5% GTA RCM rate
    elif h in ("0801", "2401", "5004", "5201", "1404") or "CASHEW" in cat or "COTTON" in cat or "SILK" in cat:
        rate = 5.0  # 5% notified goods RCM rate
    else:
        rate = 18.0  # 18% standard services / unregistered RCM rate

    return int(round(taxable_paise * (rate / 100.0))), rate, True


# ══════════════════════════════════════════════════════════════════════════════
# Main Detection Function
# ══════════════════════════════════════════════════════════════════════════════

def detect_rcm_inward_supplies(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """
    Scan purchase register records for RCM applicability.

    Uses multi-signal evidence aggregation (explicit PR flag, HSN/SAC rules,
    keyword rules, unregistered supplier checks) and aggregates all corroborating
    evidence into the record explanation and confidence tier.
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
        raw_gstin = rec.get("supplier_gstin") or rec.get("gstin") or rec.get("vendor_gstin")
        clean_gstin, is_valid_gstin = _normalize_and_validate_gstin(raw_gstin)

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
        is_explicit_no = _is_explicit_non_rcm(rec)

        signals: list[dict[str, Any]] = []

        # Signal 1: Explicit PR reverse charge column flag == True
        if is_explicit:
            signals.append({
                "source": "pr_flag",
                "category": "Explicitly marked RCM in Purchase Register",
                "reason_code": REASON_PR_REVERSE_CHARGE_FLAG,
                "confidence": CONFIDENCE_HIGH,
                "pending": False,
                "explanation": "Explicit PR reverse charge flag = Yes",
            })

        # Forward-charge guard (BUG 1): if explicitly set to False/No AND tax is charged,
        # skip HSN/SAC/keyword RCM rules (valid forward-charge GTA / supplier option).
        is_forward_charge_option = is_explicit_no and total_tax_paise > 0

        if not is_forward_charge_option:
            # Signal 2: HSN match against Notified Goods
            if hsn in NOTIFIED_GOODS_HSN:
                rule = NOTIFIED_GOODS_HSN[hsn]
                signals.append({
                    "source": "hsn",
                    "category": rule["category"],
                    "reason_code": rule["reason_code"],
                    "confidence": rule["confidence"],
                    "pending": False,
                    "explanation": f"HSN {hsn}: {rule['description']}",
                })

            # Signal 3: SAC match against Notified Services
            if hsn in NOTIFIED_SERVICES_SAC:
                rule = NOTIFIED_SERVICES_SAC[hsn]
                signals.append({
                    "source": "sac",
                    "category": rule["category"],
                    "reason_code": rule["reason_code"],
                    "confidence": rule["confidence"],
                    "pending": rule["confidence"] != CONFIDENCE_HIGH,
                    "explanation": f"SAC {hsn}: {rule['description']}",
                })

            # Signal 4: Text Keyword Scan
            if desc_text:
                upper_desc = desc_text.upper()
                for pattern, cat, reason, conf, pending in RCM_KEYWORD_RULES:
                    if re.search(pattern, upper_desc, re.IGNORECASE):
                        clean_pattern = pattern.replace(r"\b", "").replace(r"\s+", " ")
                        signals.append({
                            "source": "keyword",
                            "category": cat,
                            "reason_code": reason,
                            "confidence": conf,
                            "pending": pending,
                            "explanation": f"Matched keyword '{clean_pattern}' in description",
                        })
                        break

            # Signal 5: Unregistered supplier RCM check (BUG 2)
            if not is_valid_gstin and taxable_paise > 0 and str(rec.get("supplier_name", "")).upper() not in ("", "CASH", "NAN"):
                signals.append({
                    "source": "unregistered",
                    "category": "Unregistered Supplier Inward Supply -- Section 9(4)",
                    "reason_code": REASON_UNREGISTERED_SUPPLIER,
                    "confidence": CONFIDENCE_MEDIUM,
                    "pending": True,
                    "explanation": "Inward supply from unregistered supplier (Section 9(4))",
                })

        if signals:
            # Prefer specific rule category over general 'Explicitly marked' category if available
            primary_cat = next((s["category"] for s in signals if s["source"] in ("hsn", "sac", "keyword")), signals[0]["category"])
            primary_reason = next((s["reason_code"] for s in signals if s["source"] in ("hsn", "sac", "keyword")), signals[0]["reason_code"])
            sources = [s["source"] for s in signals]
            source_str = "+".join(dict.fromkeys(sources))

            # BUG 3: Corroborated signals produce HIGH confidence and combine explanation parts
            conf = CONFIDENCE_HIGH if len(signals) > 1 or any(s["confidence"] == CONFIDENCE_HIGH for s in signals) else signals[0]["confidence"]
            pending = any(s["pending"] for s in signals) and conf != CONFIDENCE_HIGH
            exp = "; ".join(s["explanation"] for s in signals)

            # Self-assessed RCM liability calculation: supplier invoices under RCM show 0 tax billed;
            # estimate recipient RCM liability from applicable GST rate if raw total_tax_paise == 0.
            rcm_tax_paise = total_tax_paise
            tax_rate = 0.0
            is_estimated = False
            if rcm_tax_paise == 0 and taxable_paise > 0:
                rcm_tax_paise, tax_rate, is_estimated = _estimate_rcm_tax_paise(hsn, primary_cat, rec, taxable_paise)
                exp = f"{exp}; Estimated @ {tax_rate:g}% statutory RCM rate"
            elif total_tax_paise > 0 and taxable_paise > 0:
                tax_rate = round((total_tax_paise / taxable_paise) * 100, 2)
                exp = f"{exp}; Rate per PR ({tax_rate:g}%)"

            flagged.append({
                "invoice_number": inv_num,
                "supplier_gstin": clean_gstin,
                "supplier_name": str(rec.get("supplier_name") or "").strip(),
                "invoice_date": str(rec.get("invoice_date") or "").strip(),
                "hsn_sac": hsn,
                "taxable_value_paise": taxable_paise,
                "igst_paise": igst_paise,
                "cgst_paise": cgst_paise,
                "sgst_paise": sgst_paise,
                "cess_paise": cess_paise,
                "total_tax_paise": rcm_tax_paise,
                "rcm_tax_rate": tax_rate,
                "rcm_tax_is_estimated": is_estimated,
                "category": primary_cat,
                "reason_code": primary_reason,
                "confidence": conf,
                "flag_source": source_str,
                "pending_review": pending,
                "explanation": exp,
                "raw_record": dict(rec),
            })

    return flagged
