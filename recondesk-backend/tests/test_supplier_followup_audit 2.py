"""Supplier follow-up audit helpers."""

from app.routers.reconciliation_api import (
    _followup_audit_list_response,
    _safe_int_paise,
    _wrongful_risk_record_ids_for_run,
)
from app.services.followup_audit_export import build_followup_history_xlsx_bytes


def test_safe_int_paise_handles_bad_values():
    assert _safe_int_paise(None) == 0
    assert _safe_int_paise("") == 0
    assert _safe_int_paise("bad", 7) == 7
    assert _safe_int_paise(100) == 100


def test_wrongful_risk_record_ids_from_engine_payload():
    class FakeSb:
        pass

    def fake_payload(_sb, _rid):
        return {
            "engine": {
                "wrongful_itc_risk": [
                    {"id": "pr-uuid-1"},
                    {"id": "pr-uuid-2"},
                ]
            }
        }

    import app.routers.reconciliation_api as api

    orig = api._payload_or_404
    api._payload_or_404 = fake_payload
    try:
        ids = _wrongful_risk_record_ids_for_run(FakeSb(), "run-1")
        assert ids == {"wr:pr-uuid-1", "wr:pr-uuid-2"}
    finally:
        api._payload_or_404 = orig


def test_followup_audit_list_response_includes_letter_body(monkeypatch):
    monkeypatch.setattr(
        "app.routers.reconciliation_api._followup_audit_user_names",
        lambda _uids: {"user-1": "CA Name"},
    )
    rows = _followup_audit_list_response(
        [
            {
                "id": "a1",
                "run_id": "r1",
                "tax_period": "2026-05",
                "supplier_gstin": "27AABCU9603R1ZX",
                "supplier_name_display": "Supplier Co",
                "template_type": "wrongful_itc_single",
                "status": "downloaded",
                "generated_by": "user-1",
                "generated_at": "2026-07-29T01:00:00+00:00",
                "invoice_snapshot": [{"invoice_number": "INV-1"}],
                "letter_body": "Date: 29 Jul 2026\n\nDear Sir/Madam,\n…",
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0].letter_body and "Dear Sir/Madam" in rows[0].letter_body
    assert rows[0].generated_by_name == "CA Name"


def test_followup_history_xlsx_includes_letter_body_column():
    raw, _name = build_followup_history_xlsx_bytes(
        [
            {
                "supplier_name_display": "Supplier Co",
                "supplier_gstin": "27AABCU9603R1ZX",
                "tax_period": "2026-05",
                "template_type": "wrongful_itc_single",
                "status": "copied",
                "generated_by_name": "CA Name",
                "generated_at": "2026-07-29T01:00:00+00:00",
                "letter_body": "Exact letter text for audit trail.",
            }
        ],
        client_gstin="27AAAAA0000A1Z5",
        include_tax_period=True,
    )
    from io import BytesIO

    from openpyxl import load_workbook

    wb = load_workbook(BytesIO(raw))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert "Letter Body" in headers
    letter_col = headers.index("Letter Body") + 1
    assert ws.cell(row=2, column=letter_col).value == "Exact letter text for audit trail."
