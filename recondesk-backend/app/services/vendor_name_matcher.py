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


# ---------------------------------------------------------------------------
# L1-guard-specific normalisation (independent of the functions above)
# ---------------------------------------------------------------------------
# These trailing tokens are stripped from the END of the name only, so that
# mid-name proper nouns like "Corporation Bank" are never mangled.
_L1_TRAILING_TOKENS = {
    "PVT", "PRIVATE", "LTD", "LIMITED", "LLP",
    "CORP", "CORPORATION", "CO", "COMPANY", "INC",
    "ENTERPRISES", "ENTERPRISE",
    "TRADERS", "TRADING",
    "INDUSTRIES", "INDUSTRY",
    "SOLUTIONS", "SERVICES",
    "AGENCY", "AGENCIES",
    "AND", "&",                    # "… AND SONS", "… & CO" residuals
    "SONS", "ASSOCIATES", "ASSOC",
    "DISTRIBUTORS", "DISTRIBUTOR",
    "SUPPLIERS", "SUPPLIER",
    "MANUFACTURING", "MANUFACTURERS",
    "EXPORTS", "EXPORT",
    "IMPORTS", "IMPORT",
    "GARAGE", "GROUP",
}

# Common single-token business abbreviations → their canonical expansion.
# Expanded BEFORE stripping trailing tokens so e.g. "SOLN" becomes
# "SOLUTIONS" and then is stripped just like the full word.
_ABBREV_MAP: dict[str, str] = {
    "SOLN":  "SOLUTIONS",
    "SOLNS": "SOLUTIONS",
    "MFG":   "MANUFACTURING",
    "IND":   "INDUSTRIES",
    "INDS":  "INDUSTRIES",
    "ENT":   "ENTERPRISES",
    "ENTS":  "ENTERPRISES",
    "DIST":  "DISTRIBUTORS",
    "DISTS": "DISTRIBUTORS",
    "ASSOC": "ASSOCIATES",
    "CORP":  "CORPORATION",
    "SERV":  "SERVICES",
    "MKTG":  "MARKETING",
    "MGMT":  "MANAGEMENT",
    "INTL":  "INTERNATIONAL",
    "NATL":  "NATIONAL",
    "TRDG":  "TRADING",
}

_RE_PUNCT = re.compile(r"[.,&()\-/]")
_RE_SPACE = re.compile(r"\s+")


def _normalize_for_l1(name: str) -> str:
    """Return a suffix-stripped, abbreviation-expanded, uppercased name core.

    Only trailing business-entity tokens are removed — mid-name proper nouns
    (e.g. "Corporation Bank", "Industries Limited" where "Industries" is core)
    are preserved because we strip token-by-token from the right end only.
    """
    if not name:
        return ""

    # 1. Uppercase + strip punctuation + collapse spaces
    s = _RE_PUNCT.sub(" ", name.upper())
    s = _RE_SPACE.sub(" ", s).strip()

    # 2. Expand abbreviations (whole-token match only)
    tokens = s.split()
    tokens = [_ABBREV_MAP.get(t, t) for t in tokens]

    # 3. Strip trailing business-entity tokens (from right end only)
    while tokens and tokens[-1] in _L1_TRAILING_TOKENS:
        tokens.pop()

    # 4. Re-join and collapse spaces
    return " ".join(tokens).strip()


def l1_vendor_name_ok(
    gstr_name: str,
    pr_name: str,
    threshold: float = 0.80,
) -> bool:
    """Return True if the two vendor names are close enough to allow L1 match.

    Logic (applied to suffix-stripped, abbreviation-expanded, uppercased cores):
    1. If either name is empty → True (no signal, do not block L1).
    2. Containment / prefix check: if the shorter core IS the longer or is a
       prefix of the longer → True (handles "Metro Supplier" vs "Metro Suppliers").
    3. Length-ratio shortcut: if shorter is ≥ 90% the length of longer AND
       the shorter is a prefix of the longer → True.
    4. token_sort_ratio on the normalized cores ≥ threshold → True.
    5. Otherwise → False (block L1, let the pair fall through to L2/L3 review).
    """
    na = _normalize_for_l1(gstr_name)
    nb = _normalize_for_l1(pr_name)

    # Rule 1 — absent name means no signal
    if not na or not nb:
        return True

    # Rule 2 & 3 — containment / prefix check
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if longer.startswith(shorter):
        return True
    if len(shorter) >= 0.90 * len(longer) and longer.startswith(shorter[: len(shorter)]):
        return True

    # Rule 4 — normalized similarity
    score = fuzz.token_sort_ratio(na, nb) / 100.0
    return score >= threshold
