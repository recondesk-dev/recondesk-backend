"""
test_supplier_compliance_scorecard.py
Pure-function tests for vendor compliance scorecard aggregation.
Run: PYTHONPATH=. pytest tests/test_supplier_compliance_scorecard.py -v
"""

from __future__ import annotations

from app.services.supplier_compliance_scorecard import (
    SIGNAL_NOTES,
    compute_risk_score,
    counters_to_row_dict,
    extract_supplier_counters_from_payload,
    rollup_client_rows,
    try_normalize_supplier_gstin,
)

VALID_MH = "27ABCDE1234F1Z0"
VALID_KA = "29ABCDE1234F1ZW"
INVALID_CHECKSUM = "27AAAAA0000A1Z5"  # format-ok, checksum bad


def _payload(**kwargs):
    engine = kwargs.pop("engine", {})
    compliance = kwargs.pop("compliance", {})
    return {"engine": engine, "compliance": compliance, **kwargs}


class TestNormalizeGate:
    def test_valid_gstin_accepted(self):
        assert try_normalize_supplier_gstin(VALID_MH) == VALID_MH

    def test_invalid_checksum_excluded(self):
        assert try_normalize_supplier_gstin(INVALID_CHECKSUM) is None

    def test_garbage_excluded(self):
        assert try_normalize_supplier_gstin("not-a-gstin") is None
        assert try_normalize_supplier_gstin("") is None
        assert try_normalize_supplier_gstin(None) is None

    def test_extract_skips_invalid_checksum_supplier(self):
        payload = _payload(
            engine={
                "missed_itc": [
                    {
                        "supplier_gstin": INVALID_CHECKSUM,
                        "invoice_number_normalized": "INV1",
                        "invoice_date": "2024-04-01",
                    },
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number_normalized": "INV2",
                        "invoice_date": "2024-04-02",
                    },
                ]
            }
        )
        out = extract_supplier_counters_from_payload(payload)
        assert INVALID_CHECKSUM not in out
        assert VALID_MH in out
        assert len(out[VALID_MH].invoice_keys) == 1


class TestMismatchAndPrOnly:
    def test_mismatch_rate_inputs(self):
        payload = _payload(
            engine={
                "matched": [],
                "missed_itc": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number_normalized": "A",
                        "invoice_date": "2024-04-01",
                    }
                ],
                "wrongful_itc_risk": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number_normalized": "B",
                        "invoice_date": "2024-04-02",
                        "risk_reason": "PR_ONLY",
                    }
                ],
            }
        )
        # Matched via record index
        idx = {
            "gstr:g1": {
                "supplier_gstin": VALID_MH,
                "invoice_number": "C",
                "invoice_date": "2024-04-03",
                "supplier_name": "Acme",
            }
        }
        payload["engine"]["matched"] = [{"gstr_id": "g1", "pr_id": "p1"}]
        out = extract_supplier_counters_from_payload(payload, record_index=idx)
        c = out[VALID_MH]
        assert len(c.invoice_keys) == 3
        assert len(c.mismatch_keys) == 2
        assert c.pr_only_count == 1
        assert c.trade_name == "Acme"

    def test_pr_only_not_labeled_non_filer_in_signal_notes(self):
        note = SIGNAL_NOTES["pr_only_count"].lower()
        assert "not a non-filer" in note
        assert "non_filer" in SIGNAL_NOTES
        assert "no non-filer" in SIGNAL_NOTES["non_filer"].lower()

    def test_quarterly_filer_flag(self):
        payload = _payload(
            engine={
                "wrongful_itc_risk": [
                    {
                        "supplier_gstin": VALID_KA,
                        "invoice_number_normalized": "Q1",
                        "invoice_date": "2024-04-01",
                        "risk_reason": "QUARTERLY_FILER",
                    }
                ]
            }
        )
        out = extract_supplier_counters_from_payload(payload)
        assert out[VALID_KA].quarterly_filer_flag is True


class TestComplianceSignals:
    def test_rule37_open_and_at_risk(self):
        payload = _payload(
            compliance={
                "rule37": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "R1",
                        "invoice_date": "2024-01-01",
                        "status": "OVERDUE_UNPAID",
                        "itc_at_risk_paise": 15000,
                    },
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "R2",
                        "invoice_date": "2024-01-02",
                        "status": "OK",
                        "itc_at_risk_paise": 999,
                    },
                ],
                "rule37_pending_verification": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "R3",
                        "invoice_date": "2024-01-03",
                        "status": "PENDING_VERIFICATION",
                        "potential_itc_paise": 500,
                    }
                ],
            }
        )
        out = extract_supplier_counters_from_payload(payload)
        c = out[VALID_MH]
        assert c.rule37_open_count == 2
        assert c.rule37_at_risk_paise == 15500

    def test_section_17_5_and_late_filing(self):
        payload = _payload(
            compliance={
                "section_17_5": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "S1",
                        "invoice_date": "2024-04-01",
                    }
                ],
                "late_filing": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "L1",
                        "invoice_date": "2024-04-02",
                    },
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number": "L2",
                        "invoice_date": "2024-04-03",
                    },
                ],
            }
        )
        out = extract_supplier_counters_from_payload(payload)
        c = out[VALID_MH]
        assert c.section_17_5_count == 1
        assert c.late_filing_count == 2


class TestRollupAndRisk:
    def test_rollup_sums_clients(self):
        rows = [
            {
                "supplier_gstin_normalized": VALID_MH,
                "client_gstin_id": "c1",
                "supplier_trade_name": "A",
                "total_invoices": 10,
                "mismatch_invoice_count": 2,
                "rule37_open_count": 1,
                "rule37_at_risk_paise": 100,
                "section_17_5_count": 0,
                "late_filing_count": 1,
                "pr_only_count": 1,
                "quarterly_filer_flag": False,
            },
            {
                "supplier_gstin_normalized": VALID_MH,
                "client_gstin_id": "c2",
                "supplier_trade_name": "Acme Supplies",
                "total_invoices": 5,
                "mismatch_invoice_count": 1,
                "rule37_open_count": 0,
                "rule37_at_risk_paise": 0,
                "section_17_5_count": 2,
                "late_filing_count": 0,
                "pr_only_count": 0,
                "quarterly_filer_flag": True,
            },
        ]
        rolled = rollup_client_rows(rows)
        assert rolled["clients_touched_count"] == 2
        assert rolled["total_invoices"] == 15
        assert rolled["mismatch_invoice_count"] == 3
        assert abs(rolled["mismatch_rate"] - 0.2) < 1e-6
        assert rolled["rule37_open_count"] == 1
        assert rolled["section_17_5_count"] == 2
        assert rolled["quarterly_filer_flag"] is True
        assert rolled["supplier_trade_name"] == "Acme Supplies"
        assert 0 <= rolled["risk_score"] <= 100

    def test_risk_score_increases_with_rule37(self):
        low = compute_risk_score(
            rule37_open_count=0,
            section_17_5_count=0,
            mismatch_rate=0.0,
            late_filing_rate=0.0,
            quarterly_filer_flag=False,
            pr_only_count=0,
        )
        high = compute_risk_score(
            rule37_open_count=5,
            section_17_5_count=0,
            mismatch_rate=0.0,
            late_filing_rate=0.0,
            quarterly_filer_flag=False,
            pr_only_count=0,
        )
        assert high > low
        assert high == 50

    def test_counters_to_row_dict(self):
        payload = _payload(
            engine={
                "missed_itc": [
                    {
                        "supplier_gstin": VALID_MH,
                        "invoice_number_normalized": "X",
                        "invoice_date": "2024-04-01",
                    }
                ]
            }
        )
        c = extract_supplier_counters_from_payload(payload)[VALID_MH]
        row = counters_to_row_dict(
            c,
            firm_owner_id="firm1",
            client_gstin_id="client1",
            now_iso="2024-05-01T00:00:00+00:00",
        )
        assert row["firm_owner_id"] == "firm1"
        assert row["client_gstin_id"] == "client1"
        assert row["total_invoices"] == 1
        assert row["mismatch_invoice_count"] == 1


class TestGstinMismatchAttribution:
    def test_both_valid_gstins_counted(self):
        payload = _payload(
            engine={
                "gstin_mismatch": [
                    {
                        "gstr_supplier_gstin": VALID_MH,
                        "pr_supplier_gstin": VALID_KA,
                        "invoice_number_normalized": "M1",
                        "invoice_date": "2024-04-01",
                    }
                ]
            }
        )
        out = extract_supplier_counters_from_payload(payload)
        assert VALID_MH in out
        assert VALID_KA in out
        assert len(out[VALID_MH].mismatch_keys) == 1
        assert len(out[VALID_KA].mismatch_keys) == 1
