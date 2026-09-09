import io
from typing import Dict, List

import pandas as pd


def parse_excel(file_content: bytes, sheet_name: int | str = 0) -> pd.DataFrame:
    """Parse an Excel file (.xlsx / .xls) into a normalised DataFrame."""
    df = pd.read_excel(io.BytesIO(file_content), sheet_name=sheet_name, dtype=str)
    return _normalise(df)


def get_sheet_names(file_content: bytes) -> List[str]:
    xl = pd.ExcelFile(io.BytesIO(file_content))
    return xl.sheet_names


def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    df = df.dropna(how="all")
    return df.reset_index(drop=True)
