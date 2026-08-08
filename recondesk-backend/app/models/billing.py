from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.models.base import StrictModel


# --- Existing SaaS Subscription Models ---
class PlanType(str, Enum):
    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"
    TRIALING = "trialing"


class CreateOrderRequest(StrictModel):
    plan: PlanType
    billing_period: str = Field(
        default="monthly", max_length=32, description="monthly or yearly"
    )


class OrderResponse(StrictModel):
    order_id: str
    amount: int  # paise
    currency: str = "INR"
    razorpay_key: str


class SubscriptionResponse(StrictModel):
    id: UUID
    user_id: UUID
    plan: PlanType
    status: SubscriptionStatus
    current_period_start: datetime
    current_period_end: datetime
    razorpay_subscription_id: Optional[str] = None

    model_config = {"from_attributes": True}  # type: ignore[assignment]  # noqa: C408


# --- E-Invoicing / Billing Module Models (Phase 1) ---
class ItemType(str, Enum):
    GOODS = "goods"
    SERVICE = "service"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"


# --- Company Profiles ---
class CompanyProfileBase(BaseModel):
    legal_name: str
    trade_name: Optional[str] = None
    address_line1: str
    address_line2: Optional[str] = None
    city: str
    state: str
    state_code: str = Field(..., min_length=2, max_length=2)
    pincode: str
    gstin: str
    pan: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    invoice_number_prefix: str = ""
    invoice_number_next_seq: int = 1
    financial_year_reset: bool = True


class CompanyProfileCreate(CompanyProfileBase):
    client_gstin_id: str


class CompanyProfileUpdate(BaseModel):
    legal_name: Optional[str] = None
    trade_name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    invoice_number_prefix: Optional[str] = None
    invoice_number_next_seq: Optional[int] = None
    financial_year_reset: Optional[bool] = None


class CompanyProfileResponse(CompanyProfileBase):
    id: str
    client_gstin_id: str
    created_at: datetime
    updated_at: datetime


# --- Customers ---
class CustomerBase(BaseModel):
    name: str
    gstin: Optional[str] = None
    address_line1: str = ""
    address_line2: Optional[str] = None
    city: str = ""
    state: str = ""
    state_code: str = Field(..., min_length=2, max_length=2)
    pincode: str = ""
    is_b2b: bool = True


class CustomerCreate(CustomerBase):
    client_gstin_id: str


class CustomerUpdate(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    state_code: Optional[str] = None
    pincode: Optional[str] = None
    is_b2b: Optional[bool] = None


class CustomerResponse(CustomerBase):
    id: str
    client_gstin_id: str
    created_at: datetime
    updated_at: datetime


# --- Items ---
class ItemBase(BaseModel):
    name: str
    hsn_or_sac_code: str
    unit: str = "NOS"
    default_rate: int = 0  # paise
    default_tax_rate_percent: float = 18.00
    item_type: ItemType = ItemType.GOODS


class ItemCreate(ItemBase):
    client_gstin_id: str


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    hsn_or_sac_code: Optional[str] = None
    unit: Optional[str] = None
    default_rate: Optional[int] = None
    default_tax_rate_percent: Optional[float] = None
    item_type: Optional[ItemType] = None


class ItemResponse(ItemBase):
    id: str
    client_gstin_id: str
    created_at: datetime
    updated_at: datetime


# --- Invoice Line Items ---
class InvoiceLineItemInput(BaseModel):
    item_id: Optional[str] = None
    description: str
    hsn_or_sac_code: str
    quantity: float = Field(gt=0, default=1.0)
    unit: str = "NOS"
    rate_paise: int = Field(ge=0)
    discount_percent: float = Field(default=0.0, ge=0, le=100)
    tax_rate_percent: float = Field(default=18.0, ge=0, le=100)
    cess_paise: int = Field(default=0, ge=0)


class InvoiceLineItemResponse(BaseModel):
    id: str
    invoice_id: str
    item_id: Optional[str] = None
    description: str
    hsn_or_sac_code: str
    quantity: float
    unit: str
    rate_paise: int
    discount_percent: float
    taxable_value_paise: int
    cgst_rate_percent: float
    cgst_paise: int
    sgst_rate_percent: float
    sgst_paise: int
    igst_rate_percent: float
    igst_paise: int
    cess_paise: int
    line_total_paise: int


# --- Invoices ---
class InvoiceCreateInput(BaseModel):
    client_gstin_id: str
    company_profile_id: str
    customer_id: str
    invoice_date: date
    due_date: Optional[date] = None
    place_of_supply: Optional[str] = None  # state_code
    notes: Optional[str] = None
    line_items: List[InvoiceLineItemInput] = Field(..., min_items=1)


class InvoiceUpdateInput(BaseModel):
    customer_id: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    place_of_supply: Optional[str] = None
    notes: Optional[str] = None
    line_items: Optional[List[InvoiceLineItemInput]] = None


class InvoiceResponse(BaseModel):
    id: str
    client_gstin_id: str
    company_profile_id: str
    customer_id: str
    invoice_number: str
    invoice_date: date
    due_date: Optional[date] = None
    place_of_supply: str
    is_interstate: bool
    subtotal_paise: int
    total_tax_paise: int
    total_paise: int
    status: InvoiceStatus
    irn: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class InvoiceDetailResponse(InvoiceResponse):
    company_profile: Optional[CompanyProfileResponse] = None
    customer: Optional[CustomerResponse] = None
    line_items: List[InvoiceLineItemResponse] = []
