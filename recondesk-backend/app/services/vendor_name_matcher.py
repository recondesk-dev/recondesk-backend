from rapidfuzz import fuzz
import math
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
# CONSERVATIVE: only pure legal-entity FORM tokens are stripped from the
# trailing end — words that describe HOW a company is incorporated, not WHAT
# it does. Business-type words (EXPORTS, INDUSTRIES, TRADERS, SOLUTIONS,
# SERVICES, AGENCIES, MANUFACTURING, etc.) are deliberately NOT stripped
# because they are the distinguishing part of the vendor name:
#   "Sunrise Exports" vs "Sunrise Industries" must NOT collapse to "SUNRISE".
_L1_TRAILING_TOKENS = {
    # Pure legal form
    "PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "LLC",
    "CORP", "CORPORATION", "CO", "COMPANY", "INC",
    # Ownership / connector words that appear as trailing noise
    "AND", "&", "SONS",
    # Abbreviation expansions: ASSOC is kept because it expands to ASSOCIATES
    # which is a form word (not a business-type distinguisher).
    "ASSOCIATES", "ASSOC",
}

# Common single-token abbreviations → canonical expansion.
# These expansions normalize abbreviated tokens to their full form BEFORE
# similarity scoring — e.g. "Royal Mfg" becomes "ROYAL MANUFACTURING" and
# scores correctly against "Royal Manufacturing". Critically, the expanded
# forms (MANUFACTURING, ENTERPRISES, etc.) are NOT in _L1_TRAILING_TOKENS,
# so they are preserved in the normalized core and used for comparison.
# This means "Royal Manufacturing" and "Royal Exports" remain distinct strings.
_ABBREV_MAP: dict[str, str] = {
    # Legal/form abbreviations
    "ASSOC": "ASSOCIATES",
    "CORP":  "CORPORATION",
    # Business-type abbreviations — expanded for better fuzzy scoring only
    "MFG":   "MANUFACTURING",
    "MFRS":  "MANUFACTURERS",
    "IND":   "INDUSTRIES",
    "INDS":  "INDUSTRIES",
    "ENT":   "ENTERPRISES",
    "ENTS":  "ENTERPRISES",
    "DIST":  "DISTRIBUTORS",
    "DISTS": "DISTRIBUTORS",
    "SOLN":  "SOLUTIONS",
    "SOLNS": "SOLUTIONS",
    "SERV":  "SERVICES",
    "TRDG":  "TRADING",
    # Geographic/other
    "INTL":  "INTERNATIONAL",
    "NATL":  "NATIONAL",
    "MGMT":  "MANAGEMENT",
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
    1. If either normalized core is empty → True (no signal, do not block L1).
    2. Exact equality of normalized cores → True.
    3. Token-prefix check: the shorter token list must be a true prefix of the
       longer token list, AND the shorter must carry at least 2 tokens (a single
       shared word like "OM", "SHREE", "CROWN" is insufficient on its own).
       Additionally the shorter must cover ≥ ceil(len(longer_tokens) / 2) of
       the longer's tokens, preventing a 2-token shorter from matching a 6-token
       longer on the first two tokens alone.
    4. token_sort_ratio on the normalized cores ≥ threshold → True.
    5. Otherwise → False (block L1, let the pair fall through to L2/L3 review).
    """
    na = _normalize_for_l1(gstr_name)
    nb = _normalize_for_l1(pr_name)

    # Rule 1 — absent name means no signal
    if not na or not nb:
        return True

    # Rule 2 — exact equality (catches identical names after normalisation)
    if na == nb:
        return True

    # Rule 3 — whole-token prefix check (only when shorter has ≥ 2 tokens)
    ta = na.split()
    tb = nb.split()
    shorter_t, longer_t = (ta, tb) if len(ta) <= len(tb) else (tb, ta)

    min_coverage = math.ceil(len(longer_t) / 2)
    is_token_prefix = longer_t[: len(shorter_t)] == shorter_t
    # Require at least 2 tokens in the shorter AND coverage ≥ ceil(longer/2).
    # This prevents any single-word prefix ("OM", "SHREE") from passing.
    coverage_ok = len(shorter_t) >= 2 and len(shorter_t) >= min_coverage
    if is_token_prefix and coverage_ok:
        return True

    # Rule 4 — normalized similarity
    score = fuzz.token_sort_ratio(na, nb) / 100.0
    return score >= threshold
