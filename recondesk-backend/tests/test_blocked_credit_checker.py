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
    assert "9963" in warnings[0]["reason"]


def test_blocked_itc_eligibility_value_is_ineligible():
    warnings = check_blocked_credits(
        [
            {
                "invoice_number": "INV6",
                "supplier_gstin": "27FFF",
                "itc_eligibility": "Blocked",
            }
        ]
    )
    assert len(warnings) == 1
    assert "ITC-ineligible" in warnings[0]["reason"]


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
    assert "2106" in warnings[0]["reason"]
