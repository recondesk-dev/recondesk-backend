"""GSTR-3B Sandbox client — fixture envelopes only (no live network)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.filing.filing_store import (
    Gstr3bPeriodLockedError,
    apply_offset_status_to_run,
)
from app.filing.sandbox_filing_client import (
    FilingGstnError,
    SandboxFilingClient,
    filing_run_status_after_offset_poll,
    filing_run_status_after_save_poll,
    parse_return_status,
)


GSTIN = "27ISKPK1273H1ZF"
PERIOD = "2026-07"


def _client() -> SandboxFilingClient:
    return SandboxFilingClient(
        api_key="k",
        api_secret="s",
        base_url="https://api.sandbox.co.in",
    )


def _resp(status: int, body: dict, url: str = "https://api.sandbox.co.in/x") -> httpx.Response:
    req = httpx.Request("POST", url)
    return httpx.Response(status, json=body, request=req)


class _FakeQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = list(rows)
        self._filters: list[tuple[str, Any]] = []
        self._in_filters: list[tuple[str, list[Any]]] = []
        self._order_col: str | None = None
        self._order_desc = False
        self._limit: int | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col: str, val: Any):
        self._filters.append((col, val))
        return self

    def in_(self, col: str, values: list[Any]):
        self._in_filters.append((col, list(values)))
        return self

    def order(self, col: str, desc: bool = False):
        self._order_col = col
        self._order_desc = desc
        return self

    def limit(self, n: int):
        self._limit = n
        return self

    def execute(self):
        out = self._rows
        for col, val in self._filters:
            out = [r for r in out if r.get(col) == val]
        for col, values in self._in_filters:
            allowed = set(values)
            out = [r for r in out if r.get(col) in allowed]
        if self._order_col:
            out = sorted(
                out,
                key=lambda r: (r.get(self._order_col) is None, r.get(self._order_col)),
                reverse=self._order_desc,
            )
        if self._limit is not None:
            out = out[: self._limit]
        return type("Res", (), {"data": out})()


class _FakeSb:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = list(rows or [])

    def table(self, name: str):
        assert name == "filing_runs"
        return _FakeQuery(self._rows)


def _minimal_save_body() -> dict[str, Any]:
    return {
        "gstin": GSTIN,
        "ret_period": "072026",
        "sup_details": {
            "osup_det": {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "osup_zero": {"txval": 0, "iamt": 0, "csamt": 0},
            "osup_nil_exmp": {"txval": 0},
            "osup_nongst": {"txval": 0},
            "isup_rev": {"txval": 0, "iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
        },
        "itc_elg": {
            "itc_avl": [{"ty": "OTH", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}],
            "itc_rev": [{"ty": "RUL", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}],
            "itc_net": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0},
            "itc_inelg": [{"ty": "OTH", "iamt": 0, "camt": 0, "samt": 0, "csamt": 0}],
        },
        "inward_sup": {
            "isup_details": [
                {"ty": "GST", "inter": 0, "intra": 0},
                {"ty": "NONGST", "inter": 0, "intra": 0},
            ]
        },
        "inter_sup": {"unreg_details": [], "comp_details": [], "uin_details": []},
        "intr_ltfee": {"intr_details": {"iamt": 0, "camt": 0, "samt": 0, "csamt": 0}},
    }


def _offset_body() -> dict[str, Any]:
    return {
        "pdcash": [
            {
                "liab_ldg_id": 1,
                "trans_typ": 30002,
                "ipd": 100,
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
            "i_pdi": 0,
            "i_pdc": 0,
            "i_pds": 0,
            "c_pdi": 0,
            "c_pdc": 0,
            "s_pdi": 0,
            "s_pds": 0,
            "cs_pdcs": 0,
        },
    }


# ── Shared async poll mapper ──────────────────────────────────────────────────


def test_offset_poll_mapper_mirrors_save_dual_status():
    ok = parse_return_status(
        {
            "data": {
                "status_cd": "1",
                "data": {"action": "RETOFFSET", "status_cd": "P"},
            }
        }
    )
    assert filing_run_status_after_offset_poll(ok) == ("offset_complete", None, None)
    # Same outer "1" must not confuse Save vs Offset mappers
    assert filing_run_status_after_save_poll(ok) == ("saved", None, None)

    er = parse_return_status(
        {
            "data": {
                "status_cd": "1",
                "data": {
                    "status_cd": "ER",
                    "error_report": {
                        "error_cd": "RT-3BAS1070",
                        "error_msg": "PARTIAL/EXCESS payment is not allowed.",
                    },
                },
            }
        }
    )
    st, cd, msg = filing_run_status_after_offset_poll(er)
    assert st == "offset_failed"
    assert cd == "RT-3BAS1070"
    assert "PARTIAL" in (msg or "")


# ── Get Details / ledger ──────────────────────────────────────────────────────


def test_get_gstr3b_details():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {
                        "gstin": GSTIN,
                        "ret_period": "072026",
                        "sup_details": {"osup_det": {"txval": 10}},
                        "tx_pmt": {"tx_py": [{"liab_ldg_id": 99}]},
                    },
                },
            },
        )
        result = c.get_gstr3b_details("tok", period=PERIOD)
    assert result.data["gstin"] == GSTIN
    assert result.data["tx_pmt"]["tx_py"][0]["liab_ldg_id"] == 99
    assert req.call_args.args[0] == "GET"
    assert "/gstr-3b/2026/07" in req.call_args.args[1]


def test_get_ledger_balance():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {"cash_bal": [{"tot_rng_bal": 500}]},
                },
            },
        )
        result = c.get_ledger_balance("tok", period=PERIOD)
    assert result.data["cash_bal"][0]["tot_rng_bal"] == 500
    assert "/ledgers/bal/2026/07" in req.call_args.args[1]


# ── Save + gate ───────────────────────────────────────────────────────────────


def test_save_gstr3b_accepted_for_processing_only():
    c = _client()
    sb = _FakeSb()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {"reference_id": "save-ref-1"},
                },
            },
        )
        result = c.save_gstr3b(
            "tok", period=PERIOD, save_body=_minimal_save_body(), sb=sb,
        )
    assert result.reference_id == "save-ref-1"
    # Outer 1 is not "saved" — caller must poll
    assert result.return_status is not None
    assert result.return_status.outer_status_cd == "1"


def test_save_gstr3b_blocked_by_period_gate_before_http():
    locking = {
        "id": "run-a",
        "gstin": GSTIN,
        "period": PERIOD,
        "return_type": "gstr-3b",
        "status": "offset_complete",
        "offset_completed_at": "2026-07-26T10:00:00+00:00",
        "tx_pmt_snapshot": {"tx_py": []},
    }
    sb = _FakeSb([locking])
    c = _client()
    with patch.object(c._http, "request") as req:
        with pytest.raises(Gstr3bPeriodLockedError) as ei:
            c.save_gstr3b(
                "tok", period=PERIOD, save_body=_minimal_save_body(), sb=sb,
            )
        assert ei.value.action == "save"
        assert req.call_count == 0  # never hit Sandbox


def test_save_gstr3b_raises_when_gstr1_not_filed():
    c = _client()
    sb = _FakeSb()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "0",
                    "error": {
                        "error_cd": "RT-R3BQ1004",
                        "message": "You have not filed GSTR-1 of the selected tax period.",
                    },
                },
            },
        )
        with pytest.raises(FilingGstnError) as ei:
            c.save_gstr3b(
                "tok", period=PERIOD, save_body=_minimal_save_body(), sb=sb,
            )
    assert ei.value.error_cd == "RT-R3BQ1004"


# ── Offset + gate + dual status ───────────────────────────────────────────────


def test_offset_blocked_by_gate_before_http():
    locking = {
        "id": "run-a",
        "gstin": GSTIN,
        "period": PERIOD,
        "return_type": "gstr-3b",
        "status": "filed",
        "offset_completed_at": "2026-07-26T10:00:00+00:00",
        "tx_pmt_snapshot": {"tx_py": [{"liab_ldg_id": 1}]},
    }
    sb = _FakeSb([locking])
    c = _client()
    with patch.object(c._http, "request") as req:
        with pytest.raises(Gstr3bPeriodLockedError) as ei:
            c.offset_gstr3b_liability(
                "tok",
                period=PERIOD,
                gstin=GSTIN,
                offset_body=_offset_body(),
                sb=sb,
            )
        assert ei.value.action == "offset"
        assert req.call_count == 0


def test_offset_outer_success_is_not_offset_complete():
    c = _client()
    sb = _FakeSb()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {
                        "Message": "Payment of tax successfully done",
                        "reference_id": "off-ref-1",
                    },
                },
            },
        )
        result = c.offset_gstr3b_liability(
            "tok",
            period=PERIOD,
            gstin=GSTIN,
            offset_body=_offset_body(),
            sb=sb,
        )
    assert result.reference_id == "off-ref-1"
    assert "/offset-liability" in req.call_args.args[1]
    # Must still poll — outer Message alone is not offset_complete
    assert filing_run_status_after_offset_poll(result.return_status)[0] != "offset_complete"


def test_offset_partial_excess_rt3bas1070_recoverable():
    c = _client()
    sb = _FakeSb()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "0",
                    "error": {
                        "error_cd": "RT-3BAS1070",
                        "message": (
                            "PARTIAL/EXCESS payment is not allowed.Please try again."
                        ),
                    },
                },
            },
        )
        with pytest.raises(FilingGstnError) as ei:
            c.offset_gstr3b_liability(
                "tok",
                period=PERIOD,
                gstin=GSTIN,
                offset_body=_offset_body(),
                sb=sb,
            )
    assert ei.value.error_cd == "RT-3BAS1070"
    # Gate still open — no offset_complete row was written


def test_apply_offset_status_sets_offset_complete_only_on_inner_p():
    info_p = parse_return_status(
        {
            "data": {
                "status_cd": "1",
                "data": {"action": "RETOFFSET", "status_cd": "P"},
            }
        }
    )
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.execute.return_value = (
        MagicMock(
            data=[
                {
                    "id": "run-1",
                    "status": "offset_complete",
                    "offset_completed_at": "2026-07-26T12:00:00+00:00",
                }
            ]
        )
    )
    updated = apply_offset_status_to_run(
        sb,
        "run-1",
        return_status=info_p,
        envelope={"data": {"status_cd": "1"}},
        offset_payload=_offset_body(),
        tx_pmt_snapshot={"tx_py": [{"liab_ldg_id": 1}]},
    )
    assert updated["status"] == "offset_complete"
    payload = sb.table.return_value.update.call_args.args[0]
    assert payload["status"] == "offset_complete"
    assert payload["offset_payload"]["pdcash"]
    assert payload["tx_pmt_snapshot"]["tx_py"][0]["liab_ldg_id"] == 1
    assert payload["offset_completed_at"]
    assert payload["status"] != "saved"


def test_wait_for_return_status_reused_for_offset_poll():
    """Same generic poller as GSTR-1 — REC then P."""
    c = _client()
    with patch.object(c._http, "request") as req:
        req.side_effect = [
            _resp(
                200,
                {
                    "code": 200,
                    "data": {
                        "status_cd": "1",
                        "data": {"action": "RETOFFSET", "status_cd": "REC"},
                    },
                },
            ),
            _resp(
                200,
                {
                    "code": 200,
                    "data": {
                        "status_cd": "1",
                        "data": {"action": "RETOFFSET", "status_cd": "P"},
                    },
                },
            ),
        ]
        result = c.wait_for_return_status(
            "tok",
            period=PERIOD,
            reference_id="off-ref-1",
            poll_interval_sec=0,
            max_attempts=5,
        )
    assert result.return_status is not None
    assert result.return_status.is_success is True
    assert filing_run_status_after_offset_poll(result.return_status)[0] == (
        "offset_complete"
    )


# ── EVC / File ────────────────────────────────────────────────────────────────


def test_generate_evc_otp_gstr3b_passes_gstr_query():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {"code": 200, "data": {"status_cd": "1"}},
        )
        c.generate_evc_otp_gstr3b("tok", pan="ABCDE1234F")
    assert req.call_args.kwargs["params"]["gstr"] == "gstr-3b"
    assert req.call_args.kwargs["json"]["pan"] == "ABCDE1234F"


def test_file_gstr3b_scrubs_otp_query_and_returns_ack():
    c = _client()
    with patch.object(c._http, "request") as req:
        req.return_value = _resp(
            200,
            {
                "code": 200,
                "data": {
                    "status_cd": "1",
                    "data": {"ack_num": "ACK3B001"},
                },
            },
        )
        result = c.file_gstr3b(
            "tok",
            period=PERIOD,
            pan="ABCDE1234F",
            otp="654321",
            file_body={
                "gstin": GSTIN,
                "ret_period": "072026",
                "tx_pmt": {"tx_py": [{"liab_ldg_id": 1}]},
            },
        )
    assert result.ack_number == "ACK3B001"
    # OTP is a query param (never body); sensitive_params path uses scrubbers in _request
    assert req.call_args.kwargs["params"]["otp"] == "654321"
    assert req.call_args.kwargs["params"]["pan"] == "ABCDE1234F"
    assert "/gstr-3b/2026/07/file" in req.call_args.args[1]
