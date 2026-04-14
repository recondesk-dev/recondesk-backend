import json

# 🔧 TEMP: Monkey patch normalize_gstin BEFORE importing parser
import app.services.normalizer as normalizer

def bypass_gstin(gstin):
    return gstin

normalizer.normalize_gstin = bypass_gstin


# Now import parser (after patch)
from app.parsers.gstr2b_parser import parse_gstr2b


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

# Convert to bytes
file_content = json.dumps(sample).encode("utf-8")

# Run parser
result = parse_gstr2b(file_content)

print("\n=== RESULT ===")
print(json.dumps(result, default=str, indent=2))
