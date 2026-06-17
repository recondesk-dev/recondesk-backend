from rapidfuzz import fuzz
import re

_STRIP_SUFFIXES = [
    "private limited", "pvt ltd", "pvt. ltd.", "pvt. ltd",
    "limited", "ltd", "llp", "& co", "and co",
    "proprietorship", "enterprises", "enterprise",
    "traders", "trading", "industries", "industry",
    "solutions", "services", "agency", "agencies",
]

_STRIP_WORDS = re.compile(
    r'\b(' + '|'.join(re.escape(s) for s in _STRIP_SUFFIXES) + r')\b',
    re.IGNORECASE
)

def normalize_vendor_name(name: str) -> str:
    if not name:
        return ""
    name = name.lower().strip()
    name = _STRIP_WORDS.sub("", name)
    name = re.sub(r'[^a-z0-9\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def vendor_name_similarity(name_a: str, name_b: str) -> float:
    """Returns 0.0–1.0. Uses token_sort_ratio to handle word-order differences."""
    a = normalize_vendor_name(name_a)
    b = normalize_vendor_name(name_b)
    if not a or not b:
        return 0.0
    return fuzz.token_sort_ratio(a, b) / 100.0

def find_best_vendor_match(
    pr_vendor: str,
    gstr_vendors: list[dict],
    threshold: float = 0.82,
) -> dict | None:
    """
    gstr_vendors: list of {"vendor_name": str, "record": dict}
    Returns the best matching record above threshold, or None.
    """
    if not gstr_vendors:
        return None
    best_score = 0.0
    best_record = None
    for item in gstr_vendors:
        score = vendor_name_similarity(pr_vendor, item["vendor_name"])
        if score > best_score:
            best_score = score
            best_record = item["record"]
    if best_score >= threshold:
        return {"record": best_record, "vendor_similarity_score": best_score}
    return None
