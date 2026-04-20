"""GSTR–PR candidate selection via ``match_gstr_to_pr`` (no separate scoring implementation)."""

from app.services.matcher import MatchResult, match_gstr_to_pr

# THRESHOLD: accept only level <= 5 (L6 = no match in matcher). L5 minimum score is 20.
THRESHOLD = 20


def compute_match_score(result: MatchResult) -> int:
    """Selection score from match level: L1=100, L2=80, L3=60, L4=40, L5=20."""
    if result is None or result.level == 6 or not result.matched:
        return 0
    return max(0, 100 - 20 * (result.level - 1))


def choose_best_candidate(g, candidates):
    scored = []
    for p in candidates:
        result = match_gstr_to_pr(g, [p])
        if result is None or result.level == 6:
            continue
        scored.append((p, compute_match_score(result)))

    if not scored:
        return None, 0, []

    scored.sort(key=lambda x: (-x[1], x[0]["id"]))
    best_p, best_score = scored[0]
    return best_p, best_score, []
