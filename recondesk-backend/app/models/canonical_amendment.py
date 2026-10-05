from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class CanonicalAmendment:
    """Canonical domain representation of an amended transaction (Table 9A/9B/9C)."""

    document_type: str  # "INVOICE", "CREDIT_NOTE", "DEBIT_NOTE"
    recipient_gstin: str | None

    original_invoice_number: str | None
    original_invoice_date: str | None

    amended_invoice_number: str | None
    amended_invoice_date: str | None

    # Values in Rupees (float, 2 decimals)
    original_taxable: float
    amended_taxable: float
    delta_taxable: float

    original_igst: float
    amended_igst: float
    delta_igst: float

    original_cgst: float
    amended_cgst: float
    delta_cgst: float

    original_sgst: float
    amended_sgst: float
    delta_sgst: float

    original_cess: float
    amended_cess: float
    delta_cess: float

    # Exact values in Paise (integers)
    original_taxable_paise: int
    amended_taxable_paise: int
    delta_taxable_paise: int

    original_igst_paise: int
    amended_igst_paise: int
    delta_igst_paise: int

    original_cgst_paise: int
    amended_cgst_paise: int
    delta_cgst_paise: int

    original_sgst_paise: int
    amended_sgst_paise: int
    delta_sgst_paise: int

    original_cess_paise: int
    amended_cess_paise: int
    delta_cess_paise: int

    amendment_type: str  # "VALUE_AMENDMENT", "DATE_AMENDMENT", "INVOICE_NUMBER_AMENDMENT", "NO_CHANGE"

    source_period: str | None
    filing_period: str | None

    original_found: bool
    original_source: str | None  # "SALES_REGISTER", "PRIOR_GSTR1", None

    chain_id: str | None
    chain_position: int  # 1-indexed
    is_latest_effective_amendment: bool

    source_record: dict[str, Any] | None = None
    amendment_record: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "recipient_gstin": self.recipient_gstin,
            "original_invoice_number": self.original_invoice_number,
            "original_invoice_date": self.original_invoice_date,
            "amended_invoice_number": self.amended_invoice_number,
            "amended_invoice_date": self.amended_invoice_date,
            "original_taxable": self.original_taxable,
            "amended_taxable": self.amended_taxable,
            "delta_taxable": self.delta_taxable,
            "original_igst": self.original_igst,
            "amended_igst": self.amended_igst,
            "delta_igst": self.delta_igst,
            "original_cgst": self.original_cgst,
            "amended_cgst": self.amended_cgst,
            "delta_cgst": self.delta_cgst,
            "original_sgst": self.original_sgst,
            "amended_sgst": self.amended_sgst,
            "delta_sgst": self.delta_sgst,
            "original_cess": self.original_cess,
            "amended_cess": self.amended_cess,
            "delta_cess": self.delta_cess,
            "original_taxable_paise": self.original_taxable_paise,
            "amended_taxable_paise": self.amended_taxable_paise,
            "delta_taxable_paise": self.delta_taxable_paise,
            "original_igst_paise": self.original_igst_paise,
            "amended_igst_paise": self.amended_igst_paise,
            "delta_igst_paise": self.delta_igst_paise,
            "original_cgst_paise": self.original_cgst_paise,
            "amended_cgst_paise": self.amended_cgst_paise,
            "delta_cgst_paise": self.delta_cgst_paise,
            "original_sgst_paise": self.original_sgst_paise,
            "amended_sgst_paise": self.amended_sgst_paise,
            "delta_sgst_paise": self.delta_sgst_paise,
            "original_cess_paise": self.original_cess_paise,
            "amended_cess_paise": self.amended_cess_paise,
            "delta_cess_paise": self.delta_cess_paise,
            "amendment_type": self.amendment_type,
            "source_period": self.source_period,
            "filing_period": self.filing_period,
            "original_found": self.original_found,
            "original_source": self.original_source,
            "chain_id": self.chain_id,
            "chain_position": self.chain_position,
            "is_latest_effective_amendment": self.is_latest_effective_amendment,
        }
