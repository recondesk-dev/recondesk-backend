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

# LEGAL-FORM ABBREVIATIONS ONLY — CORP and ASSOC.
# Business-type abbreviations (ENT→ENTERPRISES, IND→INDUSTRIES, MFG→MANUFACTURING,
# SOLN→SOLUTIONS, DIST→DISTRIBUTORS, SERV→SERVICES, TRDG→TRADING …) are
# intentionally NOT here. Expanding them makes "Nirvaan Ent" look identical
# to "Nirvaan Enterprises" after expansion, defeating the fuzzy-case test
# scenario where abbreviated business-type words are the human-review signal.
#
# CORP→CORPORATION and ASSOC→ASSOCIATES are safe: both their abbreviated and
# expanded forms are in _L1_TRAILING_TOKENS, so after expansion the token is
# stripped anyway. "Prime Corp" → CORP→CORPORATION → strip → "PRIME". No leak.
_ABBREV_MAP: dict[str, str] = {
    "ASSOC": "ASSOCIATES",
    "CORP":  "CORPORATION",
}


_RE_PARENTHESES = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_RE_PUNCT = re.compile(r"[.,&()\-/]")
_RE_SPACE = re.compile(r"\s+")
_RE_DIGITS_ONLY = re.compile(r'^\d+$')



def _normalize_for_l1(name: str) -> str:
    """Return a suffix-stripped, uppercased name core for L1 comparison.

    Steps:
    0. Strip parenthetical/bracketed branch/city annotations (e.g. "(Mumbai)", "[HO]").
    1. Uppercase + strip punctuation.
    2. Drop pure-numeric tokens (e.g. sequence numbers like 4324).
    3. Expand ONLY legal-form abbreviations (CORP→CORPORATION, ASSOC→ASSOCIATES).
       Business-type abbreviations (ENT, IND, SOLN, MFG etc.) are NOT expanded
       here — they remain as their abbreviated form so token_sort_ratio can see
       the true difference between a full word and its 3-letter stub.
    4. Strip trailing legal-form tokens from the right end only.
    """
    if not name:
        return ""

    # 0. Strip parenthetical / bracketed annotations before tokenizing
    name_clean = _RE_PARENTHESES.sub(" ", name)

    # 1. Uppercase + strip punctuation + collapse spaces
    s = _RE_PUNCT.sub(" ", name_clean.upper())
    s = _RE_SPACE.sub(" ", s).strip()

    # 2. Drop pure-numeric tokens (sequence numbers embedded in vendor names)
    tokens = [t for t in s.split() if not _RE_DIGITS_ONLY.match(t)]

    # 3. Expand ONLY legal-form abbreviations
    tokens = [_ABBREV_MAP.get(t, t) for t in tokens]

    # 4. Strip trailing legal-form tokens (from right end only)
    while tokens and tokens[-1] in _L1_TRAILING_TOKENS:
        tokens.pop()

    # 5. Re-join
    return " ".join(tokens).strip()


# Business-type abbreviation stubs and their full-word expansions.
# Used by the stub-mismatch guard in l1_vendor_name_ok (Rule 3b):
# if one side has the stub and the other has the full word, block L1.
# These are NOT in _ABBREV_MAP (intentionally not expanded during normalisation)
# so they remain in the normalized token list as short stubs.
_BTYPE_STUB_TO_FULL: dict[str, str] = {
    "ENT":   "ENTERPRISES",
    "ENTS":  "ENTERPRISES",
    "IND":   "INDUSTRIES",
    "INDS":  "INDUSTRIES",
    "MFG":   "MANUFACTURING",
    "MFRS":  "MANUFACTURERS",
    "SOLN":  "SOLUTIONS",
    "SOLNS": "SOLUTIONS",
    "SERV":  "SERVICES",
    "DIST":  "DISTRIBUTORS",
    "DISTS": "DISTRIBUTORS",
    "TRDG":  "TRADING",
    "SUPP":  "SUPPLIERS",
    "SUPPS": "SUPPLIERS",
}
# Reverse map: full word → canonical stub
_BTYPE_FULL_TO_STUB: dict[str, str] = {v: k for k, v in _BTYPE_STUB_TO_FULL.items()}


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
    3b. Stub-mismatch guard: if one side has a known business-type abbreviation
        stub (ENT, IND, SOLN, MFG, SERV, DIST…) and the other has its full
        expansion as a distinct token → False (block). This fires before the
        similarity threshold so that "Apex Serv" vs "Apex Services" (score=0.82)
        is correctly blocked.
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

    # Rule 3b — stub-mismatch guard (per-user spec: "≥2 proper-noun tokens required")
    # If side A has a known business-type stub (e.g. "SOLN") and side B has its
    # full expansion ("SOLUTIONS") as a distinct token, this is a stub-vs-full-word
    # mismatch. We block UNLESS the stub side already has ≥2 proper-noun tokens
    # that match the start of the other side's proper-noun sequence.
    #
    # "Noble Tech Soln" vs "Noble Tech Solutions":
    #   stub side proper-noun tokens: [NOBLE, TECH] (2 tokens) ≥2 → allowed
    # "ABC Ent" vs "ABC Enterprises":
    #   stub side proper-noun tokens: [ABC] (1 token) < 2 → blocked
    # "Nirvaan Ent 4324" vs "Nirvaan Enterprises":
    #   stub side proper-noun tokens: [NIRVAAN] (1 token, 4324 stripped) < 2 → blocked
    ta_set = set(ta)
    tb_set = set(tb)
    stub_tokens = set(_BTYPE_STUB_TO_FULL.keys())

    for stub, full in _BTYPE_STUB_TO_FULL.items():
        for (stub_side_t, other_side_t) in [(ta, tb), (tb, ta)]:
            stub_side_set = set(stub_side_t)
            other_side_set = set(other_side_t)
            if stub in stub_side_set and full in other_side_set and stub not in other_side_set:
                # Stub-vs-full-word mismatch detected.
                # Count proper-noun tokens on the stub side: all tokens that are
                # neither the stub nor any other known business-type stub token.
                proper_noun_tokens_stub_side = [
                    t for t in stub_side_t if t not in stub_tokens
                ]
                # Count proper-noun tokens on the full-word side (exclude the full
                # expansion word itself — it's the business-type descriptor).
                proper_noun_tokens_other_side = [
                    t for t in other_side_t if t != full and t not in stub_tokens
                ]
                # Require ≥2 proper-noun tokens AND that the stub side's proper-noun
                # tokens are a prefix of the other side's proper-noun tokens.
                # This allows "Noble Tech Soln" vs "Noble Tech Solutions" but blocks
                # "ABC Ent" vs "ABC Enterprises".
                if len(proper_noun_tokens_stub_side) < 2:
                    return False
                # Even with ≥2 proper nouns, the proper-noun portions must agree.
                # "Noble Tech Soln" vs "Prime Tech Solutions" would have proper nouns
                # [NOBLE,TECH] vs [PRIME,TECH] — they don't match → block.
                pn_a = proper_noun_tokens_stub_side
                pn_b = proper_noun_tokens_other_side
                pn_shorter, pn_longer = (pn_a, pn_b) if len(pn_a) <= len(pn_b) else (pn_b, pn_a)
                if pn_longer[: len(pn_shorter)] != pn_shorter:
                    return False  # proper-noun prefixes don't match even with ≥2 tokens


    # Rule 4 — normalized similarity
    score = fuzz.token_sort_ratio(na, nb) / 100.0
    return score >= threshold
