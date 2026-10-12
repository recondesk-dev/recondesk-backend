"""GSTR-3B offset builder + router: preview / stale / period-locked fixtures."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.filing.filing_store import (
    Gstr3bPeriodLockedError,
    gstr3b_period_locked_detail,
)
from app.filing.gstr3b_offset import (
    Gstr3bOffsetBuildError,
    build_gstr3b_offset_body,
    extract_offset_pair,
    offset_bodies_equal,
)
from app.filing.sandbox_filing_client import FilingApiResult
from app.routers import filing as filing_router


GSTIN = "27AABCU9603R1ZM"
PERIOD = "2026-07"
FIRM_ID = "firm-1"
CLIENT_ID = "client-1"
RUN_ID = "run-saved-1"
SESSION_ID = "sess-1"


def _details_with_proposed(*, ipd: int = 100, i_pdi: int = 50) -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "ret_period": "072026",
        "tx_pmt": {
            "pdcash": [
                {
                    "liab_ldg_id": 1,
                    "trans_typ": 30002,
                    "ipd": ipd,
                    "cpd": 0,
                    "spd": 0,
                    "cspd": 0,
                    "i_intrpd": 0,
                    "c_intrpd": 0,
                    "s_intrpd": 0,
                    "cs_intrpd": 0,
                    "c_lfeepd": 0,
                    "s_lfeepd": 0,
                }
            ],
            "pditc": {
                "liab_ldg_id": 1,
                "trans_typ": 30002,
                "i_pdi": i_pdi,
                "i_pdc": 0,
                "i_pds": 0,
                "c_pdi": 0,
                "c_pdc": 0,
                "s_pdi": 0,
                "s_pds": 0,
                "cs_pdcs": 0,
            },
            "net_tax_pay": [
                {
                    "liab_ldg_id": 1,
                    "trans_typ": 30002,
                    "igst": {"tx": ipd + i_pdi, "intr": 0, "fee": 0},
                    "cgst": {"tx": 0, "intr": 0, "fee": 0},
                    "sgst": {"tx": 0, "intr": 0, "fee": 0},
                    "cess": {"tx": 0, "intr": 0, "fee": 0},
                }
            ],
        },
    }


def _ledger(*, igst_itc: int = 10_000, igst_cash: int = 10_000) -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "itc_bal": {
            "igst_bal": igst_itc,
            "cgst_bal": 0,
            "sgst_bal": 0,
            "cess_bal": 0,
        },
        "cash_bal": {
            "igst": {"tx": igst_cash, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "cgst": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "sgst": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
            "cess": {"tx": 0, "intr": 0, "fee": 0, "pen": 0, "oth": 0},
        },
    }


def _details_net_tax_only(*, igst_due: int = 150) -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "tx_pmt": {
            "net_tax_pay": [
                {
                    "liab_ldg_id": 99,
                    "trans_typ": 30002,
                    "igst": {"tx": igst_due, "intr": 0, "fee": 0},
                    "cgst": {"tx": 0, "intr": 0, "fee": 0},
                    "sgst": {"tx": 0, "intr": 0, "fee": 0},
                    "cess": {"tx": 0, "intr": 0, "fee": 0},
                }
            ],
        },
    }


# ── Builder unit tests ───────────────────────────────────────────────────────


def test_builder_prefers_proposed_pdcash_pditc_and_caps_to_ledger():
    details = _details_with_proposed(ipd=100, i_pdi=50)
    ledger = _ledger(igst_itc=10_000, igst_cash=10_000)
    body = build_gstr3b_offset_body(details, ledger)
    assert body["pdcash"][0]["ipd"] == 100
    assert body["pditc"]["i_pdi"] == 50


def test_builder_caps_when_ledger_cannot_fund_proposed():
    details = _details_with_proposed(ipd=100, i_pdi=50)
    # Ledger can only fund 20 ITC + 30 cash → caps kick in
    ledger = _ledger(igst_itc=20, igst_cash=30)
    body = build_gstr3b_offset_body(details, ledger)
    assert body["pditc"]["i_pdi"] == 20
    assert body["pdcash"][0]["ipd"] == 30


def test_builder_synthesizes_from_net_tax_pay_when_no_proposed():
    details = _details_net_tax_only(igst_due=150)
    ledger = _ledger(igst_itc=40, igst_cash=200)
    body = build_gstr3b_offset_body(details, ledger)
    assert body["pditc"]["i_pdi"] == 40
    assert body["pdcash"][0]["ipd"] == 110
    assert body["pdcash"][0]["liab_ldg_id"] == 99


def test_builder_raises_without_proposed_or_net_tax_pay():
    with pytest.raises(Gstr3bOffsetBuildError):
        build_gstr3b_offset_body({"gstin": GSTIN}, _ledger())


def test_offset_bodies_equal_ignores_non_pdcash_pditc_fields():
    a = {"pdcash": [{"ipd": 1}], "pditc": {"i_pdi": 2}, "session_id": "x"}
    b = {"pdcash": [{"ipd": 1}], "pditc": {"i_pdi": 2}, "run_id": "y"}
    assert offset_bodies_equal(a, b) is True
    assert offset_bodies_equal(a, {"pdcash": [{"ipd": 9}], "pditc": {"i_pdi": 2}}) is False


def test_period_locked_detail_includes_locking_run_proof():
    locking = {
        "id": "lock-run",
        "status": "offset_complete",
        "offset_completed_at": "2026-07-25T12:00:00+00:00",
        "reference_id": "ref-1",
        "offset_payload": {"pdcash": [{"ipd": 1}], "pditc": {}},
        "tx_pmt_snapshot": {"tx_py": [{"liab_ldg_id": 1}]},
    }
    exc = Gstr3bPeriodLockedError(
        "blocked",
        action="offset",
        gstin=GSTIN,
        period=PERIOD,
        locking_run=locking,
    )
    detail = gstr3b_period_locked_detail(exc)
    assert detail["code"] == "GSTR3B_PERIOD_LOCKED"
    assert detail["locking_run"]["run_id"] == "lock-run"
    assert detail["locking_run"]["status"] == "offset_complete"
    assert detail["locking_run"]["offset_completed_at"] == locking["offset_completed_at"]
    assert detail["locking_run"]["tx_pmt_snapshot"]["tx_py"][0]["liab_ldg_id"] == 1
    assert detail["locking_run"]["offset_payload"]["pdcash"][0]["ipd"] == 1


# ── Router helpers with mocked client / auth ─────────────────────────────────


class _FakeClient:
    def __init__(
        self,
        *,
        details: dict[str, Any],
        ledger: dict[str, Any],
        offset_result: FilingApiResult | None = None,
    ) -> None:
        self._details = details
        self._ledger = ledger
        self._offset_result = offset_result or FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-OFF"}}},
            reference_id="REF-OFF",
            data={"reference_id": "REF-OFF", "Message": "Payment of tax successfully done"},
        )
        self.offset_calls: list[dict[str, Any]] = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_gstr3b_details(self, *_a, **_k):
        return FilingApiResult(envelope={"code": 200, "data": {"status_cd": "1", "data": dict(self._details)}}, data=dict(self._details))

    def get_ledger_balance(self, *_a, **_k):
        return FilingApiResult(envelope={"code": 200, "data": {"status_cd": "1", "data": dict(self._ledger)}}, data=dict(self._ledger))

    def offset_gstr3b_liability(self, *_a, **kwargs):
        self.offset_calls.append(dict(kwargs.get("offset_body") or {}))
        return self._offset_result


@contextmanager
def _patch_router_auth(
    *,
    fake_client: _FakeClient,
    run_status: str = "saved",
    lock_exc: Gstr3bPeriodLockedError | None = None,
):
    """Context patches shared by offset-preview / offset endpoint tests."""
    sb = MagicMock()

    def _assert_save_or_offset(*_a, **_k):
        if lock_exc is not None:
            raise lock_exc

    run_row = {
        "id": RUN_ID,
        "firm_id": FIRM_ID,
        "status": run_status,
        "gstin": GSTIN,
        "period": PERIOD,
        "return_type": "gstr-3b",
    }

    patches = [
        patch.object(filing_router, "get_supabase", return_value=sb),
        patch.object(filing_router, "_firm_id", return_value=FIRM_ID),
        patch.object(
            filing_router,
            "_assert_client_access",
            return_value={"id": CLIENT_ID, "gstin": GSTIN},
        ),
        patch.object(
            filing_router,
            "_resolve_token",
            return_value=("tok", {"id": SESSION_ID}),
        ),
        patch.object(filing_router, "get_filing_client", return_value=fake_client),
        patch.object(
            filing_router.filing_store,
            "assert_gstr3b_offset_allowed",
            side_effect=_assert_save_or_offset,
        ),
        patch.object(
            filing_router.filing_store,
            "assert_gstr3b_save_allowed",
            side_effect=_assert_save_or_offset,
        ),
        patch.object(
            filing_router.filing_store,
            "get_run",
            return_value=run_row,
        ),
        patch.object(
            filing_router.filing_store,
            "update_run",
            return_value={**run_row, "status": "offset_pending"},
        ),
        patch.object(
            filing_router.filing_store,
            "mark_run_failed",
            return_value=None,
        ),
        patch.object(filing_router, "assert_maker_checker_gate", return_value=None),
        patch.object(filing_router, "assert_client_authorization_gate", return_value=None),
    ]

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


def test_offset_preview_matches_builder_output():
    details = _details_with_proposed(ipd=100, i_pdi=50)
    ledger = _ledger()
    expected = build_gstr3b_offset_body(details, ledger)
    fake = _FakeClient(details=details, ledger=ledger)
    with _patch_router_auth(fake_client=fake):
        result = filing_router.gstr3b_offset_preview(
            PERIOD,
            CLIENT_ID,
            session_id=SESSION_ID,
            current_user={"id": "u"},
        )
    assert result["pdcash"] == expected["pdcash"]
    assert result["pditc"] == expected["pditc"]
    assert offset_bodies_equal(result, expected)


def test_offset_happy_path_persists_posted_payload():
    details = _details_with_proposed(ipd=100, i_pdi=50)
    ledger = _ledger()
    posted = build_gstr3b_offset_body(details, ledger)
    fake = _FakeClient(details=details, ledger=ledger)
    body = filing_router.OffsetGstr3bBody(
        client_gstin_id=CLIENT_ID,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        pdcash=posted["pdcash"],
        pditc=posted["pditc"],
    )
    with _patch_router_auth(fake_client=fake):
        result = filing_router.offset_gstr3b(
            PERIOD, body, current_user={"id": "u"},
        )
    assert result["status"] == "offset_pending"
    assert result["reference_id"] == "REF-OFF"
    assert result["offset_payload"] == extract_offset_pair(posted)
    assert fake.offset_calls[0] == extract_offset_pair(posted)


def test_offset_stale_when_ledger_changes_between_preview_and_post():
    details = _details_with_proposed(ipd=100, i_pdi=50)
    ledger_at_preview = _ledger(igst_itc=10_000, igst_cash=10_000)
    posted = build_gstr3b_offset_body(details, ledger_at_preview)

    # Ledger drained after CA looked at confirmation screen
    ledger_now = _ledger(igst_itc=5, igst_cash=10)
    assert not offset_bodies_equal(
        posted, build_gstr3b_offset_body(details, ledger_now),
    )

    fake = _FakeClient(details=details, ledger=ledger_now)
    body = filing_router.OffsetGstr3bBody(
        client_gstin_id=CLIENT_ID,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        pdcash=posted["pdcash"],
        pditc=posted["pditc"],
    )
    with _patch_router_auth(fake_client=fake):
        with pytest.raises(HTTPException) as ei:
            filing_router.offset_gstr3b(PERIOD, body, current_user={"id": "u"})
    assert ei.value.status_code == 409
    detail = ei.value.detail
    assert detail["code"] == "GSTR3B_OFFSET_STALE"
    assert detail["posted"]["pditc"]["i_pdi"] == 50
    assert detail["current"]["pditc"]["i_pdi"] == 5
    assert fake.offset_calls == []


def test_offset_period_locked_returns_structured_409():
    details = _details_with_proposed()
    ledger = _ledger()
    posted = build_gstr3b_offset_body(details, ledger)
    locking = {
        "id": "older-run",
        "status": "offset_complete",
        "offset_completed_at": "2026-07-20T10:00:00+00:00",
        "reference_id": "OLD-REF",
        "offset_payload": {"pdcash": [{"ipd": 1}], "pditc": {"i_pdi": 1}},
        "tx_pmt_snapshot": {"tx_py": [{"liab_ldg_id": 770}]},
    }
    lock_exc = Gstr3bPeriodLockedError(
        "blocked for test",
        action="offset",
        gstin=GSTIN,
        period=PERIOD,
        locking_run=locking,
    )
    fake = _FakeClient(details=details, ledger=ledger)
    body = filing_router.OffsetGstr3bBody(
        client_gstin_id=CLIENT_ID,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        pdcash=posted["pdcash"],
        pditc=posted["pditc"],
    )
    with _patch_router_auth(fake_client=fake, lock_exc=lock_exc):
        with pytest.raises(HTTPException) as ei:
            filing_router.offset_gstr3b(PERIOD, body, current_user={"id": "u"})
    assert ei.value.status_code == 409
    detail = ei.value.detail
    assert detail["code"] == "GSTR3B_PERIOD_LOCKED"
    assert detail["locking_run"]["run_id"] == "older-run"
    assert detail["locking_run"]["tx_pmt_snapshot"]["tx_py"][0]["liab_ldg_id"] == 770
    assert fake.offset_calls == []


def test_preview_and_offset_share_identical_builder_identity():
    """Offset accepts exactly what offset-preview would have returned."""
    details = _details_net_tax_only(igst_due=200)
    ledger = _ledger(igst_itc=60, igst_cash=500)
    fake = _FakeClient(details=details, ledger=ledger)

    with _patch_router_auth(fake_client=fake):
        preview = filing_router.gstr3b_offset_preview(
            PERIOD, CLIENT_ID, session_id=SESSION_ID, current_user={"id": "u"},
        )

    body = filing_router.OffsetGstr3bBody(
        client_gstin_id=CLIENT_ID,
        session_id=SESSION_ID,
        run_id=RUN_ID,
        pdcash=preview["pdcash"],
        pditc=preview["pditc"],
    )
    with _patch_router_auth(fake_client=fake):
        result = filing_router.offset_gstr3b(
            PERIOD, body, current_user={"id": "u"},
        )
    assert result["offset_payload"]["pdcash"] == preview["pdcash"]
    assert result["offset_payload"]["pditc"] == preview["pditc"]


def test_get_gstr3b_raw_details_success_and_requires_session():
    """Confirms /gstr-3b/{period}/raw-details requires a valid session and passes through raw envelope unmodified."""
    details = _details_with_proposed()
    raw_envelope = {"code": 200, "data": {"status_cd": "1", "data": details}, "transaction_id": "tx-123"}
    fake = _FakeClient(details=details, ledger=_ledger())
    fake.get_gstr3b_details = MagicMock(return_value=FilingApiResult(envelope=raw_envelope, data=details))

    # 1. Success case: returns unmodified raw envelope
    with _patch_router_auth(fake_client=fake):
        raw = filing_router.get_gstr3b_raw_details(
            PERIOD,
            client_gstin_id=CLIENT_ID,
            session_id=SESSION_ID,
            current_user={"id": "u"},
        )
    assert raw == raw_envelope

    # 2. Session missing/invalid case: raises 409
    with patch.object(filing_router, "get_supabase", return_value=MagicMock()), \
         patch.object(filing_router, "_firm_id", return_value=FIRM_ID), \
         patch.object(filing_router, "_assert_client_access", return_value={"id": CLIENT_ID, "gstin": GSTIN}), \
         patch.object(filing_router, "_resolve_token", side_effect=HTTPException(status_code=409, detail="no active filing session")):
        with pytest.raises(HTTPException) as ei:
            filing_router.get_gstr3b_raw_details(
                PERIOD,
                client_gstin_id=CLIENT_ID,
                session_id=None,
                current_user={"id": "u"},
            )
        assert ei.value.status_code == 409


def test_save_gstr3b_applies_system_late_fee_from_get_details():
    """Confirms save_gstr3b endpoint fetches get_gstr3b_details and overlays system late fee before saving."""
    details = {
        "gstin": GSTIN,
        "ret_period": "072026",
        "intr_ltfee": {
            "ltfee_details": {"camt": 150.0, "samt": 150.0}
        }
    }
    fake = _FakeClient(details=details, ledger=_ledger())
    save_calls = []
    def _mock_save(token, *, period, save_body, sb):
        save_calls.append(dict(save_body))
        return FilingApiResult(
            envelope={"code": 200, "data": {"status_cd": "1", "data": {"reference_id": "REF-SAVE"}}},
            reference_id="REF-SAVE",
            data={"reference_id": "REF-SAVE"},
        )
    fake.save_gstr3b = _mock_save

    body = filing_router.SaveGstr3bBody(
        client_gstin_id=CLIENT_ID,
        period=PERIOD,
        session_id=SESSION_ID,
        save_body={
            "gstin": GSTIN,
            "intr_ltfee": {"ltfee_details": {"camt": 0, "samt": 0}},
        },
    )
    with _patch_router_auth(fake_client=fake):
        res = filing_router.save_gstr3b(PERIOD, body, current_user={"id": "u", "role": "admin"})

    assert res["status"] == "save_pending"
    assert len(save_calls) == 1
    assert save_calls[0]["intr_ltfee"]["ltfee_details"] == {"camt": 150, "samt": 150}




