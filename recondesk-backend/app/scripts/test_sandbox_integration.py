import json
import os
import sys
from pathlib import Path

# Add project root to sys.path so we can import app modules
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.sandbox_gst_client import (
    IMSResponse,
    Gstr2bResponse,
    _unwrap_sandbox_envelope,
    _parse_ims_section,
    IMS_SECTIONS
)
from app.parsers.gstr2b_parser import parse_gstr2b

FIXTURES_DIR = project_root / "test_fixtures" / "sandbox"

def test_ims_parsing():
    print("=== Testing IMS Parsing ===")
    file_path = FIXTURES_DIR / "sample_ims_response.json"
    
    with open(file_path, "r", encoding="utf-8") as f:
        raw_payload = json.load(f)
    
    inner = _unwrap_sandbox_envelope(raw_payload)
    sections_data = inner.get("data", {})
    
    all_invoices = []
    
    # In the mock, we have B2B and CN sections
    for section_upper in ["B2B", "CN", "DN"]:
        section_lower = section_upper.lower()
        entries = sections_data.get(section_lower, [])
        if entries:
            invoices = _parse_ims_section(section_lower, entries)
            all_invoices.extend(invoices)
            
    response = IMSResponse(invoices=all_invoices, raw_payload=raw_payload)
    
    print(f"Total IMS Invoices Parsed: {len(response.invoices)}")
    status_counts = response.status_counts()
    print("Counts by status:")
    for status, count in status_counts.items():
        print(f"  - {status}: {count}")
    
    # Print status map
    print("\nSample Invoice Status Map:")
    status_map = response.as_invoice_status_map()
    for inv_num, status in status_map.items():
        print(f"  {inv_num} -> {status}")
    print()

def test_gstr2b_parsing():
    print("=== Testing GSTR-2B Parsing ===")
    file_path = FIXTURES_DIR / "sample_gstr2b_response.json"
    
    with open(file_path, "r", encoding="utf-8") as f:
        raw_payload = json.load(f)
        
    inner = _unwrap_sandbox_envelope(raw_payload)
    gstn_data = inner.get("data") if isinstance(inner, dict) else inner
    
    if "data" in gstn_data and isinstance(gstn_data["data"], dict):
        gstn_payload = gstn_data
    else:
        gstn_payload = {"data": gstn_data}
        
    response = Gstr2bResponse(
        gstn_payload=gstn_payload,
        period_year=2024,
        period_month=11,
        gstin="27AABCU9603R1ZP",
        raw_payload=raw_payload
    )
    
    # Pass the payload directly to the existing parser
    parsed_result = parse_gstr2b(response.gstn_payload)
    
    print(f"Total GSTR-2B Invoices Parsed: {parsed_result['total_parsed']}")
    
    total_itc_paise = 0
    for record in parsed_result["records"]:
        items = record.get("items", [])
        for item in items:
            total_itc_paise += item.get("igst_paise", 0)
            total_itc_paise += item.get("cgst_paise", 0)
            total_itc_paise += item.get("sgst_paise", 0)
            total_itc_paise += item.get("cess_paise", 0)
            
    print(f"Total ITC Value (Rupees): {total_itc_paise / 100.0:.2f}")
    print()

if __name__ == "__main__":
    test_ims_parsing()
    test_gstr2b_parsing()
    print("All tests completed successfully!")
