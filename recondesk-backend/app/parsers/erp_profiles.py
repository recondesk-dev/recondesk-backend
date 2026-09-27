"""ERP column alias profiles and normalization helpers for ReconDesk.

Supports standard export conventions and field codes for:
- SAP ECC / S/4HANA (FBL1N, FBL5N, S_ALR, BKPF, BSEG, VBRK, RBKP)
- Oracle EBS / ERP Cloud / NetSuite
- Busy Accounting
- Zoho Books
"""

from __future__ import annotations

from typing import Any
import re
from app.parsers.tally_register import merge_aliases

# ---------------------------------------------------------------------------
# SAP Profiles
# ---------------------------------------------------------------------------
# Common SAP technical field names:
# BELNR: Accounting Document Number
# XBLNR: Reference Document Number (Vendor Invoice No in MM/FI)
# VBELN: Billing Document Number (Sales and Distribution)
# BUDAT: Posting Date
# BLDAT: Document Date
# CPUDT: Entry Date
# STCEG: Tax Registration Number / GSTIN
# STCD3: Tax Number 3 (Used for GSTIN in India SAP localization)
# NAME1: Name 1 (Vendor/Customer Name)
# LIFNR: Vendor Account Number
# KUNNR: Customer Account Number
# WRBTR: Amount in document currency
# DMBTR: Amount in local currency
# FWBAS / HWBAS: Tax Base Amount (Taxable Value)
# NETWR: Net Value
# WMWST / MWSTS / HWSTE: Tax Amount
# J_1ICGST / CGST_AMT / CGST_VAL: Central Tax
# J_1ISGST / SGST_AMT / SGST_VAL / UTGST_AMT: State/UT Tax
# J_1IIGST / IGST_AMT / IGST_VAL: Integrated Tax
# J_1ICESS / CESS_AMT / CESS_VAL: Cess Amount
# BLART: Document Type (KR=Vendor Inv, KG=Vendor Credit Memo, RE=Inv Receipt, DR=Customer Inv, DG=Customer Credit Memo)
# SHKZG: Debit/Credit indicator (S=Debit, H=Credit)

SAP_PURCHASE_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "stceg", "stcd3", "stcd1", "stcd2", "tax_number_3", "tax num 3",
        "tax reg no", "vat reg no", "stceg_l", "gstin_supplier",
    ],
    "invoice_number": [
        "xblnr", "belnr", "xblnr1", "ref doc", "reference document",
        "accounting doc", "accounting document", "fi doc no", "doc_no",
    ],
    "invoice_date": [
        "budat", "bldat", "cpudt", "posting_date", "document_date",
        "entry_date", "doc_date", "post_date",
    ],
    "taxable_amount": [
        "wrbtr", "dmbtr", "fwbas", "hwbas", "base_amount", "netwr",
        "tax_base", "taxable_base", "line_net_val",
    ],
    "igst": [
        "j_1iigst", "igst_amt", "igst_val", "igst_tax", "igst_amount",
    ],
    "cgst": [
        "j_1icgst", "cgst_amt", "cgst_val", "cgst_tax", "cgst_amount",
    ],
    "sgst": [
        "j_1isgst", "sgst_amt", "sgst_val", "sgst_tax", "sgst_amount", "utgst_amt",
    ],
    "cess": [
        "j_1icess", "cess_amt", "cess_val", "cess_amount",
    ],
    "total_tax": [
        "wmwst", "mwsts", "hwste", "tax_amount", "tot_tax",
    ],
    "total_amount": [
        "gross_amount", "total_val", "inv_val", "gross_val",
    ],
    "supplier_name": [
        "name1", "name2", "lifnr", "vendor_account", "party_desc", "name1_lifnr",
    ],
    "place_of_supply": [
        "regio", "region", "werks", "plant_state",
    ],
    "note_type": [
        "blart", "shkzg", "doc_type", "document_type", "shkzg_debit_credit",
    ],
}

SAP_SALES_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "stceg", "stcd3", "stcd1", "stcd2", "tax_number_3", "tax num 3",
        "vat reg no", "customer_gstin",
    ],
    "invoice_number": [
        "vbeln", "belnr", "xblnr", "billing_document", "billing_doc",
        "sales_doc", "invoice_doc",
    ],
    "invoice_date": [
        "fkdat", "budat", "bldat", "billing_date", "posting_date",
        "doc_date",
    ],
    "taxable_amount": [
        "netwr", "wrbtr", "dmbtr", "fwbas", "hwbas", "base_amount",
    ],
    "igst": [
        "j_1iigst", "igst_amt", "igst_val", "igst_tax", "igst_amount",
    ],
    "cgst": [
        "j_1icgst", "cgst_amt", "cgst_val", "cgst_tax", "cgst_amount",
    ],
    "sgst": [
        "j_1isgst", "sgst_amt", "sgst_val", "sgst_tax", "sgst_amount", "utgst_amt",
    ],
    "cess": [
        "j_1icess", "cess_amt", "cess_val", "cess_amount",
    ],
    "total_tax": [
        "wmwst", "mwsts", "hwste", "tax_amount",
    ],
    "total_amount": [
        "gross_amount", "total_val", "inv_val", "gross_val",
    ],
    "recipient_name": [
        "name1", "name2", "kunnr", "customer_account", "customer_name",
    ],
    "place_of_supply": [
        "regio", "region", "werks", "destination_state",
    ],
    "invoice_type": [
        "blart", "fkart", "doc_type", "billing_type", "shkzg",
    ],
}

# ---------------------------------------------------------------------------
# Oracle Cloud / EBS / NetSuite Profiles
# ---------------------------------------------------------------------------

ORACLE_PURCHASE_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "tax_registration_number", "tax reg no", "party_tax_reg_no",
        "vendor_tax_reg_no", "party tax profile", "tax_reg_num",
    ],
    "invoice_number": [
        "trx_number", "trx_num", "invoice_num", "doc_sequence_value",
        "trx no", "ap_invoice_num", "voucher_num",
    ],
    "invoice_date": [
        "trx_date", "gl_date", "doc_date", "invoice_date", "accounting_date",
    ],
    "taxable_amount": [
        "line_amount", "taxable_amount", "base_amount", "amount_applied",
        "assessable_value", "net_amount",
    ],
    "total_tax": [
        "tax_amount", "total_tax_amount", "tax_amt",
    ],
    "total_amount": [
        "invoice_amount", "total_trx_amount", "gross_amount", "invoice total",
    ],
    "igst": ["igst_amount", "igst_amt", "igst_tax_amount"],
    "cgst": ["cgst_amount", "cgst_amt", "cgst_tax_amount"],
    "sgst": ["sgst_amount", "sgst_amt", "sgst_tax_amount"],
    "cess": ["cess_amount", "cess_amt"],
    "supplier_name": [
        "vendor_name", "party_name", "supplier_party_name", "vendor_site_code",
    ],
    "place_of_supply": [
        "tax_jurisdiction", "place_of_supply", "ship_to_state",
    ],
}

ORACLE_SALES_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "tax_registration_number", "tax reg no", "party_tax_reg_no",
        "customer_tax_reg_no", "party tax profile", "tax_reg_num",
    ],
    "invoice_number": [
        "trx_number", "trx_num", "invoice_num", "doc_sequence_value",
        "ar_invoice_num", "trx no",
    ],
    "invoice_date": [
        "trx_date", "gl_date", "doc_date", "invoice_date", "accounting_date",
    ],
    "taxable_amount": [
        "line_amount", "taxable_amount", "base_amount", "amount_applied",
        "assessable_value", "net_sales",
    ],
    "total_tax": [
        "tax_amount", "total_tax_amount", "tax_amt",
    ],
    "total_amount": [
        "invoice_amount", "total_trx_amount", "gross_amount", "invoice total",
    ],
    "igst": ["igst_amount", "igst_amt", "igst_tax_amount"],
    "cgst": ["cgst_amount", "cgst_amt", "cgst_tax_amount"],
    "sgst": ["sgst_amount", "sgst_amt", "sgst_tax_amount"],
    "cess": ["cess_amount", "cess_amt"],
    "recipient_name": [
        "customer_name", "party_name", "bill_to_customer_name", "cust_name",
    ],
    "place_of_supply": [
        "tax_jurisdiction", "place_of_supply", "ship_to_state",
    ],
}

# ---------------------------------------------------------------------------
# Busy Accounting Profiles
# ---------------------------------------------------------------------------

BUSY_PURCHASE_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "party gstin", "party gst no", "dealer gstin", "vendor gstin", "party tin",
    ],
    "invoice_number": [
        "bill no.", "bill no", "vch no.", "vch no", "voucher no.", "voucher no",
    ],
    "invoice_date": [
        "bill date", "bill dt.", "vch date", "vch dt.", "voucher date",
    ],
    "taxable_amount": [
        "taxable amt", "taxable amt.", "taxable value", "taxable amount",
    ],
    "igst": ["igst amt", "igst amt.", "igst tax"],
    "cgst": ["cgst amt", "cgst amt.", "central tax"],
    "sgst": ["sgst amt", "sgst amt.", "state tax", "utgst amt"],
    "cess": ["cess amt", "cess amt."],
    "total_amount": [
        "total amt", "total amt.", "vch amount", "bill amount", "net amount",
    ],
    "supplier_name": [
        "party name", "party's name", "account", "party",
    ],
}

BUSY_SALES_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "party gstin", "party gst no", "buyer gstin", "customer gstin",
    ],
    "invoice_number": [
        "bill no.", "bill no", "vch no.", "vch no", "sale bill no", "sale inv no",
    ],
    "invoice_date": [
        "bill date", "bill dt.", "vch date", "vch dt.", "sale date",
    ],
    "taxable_amount": [
        "taxable amt", "taxable amt.", "taxable value", "taxable amount",
    ],
    "igst": ["igst amt", "igst amt.", "igst tax"],
    "cgst": ["cgst amt", "cgst amt.", "central tax"],
    "sgst": ["sgst amt", "sgst amt.", "state tax", "utgst amt"],
    "cess": ["cess amt", "cess amt."],
    "total_amount": [
        "total amt", "total amt.", "vch amount", "bill amount", "net amount",
    ],
    "recipient_name": [
        "party name", "party's name", "account", "party", "customer name",
    ],
}

# ---------------------------------------------------------------------------
# Zoho Books Profiles
# ---------------------------------------------------------------------------

ZOHO_PURCHASE_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gst identification number (gstin)", "gstin", "vendor gstin",
    ],
    "invoice_number": [
        "bill number", "bill#", "bill no", "vendor invoice number",
    ],
    "invoice_date": [
        "bill date", "date",
    ],
    "taxable_amount": [
        "taxable amount", "subtotal", "sub total", "item total",
    ],
    "total_amount": [
        "total", "balance due", "bill amount",
    ],
    "igst": ["igst (rs.)", "igst (rs)", "igst 18%", "igst 12%", "igst 5%", "igst 28%"],
    "cgst": ["cgst (rs.)", "cgst (rs)", "cgst 9%", "cgst 6%", "cgst 2.5%", "cgst 14%"],
    "sgst": ["sgst (rs.)", "sgst (rs)", "sgst 9%", "sgst 6%", "sgst 2.5%", "sgst 14%"],
    "cess": ["cess (rs.)", "cess (rs)"],
    "supplier_name": ["vendor name", "vendor's name"],
    "place_of_supply": ["destination state (pos)", "place of supply"],
}

ZOHO_SALES_ALIASES: dict[str, list[str]] = {
    "gstin": [
        "gst identification number (gstin)", "gstin", "customer gstin",
    ],
    "invoice_number": [
        "invoice number", "invoice#", "inv#",
    ],
    "invoice_date": [
        "invoice date", "date",
    ],
    "taxable_amount": [
        "taxable amount", "subtotal", "sub total", "item total",
    ],
    "total_amount": [
        "total", "balance due", "invoice amount",
    ],
    "igst": ["igst (rs.)", "igst (rs)", "igst 18%", "igst 12%", "igst 5%", "igst 28%"],
    "cgst": ["cgst (rs.)", "cgst (rs)", "cgst 9%", "cgst 6%", "cgst 2.5%", "cgst 14%"],
    "sgst": ["sgst (rs.)", "sgst (rs)", "sgst 9%", "sgst 6%", "sgst 2.5%", "sgst 14%"],
    "cess": ["cess (rs.)", "cess (rs)"],
    "recipient_name": ["customer name", "customer's name"],
    "place_of_supply": ["destination state (pos)", "place of supply"],
}


def combine_alias_maps(*maps: dict[str, list[str]]) -> dict[str, list[str]]:
    """Iteratively merge multiple alias dictionaries preserving order without duplicates."""
    if not maps:
        return {}
    res = dict(maps[0])
    for m in maps[1:]:
        res = merge_aliases(res, m)
    return res


# Combined ERP aliases
ERP_PURCHASE_ALIASES: dict[str, list[str]] = combine_alias_maps(
    SAP_PURCHASE_ALIASES,
    ORACLE_PURCHASE_ALIASES,
    BUSY_PURCHASE_ALIASES,
    ZOHO_PURCHASE_ALIASES,
)

ERP_SALES_ALIASES: dict[str, list[str]] = combine_alias_maps(
    SAP_SALES_ALIASES,
    ORACLE_SALES_ALIASES,
    BUSY_SALES_ALIASES,
    ZOHO_SALES_ALIASES,
)


def is_erp_credit_note(
    doc_type_raw: Any,
    shkzg_raw: Any = None,
    is_sales: bool = False,
) -> bool:
    """Detect if an ERP document type or Debit/Credit indicator signifies a Credit Note."""
    dt = str(doc_type_raw).strip().upper() if doc_type_raw is not None else ""
    shk = str(shkzg_raw).strip().upper() if shkzg_raw is not None else ""

    # SAP Document Types (BLART)
    # KG: Vendor Credit Memo
    # DG: Customer Credit Memo
    # KN: Vendor Net Credit Memo
    # RE-C: Return / Credit
    if dt in ("KG", "KN", "RE-C", "CREDIT MEMO", "CREDIT_MEMO", "CRN", "CN", "CREDIT NOTE"):
        return True
    if is_sales and dt in ("DG", "G2", "CREDIT MEMO", "CRN", "CN"):
        return True

    # Debit / Credit indicator (SHKZG):
    # In SAP FI Customer Line Item: Invoice is Debit ('S'), Credit Memo is Credit ('H')
    if is_sales and shk == "H":
        return True
    if not is_sales and shk == "S" and dt in ("KG", "CREDIT", "CR", "KN"):
        return True

    return False
