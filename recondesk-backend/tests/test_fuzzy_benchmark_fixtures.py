"""Tests for fuzzy benchmark fixtures (stress-testing multi-sheet Excel ingestion,
repeated headers, and CDNR note number extraction).
"""

from pathlib import Path
import pytest
from app.parsers.gstr2b_excel import load_gstr2b_upload_payload
from app.parsers.gstr2b_parser import parse_gstr2b
from app.parsers.purchase_register_parser import (
    detect_column_mapping,
    parse_purchase_register,
)
from app.services.reconciliation_import_wizard.wizard_service import _read_pr_dataframe
from app.services import client_import_mapping as cim


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = WORKSPACE_ROOT / "benchmark_data"
GSTR2B_FILE = BENCHMARK_DIR / "ReconDesk_GSTR2B_3000_Fuzzy.xlsx"
PR_FILE = BENCHMARK_DIR / "ReconDesk_Purchase_Register_3000_Fuzzy.xlsx"


@pytest.mark.skipif(not GSTR2B_FILE.exists(), reason="GSTR2B fuzzy fixture missing")
def test_gstr2b_fuzzy_fixture_parsing():
    with open(GSTR2B_FILE, "rb") as f:
        raw = f.read()

    payload = load_gstr2b_upload_payload(raw, "ReconDesk_GSTR2B_3000_Fuzzy.xlsx")
    res = parse_gstr2b(payload)

    # 3,070 total rows (2,910 B2B + 80 CDNR + 80 B2BA) should all parse with 0 skips
    assert res["total_parsed"] == 3070
    assert res["total_skipped"] == 0
    assert not res["metrics"].get("skip_breakdown", {})


@pytest.mark.skipif(not PR_FILE.exists(), reason="PR fuzzy fixture missing")
def test_purchase_register_fuzzy_fixture_dataframe_read():
    with open(PR_FILE, "rb") as f:
        raw = f.read()

    df = _read_pr_dataframe(raw, "ReconDesk_Purchase_Register_3000_Fuzzy.xlsx")
    # Must pick the 'Purchase Dump Apr-Sep' sheet (3180 rows, 22 cols), NOT 'READ ME' (9 rows, 2 cols)
    assert len(df) > 3000
    assert len(df.columns) >= 14

    headers = [str(h).strip() for h in df.columns.tolist()]
    assert cim.columns_match_expected_schema(headers) is True

    mapping = detect_column_mapping(df)
    assert "gstin" in mapping
    assert "invoice_number" in mapping
    assert "invoice_date" in mapping
    assert "taxable_amount" in mapping


@pytest.mark.skipif(not PR_FILE.exists(), reason="PR fuzzy fixture missing")
def test_purchase_register_fuzzy_fixture_full_parse():
    with open(PR_FILE, "rb") as f:
        raw = f.read()

    res = parse_purchase_register(raw, "ReconDesk_Purchase_Register_3000_Fuzzy.xlsx")
    assert res.get("valid_rows") == 3173
    # Master and decoy sheets should be skipped and not combined into invoices
    sheets_used = [s["sheet"] for s in res.get("sheets_used", [])]
    assert sheets_used == ["Purchase Dump Apr-Sep"]
