# Phase 5.7 REM-06 Audit: Vendor Follow-Up Template Token Sanitization & Fallbacks

**Author**: Senior Software Engineer / Auditor  
**Date**: September 22, 2026  
**Status**: AUDITED & PLANNED  
**Scope**: `recondesk-backend/app/services/vendor_followup_engine.py`, `recondesk-backend/app/routers/vendor_followup.py`, `recondesk-frontend/lib/vendorFollowupApi.ts`, `recondesk-backend/tests/test_vendor_followup_engine.py`

---

## 1. Executive Summary & Problem Statement

In **Phase 5.7 Audit [FINDING-M03]**, an audit of the automated vendor follow-up engine identified suboptimal template rendering when vendor master fields are missing, null, or whitespace:
1. **Redundant & Bare GSTIN Salutations**:
   When `supplier_name` is omitted, `None`, or empty, `sname` currently falls back to `supplier_gstin`. In both WhatsApp and Email notices, this produces:
   `Dear 27ABCDE1234F1Z5 (27ABCDE1234F1Z5)`
   and in HTML email:
   `<p>Dear <strong>27ABCDE1234F1Z5</strong> (GSTIN: <code>27ABCDE1234F1Z5</code>),</p>`
2. **Whitespace-Only Value Exploits**:
   If `supplier_name` is whitespace (e.g., `"   "`), `supplier_name or supplier_gstin` evaluates to `"   "` (truthy in Python), generating:
   `Dear     (27ABCDE1234F1Z5)`
3. **Missing Token Sanitization Fallbacks**:
   When template texts or custom notices utilize placeholder tokens (e.g., `{supplier_contact}`, `{supplier_trade_name}`, `{contact_person}`), missing master values result in raw bracket placeholders leaking into outbound customer/vendor communications (e.g., `"Dear {supplier_contact}, ..."`).
4. **Lack of Trade Name vs. Legal Name Hierarchy**:
   The engine does not distinguish between a vendor's trade name (dba) and legal entity name, nor does it provide a clean fallback hierarchy: `trade_name -> legal_name -> "Valued Supplier"`.

---

## 2. Code Audit: Current Implementation

### 2.1 File: `recondesk-backend/app/services/vendor_followup_engine.py`
Lines 140–160:
```python
def generate_whatsapp_payload(
    supplier_gstin: str,
    supplier_name: str,
    vendor_phone: str,
    at_risk_itc_rupees: float,
    template_type: str = "POLITE_REMINDER",
) -> dict[str, str]:
    phone_clean = "".join(c for c in vendor_phone if c.isdigit())
    if len(phone_clean) == 10:
        phone_clean = f"91{phone_clean}"

    sname = supplier_name or supplier_gstin
    ...
```
Lines 211–220:
```python
def generate_email_template(
    supplier_gstin: str,
    supplier_name: str,
    at_risk_itc_rupees: float,
    template_type: str = "POLITE_REMINDER",
) -> dict[str, str]:
    sname = supplier_name or supplier_gstin
    ...
```

### 2.2 File: `recondesk-backend/app/routers/vendor_followup.py`
Lines 30–45:
```python
class WhatsAppGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    vendor_phone: Optional[str] = ""
    at_risk_itc_rupees: float = 0.0
    template_type: str = "POLITE_REMINDER"

class EmailGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    supplier_gstin: str
    supplier_name: Optional[str] = None
    at_risk_itc_rupees: float = 0.0
    template_type: str = "POLITE_REMINDER"
```

---

## 3. Statutory & Professional Requirements

Under Indian GST communication norms, communication sent from CAs and tax teams to external vendors should:
1. Address the recipient professionally:
   - If contact person is known: `"Dear {contact_person} ({trade_name or legal_name})"`
   - If only company name is known: `"Dear {trade_name or legal_name} ({gstin})"`
   - If company name is missing or identical to GSTIN: `"Dear Valued Supplier ({gstin})"` (never duplicate GSTIN in name and parenthesis).
2. Fall back `{supplier_contact}` to `"Accounts Payable Team"`.
3. Fall back `{supplier_trade_name}` to `legal_name`, then `"Valued Supplier"`.
4. Fall back `{supplier_name}` to `trade_name`, then `"Valued Supplier"`.
5. Scrub any lingering `{token}` patterns before payload serialization so brackets are never sent to vendors or WhatsApp deep links.

---

## 4. Architectural Design & Proposed Solution

### 4.1 Token Resolution & Fallback Hierarchy

```
[Target Token]            [Primary Source]       [Fallback 1]        [Final Fallback]
{supplier_contact}     -> contact_person      -> "Accounts Payable Team"
{supplier_trade_name}  -> trade_name          -> supplier_name    -> "Valued Supplier"
{supplier_name}        -> supplier_name       -> trade_name       -> "Valued Supplier"
{supplier_gstin}       -> supplier_gstin (15-char uppercase)      -> "—"
{at_risk_itc}          -> f"₹{at_risk_itc_rupees:,.2f}"
```

### 4.2 Helper Functions in `vendor_followup_engine.py`

1. **`resolve_supplier_display_name(supplier_name: Optional[str], trade_name: Optional[str], supplier_gstin: str) -> str`**:
   - Strips whitespace.
   - If `trade_name` is non-empty and `!= supplier_gstin`: return `trade_name`.
   - If `supplier_name` is non-empty and `!= supplier_gstin`: return `supplier_name`.
   - If both are missing, whitespace, or equal to `supplier_gstin`: return `"Valued Supplier"`.

2. **`resolve_salutation(supplier_name: Optional[str], trade_name: Optional[str], contact_person: Optional[str], supplier_gstin: str) -> str`**:
   - If `contact_person` is present and valid: return `f"Dear {contact_person} ({display_name})"` or `f"Dear {contact_person} / Accounts Payable Team ({display_name})"`.
   - Else: return `f"Dear {display_name} ({supplier_gstin})"`.

3. **`sanitize_template_tokens(template_text: str, context: dict[str, str]) -> str`**:
   - Performs case-insensitive dictionary substitution for standard tokens:
     `{supplier_contact}`, `{contact_person}`, `{supplier_trade_name}`, `{trade_name}`, `{supplier_name}`, `{legal_name}`, `{supplier_gstin}`, `{at_risk_itc}`, `{at_risk_itc_rupees}`.
   - Applies regex pass `re.sub(r"\{[a-zA-Z0-9_-]+\}", "", text)` (or clean replacement) to eliminate unmapped token residues.

---

## 5. Non-Breaking Backward Compatibility Guarantees

1. **No Database Schema Migrations**:
   All changes are purely in memory during string sanitization and payload formatting.
2. **Backward Compatible API Signatures**:
   New parameters (`trade_name`, `contact_person`, `custom_template`) are fully optional with `None` defaults.
3. **Existing Callers**:
   Existing tests and frontend calls passing only `(supplier_gstin, supplier_name, ...)` continue to succeed, but receive cleaner salutations without duplicate GSTIN strings.

---

## 6. Audit Verdict
**PROCEED TO IMPLEMENTATION PLAN**. The design addresses [FINDING-M03] completely and safely without touching database tables or breaking contracts.
