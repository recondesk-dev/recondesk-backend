import pytest
from app.parsers.gstr3b_parser import parse_gstr3b, ParseError

def test_parse_gstr3b_empty_string_itc_section():
    """Regression test: if GST portal returns empty strings instead of lists for ITC,
    it should not crash _sum_rows but safely coerce to empty lists."""
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {
                "itcAvl": "",  # portal sometimes does this instead of []
                "itcRev": [""], # what if list contains a string?
                "itcNet": None, # another edge case
                "itcInelg": "some_random_string"
            },
            "sup_details": {
                "osup_det": ""
            }
        }
    }
    
    parsed = parse_gstr3b(raw)
    
    # Assert itc_avl, itc_rev, itc_net are safely parsed as 0
    assert parsed["itc_avl"]["igst"] == 0.0
    assert parsed["itc_rev"]["igst"] == 0.0
    assert parsed["itc_net"]["igst"] == 0.0
    assert parsed["itc_inelg"]["igst"] == 0.0

    # Ensure outward supply is also safely handled
    assert parsed["outward_supply"]["igst"] == 0.0

def test_parse_gstr3b_dict_itc_section():
    """Test that a GSTR-3B with dicts instead of lists for ITC sections correctly wraps them and sums them."""
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {
                "itcAvl": {"iamt": 100.0, "camt": 50.0, "samt": 50.0},
                "itcNet": {"iamt": 100.0, "camt": 50.0, "samt": 50.0}
            }
        }
    }
    parsed = parse_gstr3b(raw)
    assert parsed["itc_avl"]["igst"] == 100.0
    assert parsed["itc_avl"]["cgst"] == 50.0
    assert parsed["itc_net"]["sgst"] == 50.0

def test_parse_gstr3b_unsupported_schema():
    """Test that missing ITC section entirely raises ParseError."""
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "sup_details": {}
        }
    }
    with pytest.raises(ParseError) as exc_info:
        parse_gstr3b(raw)
    assert "Unsupported schema" in str(exc_info.value)
