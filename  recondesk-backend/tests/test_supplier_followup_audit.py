"""Supplier follow-up audit id validation."""

from app.routers.reconciliation_api import (
    _safe_int_paise,
    _wrongful_risk_record_ids_for_run,
)


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
