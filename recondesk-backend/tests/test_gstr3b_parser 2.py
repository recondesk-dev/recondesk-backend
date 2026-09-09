from app.parsers.gstr3b_parser import parse_gstr3b

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

    # Additive fields: omitted 3.1(b–e) / Table 5 / late fee → zeros / empty
    assert parsed["osup_zero"]["taxable_value"] == 0.0
    assert parsed["osup_nil_exmp"]["taxable_value"] == 0.0
    assert parsed["isup_rev"]["igst"] == 0.0
    assert parsed["osup_nongst"]["taxable_value"] == 0.0
    assert parsed["inward_sup"] == []
    assert parsed["late_fee"]["cgst"] == 0.0
    assert parsed["interest_late_fee"]["igst"] == 0.0
    for ty in ("IMPG", "IMPS", "ISRC", "ISD", "OTH"):
        assert ty in parsed["itc_avl_by_source"]
        assert parsed["itc_avl_by_source"][ty]["igst"] == 0.0


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
    # Dict without ty → OTH bucket
    assert parsed["itc_avl_by_source"]["OTH"]["igst"] == 100.0


def test_parse_gstr3b_missing_itc_defaults_to_zero():
    """Missing itcElg is valid — ITC heads default to zeros (GSTR-1 tie-out uploads)."""
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "sup_details": {
                "osup_det": {
                    "txval": 1000,
                    "iamt": 180,
                    "camt": 0,
                    "samt": 0,
                    "csamt": 0,
                }
            }
        },
    }
    parsed = parse_gstr3b(raw)
    assert parsed["outward_supply"]["taxable_value"] == 1000.0
    assert parsed["outward_supply"]["igst"] == 180.0
    assert parsed["itc_avl"] == {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}
    assert parsed["itc_net"] == {"igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0}


def test_parse_gstr3b_top_level_sup_details_only():
    """Portal-style slice with top-level sup_details and no data/itcElg wrapper."""
    raw = {
        "gstin": "27ODNLV7602A5ZL",
        "ret_period": "042025",
        "sup_details": {
            "osup_det": {
                "txval": 437091848.82,
                "iamt": 24053615.55,
                "camt": 18040211.66,
                "samt": 18040211.66,
                "csamt": 0,
            }
        },
    }
    parsed = parse_gstr3b(raw)
    assert parsed["gstin"] == "27ODNLV7602A5ZL"
    assert parsed["ret_period"] == "2025-04"
    assert parsed["outward_supply"]["taxable_value"] == 437091848.82
    assert parsed["outward_supply"]["cgst"] == 18040211.66


def test_omitted_optional_tables_default_to_zero():
    """Missing 3.1(b–e), Table 5, and 5.1 must not fail — zeros / empty lists."""
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "072026",
        "data": {
            "itcElg": {
                "itcAvl": [],
                "itcNet": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            },
            "sup_details": {
                "osup_det": {"txval": 1000, "iamt": 180, "camt": 0, "samt": 0, "csamt": 0},
                # intentionally omit osup_zero, osup_nil_exmp, isup_rev, osup_nongst
            },
            # no inward_sup, no intr_ltfee
        },
    }
    parsed = parse_gstr3b(raw)
    assert parsed["outward_supply"]["taxable_value"] == 1000.0
    assert parsed["outward_supply"]["igst"] == 180.0
    assert parsed["osup_zero"] == {
        "taxable_value": 0.0, "igst": 0.0, "cgst": 0.0, "sgst": 0.0, "cess": 0.0,
    }
    assert parsed["osup_nil_exmp"]["taxable_value"] == 0.0
    assert parsed["isup_rev"]["igst"] == 0.0
    assert parsed["osup_nongst"]["taxable_value"] == 0.0
    assert parsed["inward_sup"] == []
    assert parsed["interest_late_fee"]["cgst"] == 0.0
    assert parsed["late_fee"]["cgst"] == 0.0
    assert parsed["late_fee"]["sgst"] == 0.0


def test_parses_3_1_b_through_e_and_table_5_and_late_fee():
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "072026",
        "data": {
            "itcElg": {
                "itcAvl": [
                    {"ty": "IMPG", "iamt": 10, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "All other ITC", "iamt": 0, "camt": 40, "samt": 40, "csamt": 0},
                ],
                "itcNet": {"iamt": 10, "camt": 40, "samt": 40, "csamt": 0},
            },
            "sup_details": {
                "osup_det": {"txval": 1000, "iamt": 100, "camt": 50, "samt": 50, "csamt": 0},
                "osup_zero": {"txval": 595400.04, "iamt": 0, "csamt": 0},
                "osup_nil_exmp": {"txval": 250},
                "isup_rev": {"txval": 100, "iamt": 18, "camt": 0, "samt": 0, "csamt": 0},
                "osup_nongst": {"txval": 75},
            },
            "inward_sup": {
                "isup_details": [
                    {"ty": "GST", "inter": 10, "intra": 20},
                    {"ty": "NONGST", "inter": 5, "intra": 0},
                ]
            },
            "intr_ltfee": {
                "intr_details": {"iamt": 1, "camt": 2, "samt": 2, "csamt": 0},
                "ltfee_details": {"camt": 25, "samt": 25},
            },
        },
    }
    parsed = parse_gstr3b(raw)

    # 3.1(a) unchanged
    assert parsed["outward_supply"]["taxable_value"] == 1000.0
    assert parsed["outward_supply"]["igst"] == 100.0

    assert parsed["osup_zero"]["taxable_value"] == 595400.04
    assert parsed["osup_nil_exmp"]["taxable_value"] == 250.0
    assert parsed["isup_rev"]["igst"] == 18.0
    assert parsed["osup_nongst"]["taxable_value"] == 75.0

    assert parsed["inward_sup"] == [
        {"ty": "GST", "inter": 10.0, "intra": 20.0},
        {"ty": "NONGST", "inter": 5.0, "intra": 0.0},
    ]

    assert parsed["interest_late_fee"]["igst"] == 1.0
    assert parsed["interest_late_fee"]["cgst"] == 2.0
    assert parsed["late_fee"]["cgst"] == 25.0
    assert parsed["late_fee"]["sgst"] == 25.0

    # Lump sums unchanged + by-source breakdown with All other ITC → OTH
    assert parsed["itc_avl"]["igst"] == 10.0
    assert parsed["itc_avl"]["cgst"] == 40.0
    assert parsed["itc_avl_by_source"]["IMPG"]["igst"] == 10.0
    assert parsed["itc_avl_by_source"]["OTH"]["cgst"] == 40.0
    assert parsed["itc_avl_by_source"]["OTH"]["sgst"] == 40.0
    assert parsed["itc_avl_by_source"]["IMPS"]["igst"] == 0.0
    assert parsed["itc_net"]["cgst"] == 40.0


def test_itc_avl_by_source_normalizes_oth_alias():
    raw = {
        "gstin": "27AABCM4162G1ZM",
        "ret_period": "052026",
        "data": {
            "itcElg": {
                "itcAvl": [
                    {"ty": "OTH", "iamt": 5, "camt": 0, "samt": 0, "csamt": 0},
                    {"ty": "All other ITC", "iamt": 7, "camt": 0, "samt": 0, "csamt": 0},
                ],
                "itcNet": {"iamt": 12, "camt": 0, "samt": 0, "csamt": 0},
            }
        },
    }
    parsed = parse_gstr3b(raw)
    assert parsed["itc_avl_by_source"]["OTH"]["igst"] == 12.0
    assert parsed["itc_avl"]["igst"] == 12.0
