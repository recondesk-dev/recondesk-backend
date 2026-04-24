from app.services.blocked_credit_checker import check_blocked_credits


def test_invoice_number_mapped_and_strict_schema():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV1",
                "supplier_gstin": "27AAA",
                "hsn_code": "8703",
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["invoice_number"] == "INV1"
    assert warnings[0]["supplier_gstin"] == "27AAA"
    assert warnings[0]["section"] == "17(5)"
    assert set(warnings[0].keys()) == {
        "invoice_number",
        "supplier_gstin",
        "reason",
        "section",
    }
    assert "8703" in warnings[0]["reason"]
