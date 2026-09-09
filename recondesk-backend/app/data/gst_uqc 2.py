"""Official GST / IRP Unit Quantity Codes (UQC) Reference List & Validation."""

from __future__ import annotations

from typing import Dict, List

GST_UQC_CODES: List[Dict[str, str]] = [
    {"code": "BAG", "description": "BAGS"},
    {"code": "BAL", "description": "BALE"},
    {"code": "BDL", "description": "BUNDLES"},
    {"code": "BKL", "description": "BUCKLES"},
    {"code": "BOU", "description": "BILLION OF UNITS"},
    {"code": "BOX", "description": "BOX"},
    {"code": "BTL", "description": "BOTTLES"},
    {"code": "BUN", "description": "BUNCHES"},
    {"code": "CAN", "description": "CANS"},
    {"code": "CBM", "description": "CUBIC METERS"},
    {"code": "CCM", "description": "CUBIC CENTIMETERS"},
    {"code": "CMS", "description": "CENTIMETERS"},
    {"code": "DOZ", "description": "DOZENS"},
    {"code": "DRS", "description": "DRUMS"},
    {"code": "GGR", "description": "GREAT GROSS"},
    {"code": "GMS", "description": "GRAMMES"},
    {"code": "GRS", "description": "GROSS"},
    {"code": "GYD", "description": "GROSS YARDS"},
    {"code": "HRS", "description": "HOURS"},
    {"code": "KGS", "description": "KILOGRAMS"},
    {"code": "KLR", "description": "KILOLITRE"},
    {"code": "KME", "description": "KILOMETRE"},
    {"code": "MLT", "description": "MILLILITRE"},
    {"code": "MTR", "description": "METERS"},
    {"code": "MTS", "description": "METRIC TON"},
    {"code": "NOS", "description": "NUMBERS"},
    {"code": "PAC", "description": "PACKETS"},
    {"code": "PCS", "description": "PIECES"},
    {"code": "PRS", "description": "PAIRS"},
    {"code": "QTL", "description": "QUINTAL"},
    {"code": "SET", "description": "SETS"},
    {"code": "SQF", "description": "SQUARE FEET"},
    {"code": "SQM", "description": "SQUARE METERS"},
    {"code": "SQY", "description": "SQUARE YARDS"},
    {"code": "TBS", "description": "TABLETS"},
    {"code": "THD", "description": "THOUSANDS"},
    {"code": "TON", "description": "TONNES"},
    {"code": "TUB", "description": "TUBES"},
    {"code": "UGS", "description": "US GALLONS"},
    {"code": "UNT", "description": "UNITS"},
    {"code": "YDS", "description": "YARDS"},
    {"code": "OTH", "description": "OTHERS"},
]

VALID_UQC_CODES = {item["code"] for item in GST_UQC_CODES}


def is_valid_uqc(unit: str) -> bool:
    """Return True if unit is in official GST UQC codes set (case-insensitive)."""
    if not unit or not isinstance(unit, str):
        return False
    return unit.strip().upper() in VALID_UQC_CODES
