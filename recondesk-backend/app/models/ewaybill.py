"""Pydantic Models and Enums for E-Way Bill Management (Government NIC Schema V1.03/V1.04)."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class TransportMode(str, Enum):
    ROAD = "1"
    RAIL = "2"
    AIR = "3"
    SHIP = "4"


class VehicleType(str, Enum):
    REGULAR = "R"
    OVER_DIMENSIONAL_CARGO = "O"


class SupplyType(str, Enum):
    OUTWARD = "O"
    INWARD = "I"


class SubSupplyType(str, Enum):
    SUPPLY = "1"
    IMPORT = "2"
    EXPORT = "3"
    JOB_WORK = "4"
    FOR_OWN_USE = "5"
    JOB_WORK_RETURNS = "6"
    SALES_RETURN = "7"
    OTHERS = "8"


class DocumentType(str, Enum):
    TAX_INVOICE = "INV"
    BILL_OF_SUPPLY = "BIL"
    BILL_OF_ENTRY = "BOE"
    DELIVERY_CHALLAN = "CHL"
    CREDIT_NOTE = "CNT"
    OTHERS = "OTH"


class EwayBillStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PART_A_ONLY = "PART_A_ONLY"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EwayBillItemInput(BaseModel):
    item_name: str
    description: Optional[str] = None
    hsn_code: str = Field(..., min_length=4, max_length=8)
    quantity: float = Field(..., gt=0)
    unit: str = "NOS"
    taxable_value: float = Field(..., ge=0)
    cgst_rate: float = 0.0
    cgst_amount: float = 0.0
    sgst_rate: float = 0.0
    sgst_amount: float = 0.0
    igst_rate: float = 0.0
    igst_amount: float = 0.0
    cess_rate: float = 0.0
    cess_amount: float = 0.0


class EwayBillCreateInput(BaseModel):
    client_gstin_id: str
    invoice_id: Optional[str] = None
    supply_type: SupplyType = SupplyType.OUTWARD
    sub_supply_type: SubSupplyType = SubSupplyType.SUPPLY
    sub_supply_desc: Optional[str] = None
    doc_type: DocumentType = DocumentType.TAX_INVOICE
    doc_number: str = Field(..., min_length=1, max_length=16)
    doc_date: date = Field(default_factory=date.today)

    # From (Consignor)
    from_gstin: str = Field(..., min_length=15, max_length=15)
    from_trade_name: str
    from_addr1: str
    from_addr2: Optional[str] = None
    from_place: str
    from_pincode: int
    from_state_code: str = Field(..., min_length=2, max_length=2)

    # To (Consignee)
    to_gstin: str = Field(..., min_length=3, max_length=15)  # Can be URP or GSTIN
    to_trade_name: str
    to_addr1: str
    to_addr2: Optional[str] = None
    to_place: str
    to_pincode: int
    to_state_code: str = Field(..., min_length=2, max_length=2)

    # Values
    total_taxable_value: float = Field(..., ge=0)
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    cess_amount: float = 0.0
    total_invoice_value: float = Field(..., gt=0)

    # Items
    items: List[EwayBillItemInput] = Field(..., min_length=1)

    # Part B (Transport Details)
    transporter_id: Optional[str] = None  # 15-char GSTIN/TRANSIN
    transporter_name: Optional[str] = None
    trans_mode: TransportMode = TransportMode.ROAD
    distance_km: int = Field(..., ge=1, le=4000)
    trans_doc_no: Optional[str] = None  # LR / RR / Airway Bill No
    trans_doc_date: Optional[date] = None
    vehicle_no: Optional[str] = None
    vehicle_type: VehicleType = VehicleType.REGULAR


class EwbFromInvoiceInput(BaseModel):
    client_gstin_id: str
    invoice_id: str
    transporter_id: Optional[str] = None
    transporter_name: Optional[str] = None
    trans_mode: TransportMode = TransportMode.ROAD
    distance_km: int = Field(..., ge=1, le=4000)
    trans_doc_no: Optional[str] = None
    trans_doc_date: Optional[date] = None
    vehicle_no: Optional[str] = None
    vehicle_type: VehicleType = VehicleType.REGULAR


class UpdateVehicleInput(BaseModel):
    ewb_number: str
    vehicle_no: str = Field(..., min_length=4, max_length=20)
    from_place: str
    from_state_code: str = Field(..., min_length=2, max_length=2)
    reason_code: str = Field(default="2", description="1-Breakdown, 2-Transshipment, 3-Others, 4-First Time")
    reason_remark: Optional[str] = None
    trans_doc_no: Optional[str] = None
    trans_doc_date: Optional[date] = None
    trans_mode: TransportMode = TransportMode.ROAD


class CancelEwayBillInput(BaseModel):
    ewb_number: str
    cancel_reason_code: str = Field(default="1", description="1-Duplicate, 2-Order Cancelled, 3-Data Entry Mistake, 4-Others")
    cancel_remarks: str = Field(..., min_length=3, max_length=100)


class EwayBillResponse(BaseModel):
    id: str
    client_gstin_id: str
    invoice_id: Optional[str] = None
    ewb_number: str
    ewb_date: datetime
    valid_until: Optional[datetime] = None
    status: EwayBillStatus = EwayBillStatus.ACTIVE
    doc_type: str
    doc_number: str
    doc_date: date
    supply_type: str
    sub_supply_type: str
    from_gstin: str
    from_trade_name: str
    to_gstin: str
    to_trade_name: str
    total_invoice_value: float
    distance_km: int
    transporter_id: Optional[str] = None
    transporter_name: Optional[str] = None
    trans_mode: str
    vehicle_no: Optional[str] = None
    vehicle_type: str
    qr_code: Optional[str] = None
    cancel_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
