import pandas as pd

from app.parsers.csv_parser import parse_csv
from app.parsers.excel_parser import parse_excel
from app.parsers.zip_batch_parser import parse_zip_to_dataframe

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".zip"}


def parse_file(file_content: bytes, file_name: str) -> pd.DataFrame:
    """Route to the correct parser based on file extension."""
    lower = file_name.lower()
    if lower.endswith((".xlsx", ".xls")):
        return parse_excel(file_content)
    if lower.endswith(".csv"):
        return parse_csv(file_content)
    if lower.endswith(".zip"):
        return parse_zip_to_dataframe(file_content)
    raise ValueError(
        f"Unsupported file type for '{file_name}'. "
        f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
    )
