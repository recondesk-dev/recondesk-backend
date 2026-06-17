import json

# Sample data
sample = {
    "data": {
        "gstin": "27ABCDE1234F1Z5",
        "rtnprd": "042024",
        "gendt": "2024-05-10",
        "b2b": [
            {
                "ctin": "29ABCDE1234F2Z5",  # doesn't matter now
                "inv": [
                    {
                        "inum": "INV001",
                        "dt": "2024-04-10",
                        "val": "1000",
                        "pos": "27",
                        "rev": "N",
                        "itcavl": "Y",
                        "itms": [
                            {
                                "rt": "18",
                                "txval": "1000",
                                "igst": "180",
                                "cgst": "0",
                                "sgst": "0",
                                "cess": "0"
                            }
                        ]
                    }
                ]
            }
        ]
    }
}


def test_parse_gstr2b_sample_with_invalid_fixture_gstins(monkeypatch):
    """Use scoped patching so invalid fixture GSTINs do not leak into other tests."""
    import app.parsers.gstr2b_parser as parser

    monkeypatch.setattr(parser, "normalize_gstin", lambda gstin: gstin)

    file_content = json.dumps(sample).encode("utf-8")
    result = parser.parse_gstr2b(file_content)

    assert result["total_parsed"] == 1
    assert result["total_skipped"] == 0
    assert result["records"][0]["invoice_number"] == "INV001"
