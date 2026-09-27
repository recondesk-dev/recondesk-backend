import io
from typing import Optional

import pandas as pd


def parse_csv(
    file_content: bytes,
    encoding: str = "utf-8",
    delimiter: Optional[str] = None,
) -> pd.DataFrame:
    """
    Parse a CSV file into a normalised DataFrame.
    Auto-detects delimiter when not provided (comma or tab).
    """
    text = file_content.decode(encoding, errors="replace")

    if delimiter is None:
        first_line = text.split("\n", 1)[0]
        counts = {
            ",": first_line.count(","),
            ";": first_line.count(";"),
            "\t": first_line.count("\t"),
            "|": first_line.count("|"),
        }
        delimiter = max(counts, key=counts.get) if any(counts.values()) else ","

    df = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str)
    return _normalise(df)


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    return df.reset_index(drop=True)
