"""HSN/SAC Code Auto-Suggest Service.

Performs fast in-memory keyword/fuzzy lookup against the reference dataset
in ``app/data/hsn_sac_common_codes.json`` to assist users during item creation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal, Optional, TypedDict

logger = logging.getLogger(__name__)

DATA_FILE_PATH = Path(__file__).parent.parent.parent / "data" / "hsn_sac_common_codes.json"


class HsnSuggestion(TypedDict):
    code: str
    description: str
    item_type: str
    match_score: int


# Cached in-memory reference data
_REFERENCE_DATA: list[dict] | None = None


def _load_reference_data() -> list[dict]:
    global _REFERENCE_DATA
    if _REFERENCE_DATA is not None:
        return _REFERENCE_DATA

    try:
        if DATA_FILE_PATH.exists():
            with open(DATA_FILE_PATH, "r", encoding="utf-8") as f:
                _REFERENCE_DATA = json.load(f)
                logger.info("Loaded %d HSN/SAC reference entries", len(_REFERENCE_DATA))
        else:
            logger.warning("HSN reference file not found at %s", DATA_FILE_PATH)
            _REFERENCE_DATA = []
    except Exception as exc:
        logger.error("Failed to load HSN/SAC reference JSON: %s", exc)
        _REFERENCE_DATA = []

    return _REFERENCE_DATA


def suggest_hsn_sac(
    item_name: str,
    item_type: Optional[Literal["goods", "service"]] = None,
    limit: int = 5,
) -> list[HsnSuggestion]:
    """Suggest HSN/SAC codes based on item name and optional item type.

    Parameters
    ----------
    item_name:
        User-typed query string (e.g. "medicine", "consulting", "laptop").
    item_type:
        Optional filter: "goods" or "service". If None, searches both categories.
    limit:
        Maximum number of suggestions to return (default 5, top 3-5).

    Returns
    -------
    list[HsnSuggestion]
        List of dicts with keys: code, description, item_type, match_score.
    """
    query = item_name.strip().lower()
    if not query or len(query) < 2:
        return []

    data = _load_reference_data()
    scored_matches: list[tuple[int, dict]] = []

    # Tokenize query words
    query_tokens = [t for t in query.split() if len(t) >= 2]

    for entry in data:
        entry_type = entry.get("item_type", "").lower()
        if item_type and entry_type != item_type.lower():
            continue

        code = str(entry.get("code", "")).strip().lower()
        desc = str(entry.get("description", "")).strip().lower()
        keywords = [k.lower() for k in entry.get("keywords", [])]

        score = 0

        # Exact code match
        if code == query:
            score += 100
        elif code.startswith(query):
            score += 80

        # Exact keyword match
        if any(k == query for k in keywords):
            score += 90

        # Prefix/token keyword match
        for k in keywords:
            if k.startswith(query):
                score += 70
            elif query in k:
                score += 50

        # Description matches
        if query in desc:
            score += 40

        # Multi-token matching
        token_matches = 0
        for qt in query_tokens:
            if qt in desc or any(qt in k for k in keywords) or qt in code:
                token_matches += 1
        if query_tokens and token_matches > 0:
            score += int((token_matches / len(query_tokens)) * 30)

        if score > 0:
            scored_matches.append((score, entry))

    # Sort descending by score
    scored_matches.sort(key=lambda x: x[0], reverse=True)

    results: list[HsnSuggestion] = []
    seen_codes: set[str] = set()

    for score, entry in scored_matches:
        code = str(entry.get("code", "")).strip()
        if code in seen_codes:
            continue
        seen_codes.add(code)
        results.append(
            {
                "code": code,
                "description": str(entry.get("description", "")),
                "item_type": str(entry.get("item_type", "")),
                "match_score": score,
            }
        )
        if len(results) >= limit:
            break

    return results


def check_hsn_type_mismatch(hsn_or_sac_code: str, item_type: str) -> Optional[dict]:
    """Check if specified HSN/SAC code conflicts with the selected item_type.

    Chapter 99 is designated for SAC (Services).
    Chapters 01 to 98 are designated for HSN (Goods).

    Returns a warning dict if a mismatch is detected, else None.
    """
    code_digits = "".join(ch for ch in str(hsn_or_sac_code or "").strip() if ch.isdigit())
    if not code_digits or len(code_digits) < 2:
        return None

    normalized_type = str(item_type or "").strip().lower()
    is_sac = code_digits.startswith("99")

    if is_sac and normalized_type == "goods":
        return {
            "mismatch": True,
            "detected_category": "service",
            "selected_type": "goods",
            "message": "This looks like a Service (SAC 99xx) code, but Item Type is set to Goods. Please confirm this is correct.",
        }
    elif not is_sac and normalized_type == "service":
        return {
            "mismatch": True,
            "detected_category": "goods",
            "selected_type": "service",
            "message": "This looks like a Goods (HSN) code, but Item Type is set to Service. Please confirm this is correct.",
        }

    return None
