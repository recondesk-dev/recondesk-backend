import io
from typing import Optional

import pandas as pd


from app.parsers.resilient_recovery import sanitize_csv_bytes


def parse_csv(
    file_content: bytes,
    encoding: str = "utf-8",
    delimiter: Optional[str] = None,
) -> pd.DataFrame:
    """
    Parse a CSV file into a normalised DataFrame.
    Auto-detects delimiter when not provided (comma or tab).
    Sanitizes embedded null bytes, unclosed quotes, and jagged truncated lines.
    """
    clean_text, _ = sanitize_csv_bytes(file_content, encoding=encoding)

    if delimiter is None:
        first_line = clean_text.split("\n", 1)[0]
        counts = {
            ",": first_line.count(","),
            ";": first_line.count(";"),
            "\t": first_line.count("\t"),
            "|": first_line.count("|"),
        }
        delimiter = max(counts, key=counts.get) if any(counts.values()) else ","

    try:
        df = pd.read_csv(io.StringIO(clean_text), sep=delimiter, dtype=str, on_bad_lines="skip")
    except Exception:
        df = pd.read_csv(io.StringIO(clean_text), sep=None, engine="python", dtype=str, on_bad_lines="skip")
    return _normalise(df)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    return df.reset_index(drop=True)
