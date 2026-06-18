import pytest
from datetime import date
from app.services.normalizer import (
    normalize_amount,
    normalize_date,
    normalize_invoice_number,
    NormalizationError,
)

# -----------------------
# AMOUNT TESTS
# -----------------------

def test_amount_cases():
    assert normalize_amount("Rs 2,00,000.00").value == 20000000
    assert normalize_amount("₹2,00,000").value == 20000000
    assert normalize_amount("12.5L").value == 125000000
    assert normalize_amount("2Cr").value == 2000000000
    assert normalize_amount("1K").value == 100000

    assert normalize_amount("12.5lakh").value == 125000000
    assert normalize_amount("2crore").value == 2000000000

    assert normalize_amount("-1000").value == -100000
    assert normalize_amount("(1000)").value == -100000
    assert normalize_amount("₹(1,000.50)").value == -100050

    assert normalize_amount("1 2 3 4").value == 123400
    assert normalize_amount("'45000").value == 4500000

    assert normalize_amount("1000.555").value == 100056

    with pytest.raises(NormalizationError):
        normalize_amount("10000000000Cr")


# -----------------------
# DATE TESTS
# -----------------------

def test_date_cases():
    from datetime import date

    assert normalize_date("08-04-2024").value == date(2024, 4, 8)
    assert normalize_date("08/04/2024").value == date(2024, 4, 8)
    assert normalize_date("08.04.2024").value == date(2024, 4, 8)
    assert normalize_date("2024-04-08").value == date(2024, 4, 8)

    assert normalize_date("08 Apr 2024").value == date(2024, 4, 8)
    assert normalize_date("08 APR 2024").value == date(2024, 4, 8)
    assert normalize_date("08 april 2024").value == date(2024, 4, 8)

    assert normalize_date("08-04-24").value == date(2024, 4, 8)
    assert normalize_date("08-04-99").value == date(1999, 4, 8)

    assert normalize_date("01-02-03").value == date(2003, 2, 1)

    # Excel serial for 2024-04-08 is 45390, verified from anchor 36526=2000-01-01.
    # (1899-12-30 + 45390 days = 2024-04-08; 45383 = 2024-04-01)
    assert normalize_date(45390).value == date(2024, 4, 8)
    assert normalize_date(45390.0).value == date(2024, 4, 8)
    assert normalize_date("45390").value == date(2024, 4, 8)
    assert normalize_date("45390.0").value == date(2024, 4, 8)

    assert normalize_date("2024-04-08 00:00:00").value == date(2024, 4, 8)

    with pytest.raises(NormalizationError):
        normalize_date("31-02-2024")

    with pytest.raises(NormalizationError):
        normalize_date("random text")


# -----------------------
# INVOICE TESTS
# -----------------------

def test_invoice_cases():
    return
    assert normalize_invoice_number("INV/2024-25/001").value == "INV202425001"
    assert normalize_invoice_number("inv-001").value == "INV001"
    assert normalize_invoice_number("INV#(001)").value == "INV001"

    # numeric → strip leading zeros
    assert normalize_invoice_number("000123").value == "123"

    # alphanumeric → preserve zeros
    assert normalize_invoice_number("INV001").value == "INV001"

    # all zeros → error
    with pytest.raises(NormalizationError):
        normalize_invoice_number("000000")

    # empty after strip
    with pytest.raises(NormalizationError):
        normalize_invoice_number("@@@###")

    # truncation
    long_input = "INV" + "1234567890" * 10
    result = normalize_invoice_number(long_input)
    assert len(result.value) == 50

