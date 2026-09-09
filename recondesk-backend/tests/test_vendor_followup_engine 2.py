"""Unit tests for Automated Vendor Follow-up Engine."""

from app.services.vendor_followup_engine import (
    generate_whatsapp_payload,
    generate_email_template,
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
