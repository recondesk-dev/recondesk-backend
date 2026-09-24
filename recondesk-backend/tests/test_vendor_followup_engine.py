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


# ---------------------------------------------------------------------------
# Tokenized Vendor Action Portal Tests (/v/[token])
# ---------------------------------------------------------------------------

def test_whatsapp_and_email_with_portal_url():
    """Verify portal_url is cleanly embedded in WhatsApp message and email CTA button."""
    portal_link = "https://recondesk.in/v/test-portal-token-123"
    wa_res = generate_whatsapp_payload(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Acme Solutions",
        vendor_phone="9876543210",
        at_risk_itc_rupees=45000.0,
        portal_url=portal_link,
    )
    assert portal_link in wa_res["message_text"]
    assert "Action Required — Confirm Status in 1-Click" in wa_res["message_text"]
    assert wa_res["portal_url"] == portal_link

    email_res = generate_email_template(
        supplier_gstin="27ABCDE1234F1Z5",
        supplier_name="Acme Solutions",
        at_risk_itc_rupees=45000.0,
        portal_url=portal_link,
    )
    assert portal_link in email_res["html_body"]
    assert "Review Invoices &amp; Confirm Filing in 1-Click" in email_res["html_body"]
    assert email_res["portal_url"] == portal_link


def test_submit_vendor_portal_response_arn_validation():
    """Verify standard 18-char ARN (AA + 2 digit state code + 14 chars) succeeds and invalid format raises 422."""
    from unittest.mock import MagicMock, patch
    from fastapi import HTTPException
    from app.services.vendor_followup_engine import submit_vendor_portal_response

    mock_sb = MagicMock()
    mock_log = {
        "id": "11111111-1111-1111-1111-111111111111",
        "client_gstin_id": "22222222-2222-2222-2222-222222222222",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "supplier_name": "Test Supplier",
        "at_risk_itc_rupees": 25000.0,
        "status": "VIEWED",
        "token": "valid-token-xyz",
        "expires_at": None,
        "viewed_at": "2026-09-25T00:00:00Z",
    }

    with patch("app.services.vendor_followup_engine.get_vendor_portal_data", return_value=mock_log):
        # 1. Valid 18-character ARN (AA + 27 + 14 alphanumeric = 18 chars)
        res = submit_vendor_portal_response(
            sb=mock_sb,
            token="valid-token-xyz",
            action="ALREADY_FILED",
            arn_number="AA2708260012345678",
        )
        assert res["success"] is True
        assert res["status"] == "FILING_CONFIRMED"
        assert res["arn_number"] == "AA2708260012345678"

        # 2. Invalid ARN: 15 chars (not 18)
        try:
            submit_vendor_portal_response(
                sb=mock_sb,
                token="valid-token-xyz",
                action="ALREADY_FILED",
                arn_number="AA2708260012",
            )
            assert False, "Should have raised 422 for invalid ARN length"
        except HTTPException as exc:
            assert exc.status_code == 422
            assert "Invalid ARN format" in exc.detail

        # 3. Invalid ARN: doesn't start with AA
        try:
            submit_vendor_portal_response(
                sb=mock_sb,
                token="valid-token-xyz",
                action="ALREADY_FILED",
                arn_number="BB27082600123456",
            )
            assert False, "Should have raised 422 for ARN not starting with AA"
        except HTTPException as exc:
            assert exc.status_code == 422

        # 4. Cycle promise action
        cycle_res = submit_vendor_portal_response(
            sb=mock_sb,
            token="valid-token-xyz",
            action="PROMISED_NEXT_CYCLE",
            promised_period="September 2026",
        )
        assert cycle_res["success"] is True
        assert cycle_res["status"] == "PROMISED_NEXT_CYCLE"
        assert cycle_res["promised_period"] == "September 2026"

        # 5. Dispute action
        disp_res = submit_vendor_portal_response(
            sb=mock_sb,
            token="valid-token-xyz",
            action="DISPUTED",
            dispute_reason="Goods were rejected and invoice canceled before delivery",
        )
        assert disp_res["success"] is True
        assert disp_res["status"] == "DISPUTED"


def test_public_vendor_portal_router_endpoints():
    """Verify public endpoints /api/public/v/{token} and /v/{token} work without auth."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    mock_portal_data = {
        "id": "11111111-1111-1111-1111-111111111111",
        "token": "test-portal-token-456",
        "client_name": "Bharat Trading Corp",
        "client_gstin": "27AAACB1234A1Z5",
        "supplier_name": "Kalyan Packaging Works",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "at_risk_itc_rupees": 54200.0,
        "status": "VIEWED",
        "response_action": None,
        "arn_number": None,
        "promised_period": None,
        "dispute_reason": None,
        "attachment_key": None,
        "viewed_at": "2026-09-25T01:00:00Z",
        "responded_at": None,
        "expires_at": "2026-11-09T01:00:00Z",
        "invoices": [
            {
                "invoice_number": "INV-2026-099",
                "invoice_date": "2026-08-10",
                "taxable_value": 300000.0,
                "tax_amount": 54000.0,
                "reason": "Missing in GSTR-2B",
            }
        ],
    }

    mock_response_result = {
        "success": True,
        "status": "FILING_CONFIRMED",
        "response_action": "ALREADY_FILED",
        "reference_id": "11111111-1111-1111-1111-111111111111",
        "responded_at": "2026-09-25T01:05:00Z",
        "arn_number": "AA2708260012345678",
        "promised_period": None,
        "message": "Thank you! Your response has been securely recorded for GST reconciliation.",
    }

    with patch("app.routers.vendor_followup.get_supabase"), \
         patch("app.services.vendor_followup_engine.get_vendor_portal_data", return_value=mock_portal_data), \
         patch("app.services.vendor_followup_engine.submit_vendor_portal_response", return_value=mock_response_result):

        # 1. GET /api/public/v/{token} (no auth header needed)
        res_info = client.get("/api/public/v/test-portal-token-456")
        assert res_info.status_code == 200
        info_data = res_info.json()
        assert info_data["supplier_gstin"] == "27ABCDE1234F1Z5"
        assert info_data["client_name"] == "Bharat Trading Corp"
        assert len(info_data["invoices"]) == 1

        # 2. GET /v/{token} (alternate prefix)
        res_info_v = client.get("/v/test-portal-token-456")
        assert res_info_v.status_code == 200
        assert res_info_v.json()["token"] == "test-portal-token-456"

        # 3. POST /api/public/v/{token}/respond
        res_resp = client.post(
            "/api/public/v/test-portal-token-456/respond",
            json={
                "action": "ALREADY_FILED",
                "arn_number": "AA2708260012345678",
            },
        )
        assert res_resp.status_code == 200
        resp_data = res_resp.json()
        assert resp_data["success"] is True
        assert resp_data["arn_number"] == "AA2708260012345678"


def test_is_promise_period_overdue_logic():
    """Verify GST GSTR-1 cutoff (11th of month M+1) accurately determines overdue cycles."""
    from datetime import datetime, timezone
    from unittest.mock import patch
    from app.services.vendor_followup_engine import is_promise_period_overdue

    # Fix current time to September 25, 2026
    fixed_now = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)
    with patch("app.services.vendor_followup_engine.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        mock_dt.fromisoformat = datetime.fromisoformat
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        # 1. August 2026 GSTR-1 was due on Sept 11, 2026. On Sept 25, it is overdue!
        assert is_promise_period_overdue("August 2026") is True
        assert is_promise_period_overdue("2026-08") is True

        # 2. September 2026 GSTR-1 is due on Oct 11, 2026. On Sept 25, it is NOT overdue!
        assert is_promise_period_overdue("September 2026") is False
        assert is_promise_period_overdue("2026-09") is False

        # 3. October 2026 is in the future
        assert is_promise_period_overdue("October 2026") is False


def test_get_vendor_risk_summaries_escalates_broken_promise():
    """Verify vendor with an overdue filing promise is auto-escalated to PROMISE_BROKEN."""
    from unittest.mock import MagicMock, patch
    from app.services.vendor_followup_engine import get_vendor_risk_summaries

    mock_sb = MagicMock()
    # 1. Mock supplier compliance summary with 1 vendor
    mock_summary = [{
        "supplier_gstin_normalized": "27ABCDE1234F1Z5",
        "supplier_trade_name": "Kalyan Packaging Works",
        "vendor_phone": "9876543210",
        "vendor_email": "kalyan@packaging.com",
        "total_invoices": 3,
        "mismatch_invoice_count": 2,
        "rule37_open_count": 0,
        "rule37_at_risk_paise": 5400000,
        "risk_score": 60,
        "client_gstin_ids": ["client-uuid-1"],
    }]
    mock_sb.table("supplier_compliance_summary").select().execute.return_value.data = mock_summary
    mock_sb.table("rule37_actions").select().eq().execute.return_value.data = []

    # 2. Mock past followup log where vendor promised August 2026 (now overdue)
    mock_logs = [{
        "id": "log-1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "supplier_name": "Kalyan Packaging Works",
        "status": "PROMISED_NEXT_CYCLE",
        "response_action": "PROMISED_NEXT_CYCLE",
        "promised_period": "August 2026",
        "dispatched_at": "2026-08-05T10:00:00Z",
        "token": "tok-1",
        "viewed_at": "2026-08-06T10:00:00Z",
    }]

    with patch("app.services.vendor_followup_engine.get_followup_history", return_value=mock_logs), \
         patch("app.services.vendor_followup_engine.is_promise_period_overdue", return_value=True):

        vendors = get_vendor_risk_summaries(mock_sb, "client-uuid-1")
        assert len(vendors) == 1
        v = vendors[0]
        assert v["supplier_gstin"] == "27ABCDE1234F1Z5"
        assert v["followup_status"] == "PROMISE_BROKEN"
        assert v["promise_broken"] is True
        assert "Promised in August 2026" in v["promise_broken_note"]
        # Risk score escalated by 20 points: 60 + 20 = 80
        assert v["risk_score"] == 80


def test_portal_reads_immutable_snapshot():
    """Verify get_vendor_portal_data strictly serves frozen invoices_snapshot without re-querying live DB."""
    from unittest.mock import MagicMock, patch
    from app.services.vendor_followup_engine import get_vendor_portal_data

    mock_sb = MagicMock()
    frozen_invoices = [
        {"invoice_number": "INV-ORIG-001", "invoice_date": "2026-07-01", "taxable_value": 100000.0, "tax_amount": 18000.0, "reason": "Missing in GSTR-2B"},
        {"invoice_number": "INV-ORIG-002", "invoice_date": "2026-07-15", "taxable_value": 200000.0, "tax_amount": 36000.0, "reason": "Missing in GSTR-2B"},
    ]

    mock_log = {
        "id": "log-abc",
        "token": "frozen-token-xyz",
        "client_gstin_id": "client-uuid-1",
        "supplier_gstin": "27ABCDE1234F1Z5",
        "supplier_name": "Supplier X",
        "at_risk_itc_rupees": 54000.0,
        "status": "DISPATCHED",
        "invoices_snapshot": frozen_invoices,
        "viewed_at": None,
        "expires_at": None,
    }

    def mock_table(table_name):
        t = MagicMock()
        if table_name == "vendor_followup_logs":
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [mock_log]
            t.update.return_value.eq.return_value.execute.return_value.data = [mock_log]
        elif table_name == "client_gstins":
            t.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
                "gstin": "27AAACB1234A1Z5",
                "legal_name": "Client Corp",
            }]
        return t

    mock_sb.table.side_effect = mock_table

    with patch("app.services.vendor_followup_engine.fetch_vendor_invoices") as mock_fetch:
        portal_info = get_vendor_portal_data(mock_sb, "frozen-token-xyz")
        # Ensure fetch_vendor_invoices was NOT called because snapshot exists
        mock_fetch.assert_not_called()
        assert len(portal_info["invoices"]) == 2
        assert portal_info["invoices"][0]["invoice_number"] == "INV-ORIG-001"
        assert portal_info["invoices"][1]["invoice_number"] == "INV-ORIG-002"



