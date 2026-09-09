"""
Evaluate vendor-name guard threshold with real-world Indian GST name pairs.

Run from recondesk-backend/:
    python3 scripts/evaluate_vendor_guard.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rapidfuzz import fuzz
from app.services.vendor_name_matcher import l1_vendor_name_ok, _normalize_for_l1

THRESHOLD = 0.80

SHOULD_PASS = [
    # (gstr_name, pr_name, description)
    ("Sunrise Exports",           "Sunrise Exports Pvt Ltd",          "suffix-only diff: Pvt Ltd"),
    ("Prime Corporation",         "Prime Corp",                        "suffix abbrev: Corporation->Corp"),
    ("Noble Tech Solutions",      "Noble Tech Soln",                   "2 proper + soln stub"),
    ("Metro Suppliers",           "Metro Supplier",                    "trailing s"),
    ("Delta Chemicals",           "Delta Chemicals Pvt Ltd",          "suffix-only diff: Pvt Ltd"),
    ("Reliable Office Supplies",  "Reliable Office Supplies Pvt Ltd", "suffix-only diff: Pvt Ltd"),
    ("Shree Tech Services",       "Shree Tech Services",               "identical"),
    ("RD Logistics",              "RD Logistics",                      "identical"),
    ("Tally Data Processors",     "Tally Data Processors Pvt Ltd",    "suffix-only diff: Pvt Ltd"),
    ("Metro Cloud Solutions",     "Metro Cloud Soln",                 "2 proper + soln stub"),
    ("Priya Tech Solutions",      "Priya Tech Soln",                  "2 proper + soln stub"),
    ("Apex Data Services",        "Apex Data Serv",                   "2 proper + serv stub"),
    ("Global Trade Enterprises",  "Global Trade Ent",                 "2 proper + ent stub"),
    ("Carbon Fuels Corporation",  "Carbon Fuels Corp",                "abbrev: Corporation->Corp"),
    ("Bright Consulting",         "Bright Consulting Services",       "extra trailing word"),
    ("Royal Motors",              "Royal Motors Garage",              "extra trailing word"),
    ("Secure Facilities",         "Secure Facility Services",         "plural+suffix"),
    ("Prime Office Interiors",    "Prime Office Interior",            "trailing s"),
    ("Dynamic Deccan Assoc",      "Dynamic Deccan Associates",        "abbrev: Assoc->Associates"),
]

SHOULD_FAIL = [
    # (gstr_name, pr_name, description)
    ("Royal Manufacturing",       "Royal Mfg",                        "1 proper + mfg stub"),
    ("ABC Enterprises",           "ABC Ent",                          "1 proper + ent stub"),
    ("XYZ Industries",            "XYZ Ind",                          "1 proper + ind stub"),
    ("Balaji Distributors",       "Balaji Dist",                      "1 proper + dist stub"),
    ("Delta Chemicals",           "Sunrise Exports",                  "completely different"),
    ("Royal Manufacturing",       "Noble Tech Solutions",             "completely different"),
    ("Prime Corporation",         "Metro Suppliers",                  "completely different"),
    ("Carbon Fuels Corp",         "Bright Consulting Services",       "completely different"),
    ("ABC Traders",               "XYZ Traders",                      "same suffix, different core"),
    ("Ramesh Enterprises",        "Suresh Enterprises",               "similar structure, different name"),
    ("National Chemicals Ltd",    "National Electronics Ltd",         "shared prefix, different business"),
    ("Sunrise Exports",           "Sunset Imports",                   "near-miss antonym"),
    ("Metro Cloud Solutions",     "Metro Road Solutions",             "one word different"),
    ("Dynamic Deccan Associates", "Dynamic Mumbai Associates",        "city differs"),
]


def score_pair(gstr_name: str, pr_name: str) -> tuple[float, bool]:
    """Return (display_score, guard_ok)."""
    na = _normalize_for_l1(gstr_name)
    nb = _normalize_for_l1(pr_name)

    if not na or not nb:
        return 0.0, True  # guard returns True (no signal)

    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    prefix_ok = longer.startswith(shorter) or (
        len(shorter) >= 0.90 * len(longer) and longer.startswith(shorter)
    )
    ratio = fuzz.token_sort_ratio(na, nb) / 100.0
    score = 1.0 if prefix_ok else ratio
    ok = l1_vendor_name_ok(gstr_name, pr_name, threshold=THRESHOLD)
    return score, ok


print(f"{'=' * 90}")
print(f"Vendor-name guard evaluation  (threshold={THRESHOLD})")
print(f"{'=' * 90}\n")
print(f"  Normalization examples:")
for pair in [("Sunrise Exports", "Sunrise Exports Pvt Ltd"),
             ("Noble Tech Solutions", "Noble Tech Soln"),
             ("Royal Manufacturing", "Royal Mfg"),
             ("Carbon Fuels Corporation", "Carbon Fuels Corp")]:
    print(f"    {pair[0]!r:35s} -> {_normalize_for_l1(pair[0])!r}")
    print(f"    {pair[1]!r:35s} -> {_normalize_for_l1(pair[1])!r}")
    print()

print("── SHOULD PASS (same vendor, formatting variant) ─────────────────────────────────")
all_pass = True
for gstr, pr, desc in SHOULD_PASS:
    score, ok = score_pair(gstr, pr)
    mark = "✅" if ok else "❌ FAIL"
    if not ok:
        all_pass = False
    print(f"  {mark}  {score:.3f}  {gstr!r:35s} vs {pr!r:35s}  [{desc}]")

print(f"\n  {'✅ All same-vendor pairs pass.' if all_pass else '❌ Some same-vendor pairs are being BLOCKED.'}\n")

print("── SHOULD FAIL (genuinely different vendors) ──────────────────────────────────────")
all_fail = True
for gstr, pr, desc in SHOULD_FAIL:
    score, ok = score_pair(gstr, pr)
    mark = "✅ blocked" if not ok else "❌ WRONGLY PASSED"
    if ok:
        all_fail = False
    print(f"  {mark}  {score:.3f}  {gstr!r:35s} vs {pr!r:35s}  [{desc}]")

print(f"\n  {'✅ All different-vendor pairs correctly blocked.' if all_fail else '❌ Some different-vendor pairs are INCORRECTLY passing.'}\n")
