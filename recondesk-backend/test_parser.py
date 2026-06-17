import io
import openpyxl
from app.parsers.purchase_register_parser import parse_purchase_register

def make_xlsx(headers, rows, blank_first_row=False):
    wb = openpyxl.Workbook()
    ws = wb.active
    # Default name "Sheet" is skipped by the parser (matches "sheet" in skip list).
    ws.title = "Register"
    if blank_first_row:
        ws.append([])
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

# Test 1 - Tally export
print("\nTest 1 - Tally export...")
data = make_xlsx(
    ['Voucher Type','Supplier GSTIN','Invoice No','Invoice Date','Taxable Value','IGST Amount','CGST Amount','SGST Amount','Grand Total'],
    [
        ['Purchase','27AAPFU0939F1ZV','INV-001','01-04-2024',10000,1800,0,0,11800],
        ['Purchase','27AAPFU0939F1ZV','INV-002','02-04-2024',20000,3600,0,0,23600],
    ]
)
result = parse_purchase_register(data, 'tally_export.xlsx')
if result['success'] and result['source_software'] == 'Tally' and result['valid_rows'] == 2:
    print("PASS — source_software=Tally, valid_rows=2")
else:
    print(f"FAIL — {result}")

# Test 2 - Non-standard headers
print("\nTest 2 - Non-standard headers...")
data = make_xlsx(
    ['GSTIN (Mandatory)','Inv No.','Bill Date','Net Amount','Total'],
    [
        ['27AAPFU0939F1ZV','INV-001','01-04-2024',10000,11800],
        ['27AAPFU0939F1ZV','INV-002','02-04-2024',20000,23600],
    ]
)
result = parse_purchase_register(data, 'nonstandard.xlsx')
if result['success'] and 'gstin' in result['detected_columns'] and 'invoice_number' in result['detected_columns']:
    print("PASS — gstin and invoice_number detected from non-standard headers")
else:
    print(f"FAIL — detected_columns: {result.get('detected_columns')}, error: {result.get('error')}")

# Test 3 - Header on row 2
print("\nTest 3 - Header on row 2...")
data = make_xlsx(
    ['Supplier GSTIN','Invoice No','Invoice Date','Taxable Value','Grand Total'],
    [
        ['27AAPFU0939F1ZV','INV-001','01-04-2024',10000,11800],
    ],
    blank_first_row=True
)
result = parse_purchase_register(data, 'header_row2.xlsx')
if result['success'] and result['valid_rows'] > 0:
    print("PASS — header on row 2 detected, data parsed correctly")
else:
    print(f"FAIL — {result}")

# Test 4 - Invoice number as integer
print("\nTest 4 - Invoice number stored as integer...")
data = make_xlsx(
    ['Supplier GSTIN','Invoice No','Invoice Date','Taxable Value','Grand Total'],
    [
        ['27AAPFU0939F1ZV', 1, '01-04-2024', 10000, 11800],
    ]
)
result = parse_purchase_register(data, 'int_invoice.xlsx')
if result['success'] and result['records'] and result['records'][0]['invoice_number'] == '1':
    print("PASS — integer invoice number normalized to string '1'")
else:
    actual = result['records'][0]['invoice_number'] if result.get('records') else 'no records'
    print(f"FAIL — invoice_number was: {actual}")

# Test 5 - CSV row-level multi-error validation and empty row
print("\nTest 5 - CSV multi-error + empty row...")
csv_input = b"""GSTIN of Supplier,Inv / No,Bill Dt.,Value
29AABCU9603R1ZX,INV-017,15-11-2024,50000
BADGSTIN,INV-018,INVALIDDATE,ABC
, , ,
"""
result = parse_purchase_register(csv_input, "test.csv")
expected_errors = [
    "Row 3: invalid GSTIN, invalid date, invalid value",
    "Row 4: empty row",
]
if (
    result["success"]
    and result["valid_rows"] == 1
    and result["errors"] == expected_errors
):
    print("PASS — valid_rows=1, combined errors and empty row reported")
else:
    print(f"FAIL — valid_rows={result.get('valid_rows')}, errors={result.get('errors')}")

print("\nDone.")
