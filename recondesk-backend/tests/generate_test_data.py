"""
Synthetic GSTR-2B + Purchase Register dataset
Covers common real-world edge cases for stress testing
"""
import json
from datetime import date, timedelta

GSTIN_A = "27ABCDE1234F1Z5"
GSTIN_B = "27XYZAB5678G2Z9"
GSTIN_C = "29PQRST9012H3Z8"
GSTIN_D = "33MNOPQ3456I4Z7"

def d(s): return s  # keep as string for realism

gstr2b_records = [

    # ── CLEAN MATCHES (should reconcile perfectly) ────────────────────────────
    {"id":"g001","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024001",
     "invoice_date":"2024-03-15","taxable_amount_paise":100000,"total_tax_paise":18000,
     "hsn_code":"9983","note":"clean match"},{"id":"g002","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024002",
     "invoice_date":"2024-03-20","taxable_amount_paise":200000,"total_tax_paise":36000,
     "hsn_code":"9983","note":"clean match"},

    {"id":"g003","supplier_gstin":GSTIN_B,"invoice_number_normalized":"BILL001",
     "invoice_date":"2024-03-10","taxable_amount_paise":500000,"total_tax_paise":90000,
     "hsn_code":"9954","note":"works contract -- Section 17(5) warning expected"},

    # ── INVOICE NUMBER VARIATIONS (fuzzy match expected) ──────────────────────
    {"id":"g004","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024003",
     "invoice_date":"2024-03-18","taxable_amount_paise":150000,"total_tax_paise":27000,
     "hsn_code":"9983","note":"PR has INV/2024/003 -- needs normalization"}, {"id":"g005","supplier_gstin":GSTIN_B,"invoice_number_normalized":"TAX00123",
     "invoice_date":"2024-03-22","taxable_amount_paise":75000,"total_tax_paise":13500,
     "hsn_code":"9983","note":"PR has TAX-00123 -- dash variant"},

    # ── AMOUNT VARIATIONS (near match) ────────────────────────────────────────
    {"id":"g006","supplier_gstin":GSTIN_C,"invoice_number_normalized":"RC2024001",
     "invoice_date":"2024-03-05","taxable_amount_paise":300000,"total_tax_paise":54000,
     "hsn_code":"9983","note":"PR amount off by Rs20 -- rounding difference"},

    {"id":"g007","supplier_gstin":GSTIN_C,"invoice_number_normalized":"RC2024002",
     "invoice_date":"2024-03-12","taxable_amount_paise":450000,"total_tax_paise":81000,
     "hsn_code":"8703","note":"motor vehicle -- Section 17(5) warning expected"},

    # ── MISSING INVOICE DATE (edge case) ──────────────────────────────────────
    {"id":"g008","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024004",
     "invoice_date":None,"taxable_amount_paise":80000,"total_tax_paise":14400,
     "hsn_code":"9983","note":"missing invoice date -- should not crash"},  # ── DUPLICATE INVOICE NUMBERS (same supplier) ─────────────────────────────
    {"id":"g009","supplier_gstin":GSTIN_B,"invoice_number_normalized":"INV001",
     "invoice_date":"2024-03-01","taxable_amount_paise":120000,"total_tax_paise":21600,
     "hsn_code":"9963","note":"duplicate invoice number -- first occurrence"},

    {"id":"g010","supplier_gstin":GSTIN_B,"invoice_number_normalized":"INV001",
     "invoice_date":"2024-03-15","taxable_amount_paise":130000,"total_tax_paise":23400,
     "hsn_code":"9963","note":"duplicate invoice number -- second occurrence, different amount"},

    # ── LATE FILING (cross-period) ────────────────────────────────────────────
    {"id":"g011","supplier_gstin":GSTIN_D,"invoice_number_normalized":"FEB2024001",
     "invoice_date":"2024-02-10","taxable_amount_paise":200000,"total_tax_paise":36000,
     "hsn_code":"9983","note":"February invoice appearing in March GSTR-2B -- late filing"},

    {"id":"g012","supplier_gstin":GSTIN_D,"invoice_number_normalized":"JAN2024001",
     "invoice_date":"2024-01-05","taxable_amount_paise":350000,"total_tax_paise":63000,
     "hsn_code":"9983","note":"January invoice in March GSTR-2B -- 2 months late"},

    # ── CREDIT NOTES ──────────────────────────────────────────────────────────
    {"id":"g013","supplier_gstin":GSTIN_A,"invoice_number_normalized":"CN2024001",
     "invoice_date":"2024-03-25","taxable_amount_paise":-50000,"total_tax_paise":-9000,
     "hsn_code":"9983","note":"credit note -- negative amount"},
	{"id":"g014","supplier_gstin":GSTIN_C,"invoice_number_normalized":"CRN001",
     "invoice_date":"2024-03-28","taxable_amount_paise":30000,"total_tax_paise":5400,
     "hsn_code":"9983","note":"credit note -- CN prefix"},

    # ── ZERO AMOUNT (edge case) ────────────────────────────────────────────────
    {"id":"g015","supplier_gstin":GSTIN_B,"invoice_number_normalized":"NIL001",
     "invoice_date":"2024-03-30","taxable_amount_paise":0,"total_tax_paise":0,
     "hsn_code":"9983","note":"zero amount invoice -- nil rated supply"},

    # ── GSTIN MISMATCH (should not match) ────────────────────────────────────
    {"id":"g016","supplier_gstin":"INVALID_GSTIN","invoice_number_normalized":"INV999",
     "invoice_date":"2024-03-15","taxable_amount_paise":100000,"total_tax_paise":18000,
     "hsn_code":"9983","note":"invalid GSTIN -- should go to missed ITC"},

    # ── LARGE AMOUNT (stress test) ────────────────────────────────────────────
    {"id":"g017","supplier_gstin":GSTIN_C,"invoice_number_normalized":"BULK001",
     "invoice_date":"2024-03-20","taxable_amount_paise":10000000,"total_tax_paise":1800000,
     "hsn_code":"9983","note":"large amount Rs1 lakh tax -- stress test"},# ── SPECIAL CHARACTERS IN INVOICE (normalization test) ────────────────────
    {"id":"g018","supplier_gstin":GSTIN_D,"invoice_number_normalized":"GST/2024/MAR/001",
     "invoice_date":"2024-03-14","taxable_amount_paise":175000,"total_tax_paise":31500,
     "hsn_code":"9983","note":"special chars in invoice number"},

    # ── NO MATCH (true missed ITC) ────────────────────────────────────────────
    {"id":"g019","supplier_gstin":GSTIN_A,"invoice_number_normalized":"GHOST001",
     "invoice_date":"2024-03-10","taxable_amount_paise":250000,"total_tax_paise":45000,
     "hsn_code":"9983","note":"no PR record exists -- true missed ITC"},

    {"id":"g020","supplier_gstin":GSTIN_B,"invoice_number_normalized":"GHOST002",
     "invoice_date":"2024-03-18","taxable_amount_paise":180000,"total_tax_paise":32400,
     "hsn_code":"9995","note":"club membership -- Section 17(5) + missed ITC"},
]

pr_records = [

    # ── CLEAN MATCHES ─────────────────────────────────────────────────────────
    {"id":"p001","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024001",
     "invoice_date":"2024-03-15","taxable_amount_paise":100000,"total_tax_paise":18000},

    {"id":"p002","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024002",
     "invoice_date":"2024-03-20","taxable_amount_paise":200000,"total_tax_paise":36000},

    {"id":"p003","supplier_gstin":GSTIN_B,"invoice_number_normalized":"BILL001",
     "invoice_date":"2024-03-10","taxable_amount_paise":500000,"total_tax_paise":90000},

    # ── INVOICE NUMBER VARIANTS ───────────────────────────────────────────────
    {"id":"p004","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV20240003",
     "invoice_date":"2024-03-18","taxable_amount_paise":150000,"total_tax_paise":27000},

    {"id":"p005","supplier_gstin":GSTIN_B,"invoice_number_normalized":"TAX00123",
     "invoice_date":"2024-03-22","taxable_amount_paise":75000,"total_tax_paise":13500},

    # ── AMOUNT VARIANTS ───────────────────────────────────────────────────────
    {"id":"p006","supplier_gstin":GSTIN_C,"invoice_number_normalized":"RC2024001",
     "invoice_date":"2024-03-05","taxable_amount_paise":302000,"total_tax_paise":54360},

    {"id":"p007","supplier_gstin":GSTIN_C,"invoice_number_normalized":"RC2024002",
     "invoice_date":"2024-03-12","taxable_amount_paise":450000,"total_tax_paise":81000},

    # ── MISSING DATE IN PR ────────────────────────────────────────────────────
    {"id":"p008","supplier_gstin":GSTIN_A,"invoice_number_normalized":"INV2024004",
     "invoice_date":None,"taxable_amount_paise":80000,"total_tax_paise":14400}, # ── DUPLICATE INVOICE -- different amounts ────────────────────────────────
    {"id":"p009","supplier_gstin":GSTIN_B,"invoice_number_normalized":"INV001",
     "invoice_date":"2024-03-01","taxable_amount_paise":120000,"total_tax_paise":21600},

    {"id":"p010","supplier_gstin":GSTIN_B,"invoice_number_normalized":"INV001",
     "invoice_date":"2024-03-15","taxable_amount_paise":130000,"total_tax_paise":23400},

    # ── CROSS-PERIOD PR RECORDS ───────────────────────────────────────────────
    {"id":"p011","supplier_gstin":GSTIN_D,"invoice_number_normalized":"FEB2024001",
     "invoice_date":"2024-02-10","taxable_amount_paise":200000,"total_tax_paise":36000},

    {"id":"p012","supplier_gstin":GSTIN_D,"invoice_number_normalized":"JAN2024001",
     "invoice_date":"2024-01-05","taxable_amount_paise":350000,"total_tax_paise":63000},

    # ── LARGE AMOUNT ──────────────────────────────────────────────────────────
    {"id":"p013","supplier_gstin":GSTIN_C,"invoice_number_normalized":"BULK001",
     "invoice_date":"2024-03-20","taxable_amount_paise":10000000,"total_tax_paise":1800000},

    # ── SPECIAL CHARS ─────────────────────────────────────────────────────────
    {"id":"p014","supplier_gstin":GSTIN_D,"invoice_number_normalized":"GST20240MAR001",
     "invoice_date":"2024-03-14","taxable_amount_paise":175000,"total_tax_paise":31500},

    # ── WRONGFUL ITC RISK (PR with no GSTR) ──────────────────────────────────
    {"id":"p015","supplier_gstin":GSTIN_A,"invoice_number_normalized":"EXTRA001",
     "invoice_date":"2024-03-08","taxable_amount_paise":90000,"total_tax_paise":16200},

    {"id":"p016","supplier_gstin":GSTIN_C,"invoice_number_normalized":"EXTRA002",
     "invoice_date":"2024-03-22","taxable_amount_paise":110000,"total_tax_paise":19800},
]

payment_records = [
    {"invoice_id":"p001","payment_date":"2024-04-10","amount_paid_paise":100000},
    {"invoice_id":"p002","payment_date":"2024-04-15","amount_paid_paise":200000},
    {"invoice_id":"p003","payment_date":"2024-09-20","amount_paid_paise":500000},  # PAID_LATE {"invoice_id":"p006","payment_date":"2024-05-01","amount_paid_paise":150000},  # partial
    {"invoice_id":"p007","payment_date":"2024-04-20","amount_paid_paise":450000},
    {"invoice_id":"p013","payment_date":"2024-04-25","amount_paid_paise":10000000},
]

if __name__ == "__main__":
    print(f"GSTR-2B records: {len(gstr2b_records)}")
    print(f"PR records: {len(pr_records)}")
    print(f"Payment records: {len(payment_records)}")
    with open("tests/synthetic_gstr2b.json", "w") as f:
        json.dump(gstr2b_records, f, indent=2)
    with open("tests/synthetic_pr.json", "w") as f:
        json.dump(pr_records, f, indent=2)
    with open("tests/synthetic_payments.json", "w") as f:
        json.dump(payment_records, f, indent=2)
    print("Files written to tests/")
