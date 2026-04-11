import pandas as pd

from app.parsers.csv_parser import parse_csv
from app.parsers.excel_parser import parse_excel

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


def parse_file(file_content: bytes, file_name: str) -> pd.DataFrame:
    """Route to the correct parser based on file extension."""
    lower = file_name.lower()
    if lower.endswith((".xlsx", ".xls")):
        return parse_excel(file_content)
    if lower.endswith(".csv"):
        return parse_csv(file_content)
    raise ValueError(
        f"Unsupported file type for '{file_name}'. "
        f"Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
    )
