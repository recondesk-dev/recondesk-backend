from app.services.blocked_credit_checker import check_blocked_credits


def test_invoice_number_mapped_and_includes_hsn_category():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV1",
                "supplier_gstin": "27AAA",
                "hsn_code": "8703",
                "invoice_date": "2024-04-01",
                "total_tax_paise": 180_000,
            }
        ]
    )
    assert len(warnings) == 1
    w = warnings[0]
    assert w["invoice_number"] == "INV1"
    assert w["supplier_gstin"] == "27AAA"
    assert w["section"] == "17(5)"
    assert w["hsn_code"] == "8703"
    assert "Motor vehicles" in w["category"]
    assert w["invoice_date"] == "2024-04-01"
    assert w["amount"] == 1800.0
    assert "8703" in w["reason"]


def test_hsn_key_and_long_code_normalized():
    """Prefer ``hsn``; use first 4 digits like GSTR-2B line items."""
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV2",
                "supplier_gstin": "27BBB",
                "hsn": "87032100",
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["hsn_code"] == "8703"
    assert "8703" in warnings[0]["reason"]


def test_hsn_code_fallback_still_works():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV3",
                "supplier_gstin": "27CCC",
                "hsn_code": "9963",
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["hsn_code"] == "9963"
    assert "9963" in warnings[0]["reason"]


def test_hsn_from_items_when_top_level_missing():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV4",
                "supplier_gstin": "27DDD",
                "items": [{"hsn": "8703"}],
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["hsn_code"] == "8703"
    assert "8703" in warnings[0]["reason"]


def test_hsn_from_itm_det_nested():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number_norm": "INV5",
                "supplier_gstin_norm": "27EEE",
                "items": [{"num": 1, "itm_det": {"hsn_sc": "996311"}}],
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["hsn_code"] == "9963"
    assert "9963" in warnings[0]["reason"]


def test_blocked_itc_eligibility_value_is_ineligible():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV6",
                "supplier_gstin": "27FFF",
                "itc_eligibility": "Blocked",
                "invoice_date": "2024-05-10",
                "total_tax_paise": 50_000,
            }
        ]
    )
    assert len(warnings) == 1
    assert "ITC-ineligible" in warnings[0]["reason"]
    assert warnings[0]["hsn_code"] is None
    assert "ineligible" in warnings[0]["category"].lower()
    assert warnings[0]["invoice_date"] == "2024-05-10"
    assert warnings[0]["amount"] == 500.0


def test_hsn_2106_chapter_triggers_warning():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV7",
                "supplier_gstin": "27GGG",
                "hsn": "2106",
            }
        ]
    )
    assert len(warnings) == 1
    assert warnings[0]["hsn_code"] == "2106"
    assert "2106" in warnings[0]["reason"]
