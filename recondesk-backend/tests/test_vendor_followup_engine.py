"""Unit tests for Automated Vendor Follow-up Engine (Phase 5.7 REM-06).

Verifies:
1. Standard template rendering (POLITE_REMINDER, RULE37_NOTICE, FINAL_ESCALATION, MISSING_2B_REQUEST, VALUE_MISMATCH_VERIFICATION).
2. Missing / empty / None supplier name falls back cleanly to 'Valued Supplier' without duplicate GSTIN.
3. Whitespace-only supplier name is trimmed and falls back safely to 'Valued Supplier'.
4. Supplier name identical to GSTIN is rejected in favor of 'Valued Supplier'.
5. Trade name hierarchy: trade_name preferred over legal supplier_name when both present.
6. Contact person salutation formatting: 'Dear {contact_person} ({display_name})'.
7. Token sanitization fallbacks:
   - {supplier_contact} / {contact_person} -> 'Accounts Payable Team'
   - {supplier_trade_name} -> legal name -> 'Valued Supplier'
   - {supplier_name} -> trade name -> 'Valued Supplier'
   - {at_risk_itc} -> formatted INR currency
8. Unmapped/residual {token} placeholders are scrubbed so raw brackets are never leaked to external vendors.
9. Custom template rendering with token replacements.
"""

from app.services.vendor_followup_engine import (
    DEFAULT_CONTACT_FALLBACK,
    DEFAULT_SUPPLIER_NAME_FALLBACK,
    generate_whatsapp_payload,
    generate_email_template,
    resolve_supplier_display_name,
    resolve_contact_salutation,
    sanitize_template_tokens,
)


def test_generate_whatsapp_payload_polite_reminder():
    res = generate_whatsapp_payload(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Acme Solutions Pvt Ltd",
        vendor_phone="9876543210",
        at_risk_itc_rupees=145000.50,
        template_type="POLITE_REMINDER",
    )
    assert res["supplier_gstin"] == "27ABCDE1234F1Z5"
    assert res["vendor_phone"] == "919876543210"
    assert "145,000.50" in res["message_text"]
    assert "https://wa.me/919876543210?text=" in res["whatsapp_url"]


def test_generate_whatsapp_payload_rule37_notice():
    res = generate_whatsapp_payload(
        supplier_gstin="27XYZAB9876K1Z9",
        supplier_name="Global Traders",
        vendor_phone="+91-9988776655",
        at_risk_itc_rupees=89200.00,
        template_type="RULE37_NOTICE",
    )
    assert "Rule 37 Overdue Tax Risk" in res["message_text"]
    assert "18% interest" in res["message_text"]
    assert "https://wa.me/919988776655?text=" in res["whatsapp_url"]


def test_generate_email_template():
    res = generate_email_template(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Acme Solutions",
        at_risk_itc_rupees=50000.00,
        template_type="FINAL_ESCALATION",
    )
    assert "Notice: GST Reconciliation" in res["subject"]
    assert "₹50,000.00" in res["html_body"]
    assert "Acme Solutions" in res["html_body"]


# ---------------------------------------------------------------------------
# Phase 5.7 REM-06 Focused Tests
# ---------------------------------------------------------------------------

def test_missing_supplier_name_falls_back_to_valued_supplier_no_duplicate_gstin():
    """Ensure missing supplier name does NOT render 'Dear 27ABC... (27ABC...)', but 'Dear Valued Supplier (27ABC...)'."""
    gstin = "27ABCDE1234F1Z5"
    res = generate_whatsapp_payload(
        supplier_gstin=gstin,
        supplier_name=None,
        vendor_phone="9876543210",
        at_risk_itc_rupees=35000.0,
        template_type="POLITE_REMINDER",
    )
    # Must NOT have duplicate GSTIN in salutation
    assert f"Dear {gstin} ({gstin})" not in res["message_text"]
    assert f"Dear Valued Supplier ({gstin})" in res["message_text"]
    assert res["supplier_name"] == DEFAULT_SUPPLIER_NAME_FALLBACK

    email_res = generate_email_template(
        supplier_gstin=gstin,
        supplier_name=None,
        at_risk_itc_rupees=35000.0,
        template_type="POLITE_REMINDER",
    )
    assert f"Dear <strong>{gstin}</strong> (GSTIN: <code>{gstin}</code>)" not in email_res["html_body"]
    assert f"Dear <strong>Valued Supplier</strong> (GSTIN: <code>{gstin}</code>)" in email_res["html_body"]


def test_whitespace_supplier_name_falls_back_cleanly():
    """Ensure whitespace-only supplier name trims and falls back to 'Valued Supplier'."""
    gstin = "29AABCT1332L1ZV"
    res = generate_whatsapp_payload(
        supplier_gstin=gstin,
        supplier_name="    ",
        vendor_phone="9876543210",
        at_risk_itc_rupees=12000.0,
    )
    assert "Dear   " not in res["message_text"]
    assert f"Dear Valued Supplier ({gstin})" in res["message_text"]


def test_supplier_name_equals_gstin_falls_back_to_valued_supplier():
    """When supplier_name is passed identically to GSTIN, fall back to avoid redundant duplicate display."""
    gstin = "07AAAAA0000A1Z5"
    res = generate_whatsapp_payload(
        supplier_gstin=gstin,
        supplier_name=gstin,
        vendor_phone="9876543210",
        at_risk_itc_rupees=5000.0,
    )
    assert f"Dear {gstin} ({gstin})" not in res["message_text"]
    assert f"Dear Valued Supplier ({gstin})" in res["message_text"]


def test_contact_person_salutation_formatting():
    """When contact_person is provided, salutation includes the contact person."""
    res = generate_whatsapp_payload(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Tata Steel Limited",
        contact_person="Ramesh Sharma",
        vendor_phone="9876543210",
        at_risk_itc_rupees=250000.0,
    )
    assert "Dear Ramesh Sharma (Tata Steel Limited)" in res["message_text"]

    email = generate_email_template(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Tata Steel Limited",
        contact_person="Ramesh Sharma",
        at_risk_itc_rupees=250000.0,
    )
    assert "Dear <strong>Ramesh Sharma</strong> (Tata Steel Limited / GSTIN: <code>27ABCDE1234F1Z5</code>)" in email["html_body"]


def test_trade_name_preferred_over_supplier_name_when_both_present():
    """trade_name takes precedence for supplier display name."""
    disp = resolve_supplier_display_name(
        supplier_name="Apex Global Technologies Private Limited",
        trade_name="Apex Tech",
        supplier_gstin="27ABCDE1234F1Z5",
    )
    assert disp == "Apex Tech"


def test_token_sanitization_supplier_contact_fallback_accounts_payable():
    """{supplier_contact} placeholder without contact person falls back to 'Accounts Payable Team'."""
    text = "Attention {supplier_contact}: please review overdue invoices for {supplier_trade_name}."
    context = {
        "supplier_gstin": "27ABCDE1234F1Z5",
        "supplier_name": "Zenith Industries",
    }
    sanitized = sanitize_template_tokens(text, context)
    assert "Attention Accounts Payable Team: please review overdue invoices for Zenith Industries." == sanitized


def test_token_sanitization_trade_name_fallback_to_legal_name():
    """Missing trade_name falls back to legal name, then 'Valued Supplier'."""
    text = "Notice for {supplier_trade_name} ({supplier_gstin}) with at-risk ITC of {at_risk_itc}."
    context = {
        "supplier_gstin": "27ABCDE1234F1Z5",
        "supplier_name": "Zenith Industries",
        "at_risk_itc_rupees": 75400.25,
    }
    sanitized = sanitize_template_tokens(text, context)
    assert "Notice for Zenith Industries (27ABCDE1234F1Z5) with at-risk ITC of ₹75,400.25." == sanitized


def test_token_sanitization_unmapped_token_scrubbed():
    """Unrecognized {tokens} are safely scrubbed so curly braces never leak to recipients."""
    text = "Dear {supplier_contact}, reference {unknown_internal_code} for invoice review {another_token}."
    context = {
        "contact_person": "Priya Patel",
    }
    sanitized = sanitize_template_tokens(text, context)
    assert "{unknown_internal_code}" not in sanitized
    assert "{another_token}" not in sanitized
    assert "Dear Priya Patel, reference  for invoice review ." == sanitized


def test_all_five_templates_with_null_and_empty_master_data():
    """Ensure all 5 template types render properly with completely missing supplier name and phone."""
    templates = [
        "POLITE_REMINDER",
        "RULE37_NOTICE",
        "FINAL_ESCALATION",
        "MISSING_2B_REQUEST",
        "VALUE_MISMATCH_VERIFICATION",
    ]
    gstin = "27ABCDE1234F1Z5"
    for t_type in templates:
        wa = generate_whatsapp_payload(
            supplier_gstin=gstin,
            supplier_name="",
            vendor_phone="",
            at_risk_itc_rupees=10000.0,
            template_type=t_type,
        )
        assert f"Dear Valued Supplier ({gstin})" in wa["message_text"]
        assert "{" not in wa["message_text"]  # No raw tokens leaked

        email = generate_email_template(
            supplier_gstin=gstin,
            supplier_name=None,
            at_risk_itc_rupees=10000.0,
            template_type=t_type,
        )
        assert f"Dear <strong>Valued Supplier</strong> (GSTIN: <code>{gstin}</code>)" in email["html_body"]
        assert "{" not in email["html_body"]  # No raw tokens leaked


def test_custom_template_rendering_with_placeholders():
    """Custom template string provided via API correctly populates tokens and handles fallbacks."""
    custom = "Hello {supplier_contact} from {supplier_name}, please verify ₹{at_risk_itc_rupees} for {supplier_gstin}."
    wa = generate_whatsapp_payload(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name=None,
        contact_person=None,
        at_risk_itc_rupees=42000.0,
        custom_template=custom,
    )
    assert "Hello Accounts Payable Team from Valued Supplier, please verify ₹42,000.00 for 27ABCDE1234F1Z5." in wa["message_text"]


# ---------------------------------------------------------------------------
# Router Endpoint Integration Tests
# ---------------------------------------------------------------------------

def test_router_generate_whatsapp_endpoint_with_fallbacks():
    """POST /api/vendors/followup/clients/{client_id}/generate-whatsapp executes with fallback sanitization."""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    client_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    user = {"id": user_id, "role": "staff", "email": "staff@recondesk.in"}

    app.dependency_overrides[get_current_active_user] = lambda: user
    client = TestClient(app)

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.list_accessible_client_gstin_ids", return_value={client_id}):

        # 1. Fallback when supplier_name is empty
        res = client.post(
            f"/api/vendors/followup/clients/{client_id}/generate-whatsapp",
            json={
                "supplier_gstin": "27ABCDE1234F1Z5",
                "supplier_name": "",
                "at_risk_itc_rupees": 50000.0,
                "template_type": "POLITE_REMINDER",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["supplier_name"] == "Valued Supplier"
        assert "Dear Valued Supplier (27ABCDE1234F1Z5)" in data["message_text"]

        # 2. Custom template with trade_name and contact_person
        res_custom = client.post(
            f"/api/vendors/followup/clients/{client_id}/generate-whatsapp",
            json={
                "supplier_gstin": "27ABCDE1234F1Z5",
                "supplier_name": "Apex Global Tech Pvt Ltd",
                "trade_name": "Apex Tech",
                "contact_person": "Vikram Seth",
                "at_risk_itc_rupees": 75000.0,
                "template_type": "POLITE_REMINDER",
                "custom_template": "Attn {contact_person} at {trade_name} ({supplier_gstin}): please clear {at_risk_itc}.",
            },
        )
        assert res_custom.status_code == 200
        custom_data = res_custom.json()
        assert "Attn Vikram Seth at Apex Tech (27ABCDE1234F1Z5): please clear ₹75,000.00." in custom_data["message_text"]

    app.dependency_overrides.clear()


def test_router_generate_email_endpoint_with_fallbacks():
    """POST /api/vendors/followup/clients/{client_id}/generate-email executes with fallback sanitization."""
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    client_id = "00000000-0000-0000-0000-000000000001"
    user_id = "00000000-0000-0000-0000-000000000002"
    user = {"id": user_id, "role": "admin", "email": "admin@recondesk.in"}

    app.dependency_overrides[get_current_active_user] = lambda: user
    client = TestClient(app)

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.routers.vendor_followup.list_accessible_client_gstin_ids", return_value={client_id}):

        # 1. Fallback when supplier_name is None
        res = client.post(
            f"/api/vendors/followup/clients/{client_id}/generate-email",
            json={
                "supplier_gstin": "27ABCDE1234F1Z5",
                "at_risk_itc_rupees": 30000.0,
                "template_type": "RULE37_NOTICE",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert "Dear <strong>Valued Supplier</strong> (GSTIN: <code>27ABCDE1234F1Z5</code>)" in data["html_body"]

        # 2. Contact person provided
        res_contact = client.post(
            f"/api/vendors/followup/clients/{client_id}/generate-email",
            json={
                "supplier_gstin": "27ABCDE1234F1Z5",
                "supplier_name": "Bharat Heavy Electricals",
                "contact_person": "Ananya Roy",
                "at_risk_itc_rupees": 90000.0,
                "template_type": "MISSING_2B_REQUEST",
            },
        )
        assert res_contact.status_code == 200
        contact_data = res_contact.json()
        assert "Dear <strong>Ananya Roy</strong> (Bharat Heavy Electricals / GSTIN: <code>27ABCDE1234F1Z5</code>)" in contact_data["html_body"]

    app.dependency_overrides.clear()

