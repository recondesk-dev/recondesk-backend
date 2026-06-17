import io
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from Levenshtein import ratio as levenshtein_ratio

from app.models.reconciliation import MatchStatus, ReconciliationRow


def load_dataframe(file_content: bytes, file_name: str) -> pd.DataFrame:
    """Parse CSV or Excel content into a DataFrame."""
    if file_name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_content))
    return pd.read_csv(io.BytesIO(file_content))


def _values_match(a: Any, b: Any, tolerance: float = 0.0) -> bool:
    """Compare two values with optional numeric tolerance or fuzzy string matching."""
    if pd.isna(a) and pd.isna(b):
        return True
    if pd.isna(a) or pd.isna(b):
        return False

    # Numeric comparison with tolerance
    try:
        fa, fb = float(a), float(b)
        if tolerance > 0:
            return abs(fa - fb) <= tolerance
        return fa == fb
    except (ValueError, TypeError):
        pass

    # Fuzzy string comparison
    sa, sb = str(a).strip().lower(), str(b).strip().lower()
    if sa == sb:
        return True
    if tolerance > 0:
        return levenshtein_ratio(sa, sb) >= (1.0 - tolerance)
    return False


def reconcile(
    source_df: pd.DataFrame,
    target_df: pd.DataFrame,
    match_columns: List[str],
    tolerance: float = 0.0,
) -> Tuple[List[ReconciliationRow], Dict[str, int]]:
    """
    Row-level reconciliation between source and target DataFrames.
    Returns a list of ReconciliationRow results and summary counts.
    """
    results: List[ReconciliationRow] = []
    matched = unmatched = partial = 0

    target_indexed = target_df.copy()

    for idx, src_row in source_df.iterrows():
        src_dict = src_row.to_dict()

        # Find the best matching target row by match_columns
        best_match: Optional[pd.Series] = None
        best_score = 0.0

        for _, tgt_row in target_indexed.iterrows():
            col_scores = []
            for col in match_columns:
                src_val = src_dict.get(col)
                tgt_val = tgt_row.get(col)
                col_scores.append(1.0 if _values_match(src_val, tgt_val, tolerance) else 0.0)

            score = sum(col_scores) / len(col_scores) if col_scores else 0.0
            if score > best_score:
                best_score = score
                best_match = tgt_row

        if best_match is None or best_score == 0.0:
            status = MatchStatus.UNMATCHED
            unmatched += 1
            results.append(
                ReconciliationRow(
                    row_index=int(idx),
                    match_status=status,
                    source_data=src_dict,
                    match_score=0.0,
                )
            )
            continue

        tgt_dict = best_match.to_dict()
        discrepancies: Dict[str, Any] = {}
        all_cols = set(src_dict) | set(tgt_dict)

        for col in all_cols:
            sv, tv = src_dict.get(col), tgt_dict.get(col)
            if not _values_match(sv, tv, tolerance):
                discrepancies[col] = {"source": sv, "target": tv}

        if best_score == 1.0 and not discrepancies:
            status = MatchStatus.MATCHED
            matched += 1
        elif best_score >= 0.5:
            status = MatchStatus.PARTIAL
            partial += 1
        else:
            status = MatchStatus.UNMATCHED
            unmatched += 1

        results.append(
            ReconciliationRow(
                row_index=int(idx),
                match_status=status,
                source_data=src_dict,
                target_data=tgt_dict,
                discrepancies=discrepancies or None,
                match_score=round(best_score, 4),
            )
        )

    summary = {
        "total": len(results),
        "matched": matched,
        "partial": partial,
        "unmatched": unmatched,
    }
    return results, summary
