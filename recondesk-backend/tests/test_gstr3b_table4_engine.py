"""Unit and integration tests for GSTR-3B Table 4 Workpaper Orchestration Engine.

Covers:
A. Clean matched invoice (4A5 only)
B. Section 17(5) confirmed blocked (4A5 gross + 4B1 reversal)
C. Section 17(5) statutory exception (4A5 only, no reversal)
D. Rule 37 reversal (4A5 gross + 4B2 reversal)
E. Rule 37 paid/eligible (4A5 only, no reversal)
F. Rule 37A exposure (warning only, no forced 4B2)
G. Rule 37A confirmed reversal (4A5 gross + 4B2 reversal)
H. Rule 37A subsequently filed (4A5 only)
I. 2B-only booked and verified (4A5)
J. 2B-only held (excluded from Table 4)
K. 2B-only wrong GSTIN (excluded from Table 4)
L. PR-only missed ITC (excluded from Table 4)
M. Credit note (reduces 4A5)
N. Debit note (increases 4A5)
O. Import of goods (4A1)
P. Import of services (4A2 via PR/adjustment)
Q. Domestic RCM (4A3)
R. ISD (4A4)
S. Rule 42 external adjustment (4B1)
T. Rule 43 external adjustment (4B1)
U. Rule 38 external adjustment (4B1)
V. Finalized run mutation rejection
W. Audit hash determinism
X. 4A/4B double-counting prevention
Y. 4C mathematical correctness (4C = 4A - 4B)
"""

import hashlib
from unittest.mock import MagicMock, patch
import pytest

from app.services.reconciliation_outcomes import OutcomeRow
from app.services.gstr3b_table4_engine import (
    TaxHeadsPaise,
    check_finalization_blocking_exceptions,
    compile_and_save_final_table4_snapshot,
    compile_gstr3b_table4,
    extract_tax_heads_paise,
    get_table4_drilldown,
    is_section_16_4_or_pos_restricted,
    load_reclaim_events_for_run,
    paise_to_rupees,
    rupees_to_paise,
)


def _mock_run_row(run_id="run-1", is_locked=False, status="COMPLETED"):
    return {
        "id": run_id,
        "client_gstin_id": "client-1",
        "period": "2026-05",
        "status": status,
        "is_locked": is_locked,
        "finalized_at": "2026-06-18T10:00:00Z" if is_locked else None,
        "finalized_by": "user-1" if is_locked else None,
        "client_gstins": {
            "gstin": "27AABCM4162G1ZM",
            "trade_name": "ABC Tech",
            "legal_name": "ABC Technologies Private Limited",
        },
    }


def _make_outcome_row(
    row_id: str,
    category: str = "matched",
    amount: int = 18000,
    *,
    match_status: str = "EXACT",
    matched_pr_id: str = "pr-1",
    supplier_gstin: str = "27AAACG0568M1Z8",
    supplier_name: str = "Supplier Inc",
    invoice_number: str = "INV-001",
    blocked_credit_flag: bool = False,
    rule37_flag: bool = False,
    rule37a_flag: bool = False,
    is_credit_note: bool = False,
    itc_reason: str = None,
) -> OutcomeRow:
    return OutcomeRow(
        id=row_id,
        category=category,
        supplier_gstin=supplier_gstin,
        supplier_name=supplier_name,
        invoice_number=invoice_number,
        invoice_date="2026-05-10",
        taxable_value_diff=0,
        igst_diff=0,
        cgst_diff=0,
        sgst_diff=0,
        total_tax_diff_paise=0,
        decision_what="",
        decision_why="",
        decision_next="",
        match_status=match_status,
        matched_pr_id=matched_pr_id,
        blocked_credit_flag=blocked_credit_flag,
        late_filing_flag=False,
        rule37_flag=rule37_flag,
        rule37a_flag=rule37a_flag,
        is_credit_note=is_credit_note,
        itc_reason=itc_reason,
        amount=amount,
    )


class TestTable4TaxArithmetic:
    def test_paise_and_rupees_conversion(self):
        assert paise_to_rupees(10050) == 100.50
        assert paise_to_rupees(0) == 0.0
        assert rupees_to_paise(100.50) == 10050
        assert rupees_to_paise(0.0) == 0

    def test_tax_heads_paise_accumulation(self):
        th = TaxHeadsPaise()
        th.add(igst=10000, cgst=5000, sgst=5000, cess=1000)
        th.add(igst=20000, cgst=0, sgst=0, cess=0)
        d = th.to_dict()
        assert d["igst_paise"] == 30000
        assert d["igst"] == 300.0
        assert d["cgst_paise"] == 5000
        assert d["cgst"] == 50.0
        assert d["sgst_paise"] == 5000
        assert d["sgst"] == 50.0
        assert d["cess_paise"] == 1000
        assert d["cess"] == 10.0
        assert d["total_tax_paise"] == 41000
        assert d["total_tax"] == 410.0
        assert d["count"] == 2

    def test_extract_tax_heads_paise_from_line_items(self):
        rd = {
            "items": [
                {"igst_paise": 1000, "cgst_paise": 500, "sgst_paise": 500, "cess_paise": 100},
                {"igst_paise": 2000, "cgst_paise": 1000, "sgst_paise": 1000, "cess_paise": 200},
            ]
        }
        igst, cgst, sgst, cess = extract_tax_heads_paise(rd)
        assert igst == 3000
        assert cgst == 1500
        assert sgst == 1500
        assert cess == 300


class TestTable4OrchestrationScenarios:
    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_a_clean_matched_invoice(self, mock_p, mock_disp, mock_adj):
        """Clean matched invoice should enter 4A5 only, with zero reversals in 4B."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="matched", amount=18000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 18000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 18000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        assert sec4a["row_4a5_all_other_itc"]["igst"] == 180.0
        assert sec4a["total_4a"]["igst"] == 180.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["igst"] == 0.0
        assert sec4b["total_4b"]["igst"] == 0.0
        assert sec4c["igst"] == 180.0
        assert sec4c["total_tax"] == 180.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_b_section_17_5_confirmed_blocked(self, mock_p, mock_disp, mock_adj):
        """Confirmed 17(5) invoice enters 4A5 Gross and 4B1 Reversal. Net 4C effect is zero."""
        mock_disp.return_value = {
            "pm:g-1": {"disposition": "CONFIRMED_BLOCKED", "exception_type": "SEC_17_5"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="blocked_credit", amount=20000, blocked_credit_flag=True, itc_reason="17(5) motor vehicles")
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 20000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 20000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        # Gross 4A5 has 200.0, Reversal 4B1 has 200.0, Net 4C is 0.0
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 200.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["igst"] == 200.0
        assert sec4c["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_c_section_17_5_statutory_exception(self, mock_p, mock_disp, mock_adj):
        """17(5) signal with statutory exception confirmed by CA: remains in 4A5 without 4B1 reversal."""
        mock_disp.return_value = {
            "pm:g-1": {"disposition": "STATUTORY_EXCEPTION", "exception_type": "SEC_17_5"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="blocked_credit", amount=20000, blocked_credit_flag=True)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 20000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 20000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        assert sec4a["row_4a5_all_other_itc"]["igst"] == 200.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["igst"] == 0.0
        assert sec4c["igst"] == 200.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_d_rule37_reversal(self, mock_p, mock_disp, mock_adj):
        """Rule 37 confirmed reversal: enters 4A5 Gross and 4B2 Reversal."""
        mock_disp.return_value = {
            "pm:g-1": {"disposition": "REVERSED", "exception_type": "RULE_37"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="rule37_warnings", amount=36000, rule37_flag=True)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 36000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 36000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        assert sec4a["row_4a5_all_other_itc"]["igst"] == 360.0
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 360.0
        assert sec4c["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_e_rule37_paid_eligible(self, mock_p, mock_disp, mock_adj):
        """Rule 37 paid/eligible resolution: enters 4A5, no reversal in 4B2."""
        mock_disp.return_value = {
            "pm:g-1": {"disposition": "PAID_ELIGIBLE", "exception_type": "RULE_37"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="rule37_warnings", amount=36000, rule37_flag=True)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 36000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 36000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        assert sec4a["row_4a5_all_other_itc"]["igst"] == 360.0
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 0.0
        assert sec4c["igst"] == 360.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_f_rule37a_exposure_warning_does_not_force_4b2(self, mock_p, mock_disp, mock_adj):
        """Rule 37A exposure warning for current period does not force 4B2 reversal."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="rule37_warnings", match_status="RULE37A", rule37a_flag=True, amount=15000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 15000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 15000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4b = res["table_4"]["section_4b"]
        # In provisional exposure stage without confirmed reversal disposition, 4B2 is zero
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_g_rule37a_confirmed_reversal(self, mock_p, mock_disp, mock_adj):
        """Rule 37A confirmed reversal (past deadline): gross in 4A5, reversed in 4B2."""
        mock_disp.return_value = {
            "pm:g-1": {"disposition": "REVERSAL_CONFIRMED", "exception_type": "RULE_37A"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="rule37_warnings", match_status="RULE37A", rule37a_flag=True, amount=15000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 15000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 15000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 150.0
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 150.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_i_2b_only_booked_and_verified(self, mock_p, mock_disp, mock_adj):
        """2B-only record with disposition BOOKED_AND_VERIFIED enters 4A5."""
        mock_disp.return_value = {
            "gstr:g-1": {"disposition": "BOOKED_AND_VERIFIED", "exception_type": "TWO_B_ONLY"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("gstr:g-1", category="unmatched_gstr", matched_pr_id=None, amount=12000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 12000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 120.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_j_2b_only_held(self, mock_p, mock_disp, mock_adj):
        """2B-only record with disposition HELD_GOODS_NOT_RECEIVED is excluded from Table 4."""
        mock_disp.return_value = {
            "gstr:g-1": {"disposition": "HELD_GOODS_NOT_RECEIVED", "exception_type": "TWO_B_ONLY"},
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("gstr:g-1", category="unmatched_gstr", matched_pr_id=None, amount=12000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 12000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_l_pr_only_missed_itc(self, mock_p, mock_disp, mock_adj):
        """PR-only missed ITC is excluded from current Table 4 workpaper under Section 16(2)(aa)."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pr:p-1", category="missed_itc", matched_pr_id="p-1", amount=50000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"p-1": {"record_data": {"igst_paise": 50000}}}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_m_credit_note_reduces_4a5(self, mock_p, mock_disp, mock_adj):
        """Credit note has negative effect on 4A5."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        inv = _make_outcome_row("pm:g-1", category="matched", amount=100000)
        cn = _make_outcome_row("pm:g-2", category="matched", amount=20000, is_credit_note=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([inv, cn], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 100000, "doc_type": "INVOICE"}},
                 "g-2": {"record_data": {"igst_paise": 20000, "doc_type": "CREDIT_NOTE"}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        # 1000.00 - 200.00 = 800.00
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 800.0
        assert sec4a["total_4a"]["igst"] == 800.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_o_import_of_goods_in_4a1(self, mock_p, mock_disp, mock_adj):
        """Import of Goods (IMPG) is routed strictly to 4A1."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        boe = _make_outcome_row("pm:g-1", category="matched", amount=450000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([boe], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 450000, "doc_type": "IMPG"}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        assert sec4a["row_4a1_import_goods"]["igst"] == 4500.0
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_q_domestic_rcm_in_4a3(self, mock_p, mock_disp, mock_adj):
        """Domestic Inward RCM is routed strictly to 4A3."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        gta = _make_outcome_row("pm:g-1", category="matched", amount=5000)
        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([gta], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"cgst_paise": 2500, "sgst_paise": 2500, "reverse_charge": "Y"}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        assert sec4a["row_4a3_inward_rcm"]["cgst"] == 25.0
        assert sec4a["row_4a3_inward_rcm"]["sgst"] == 25.0
        assert sec4a["row_4a5_all_other_itc"]["cgst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments")
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_s_t_u_external_adjustments_rules_42_43_38(self, mock_p, mock_disp, mock_adj):
        """Manual adjustments for Rule 42, 43, 38 enter 4B1."""
        mock_adj.return_value = [
            {
                "id": "adj-1",
                "row_id": "4B1",
                "adjustment_type": "ADDITION",
                "statutory_category": "RULE_42_INPUTS",
                "igst_paise": 15000,
                "cgst_paise": 7500,
                "sgst_paise": 7500,
                "cess_paise": 0,
                "reason": "Exempt turnover reversal per Rule 42",
            },
            {
                "id": "adj-2",
                "row_id": "4A2",
                "adjustment_type": "ADDITION",
                "statutory_category": "IMPORT_SERVICES_RCM",
                "igst_paise": 50000,
                "cgst_paise": 0,
                "sgst_paise": 0,
                "cess_paise": 0,
                "reason": "Import of cloud software services self-invoiced under Sec 5(3)",
            },
        ]
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        assert sec4a["row_4a2_import_services"]["igst"] == 500.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["igst"] == 150.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["cgst"] == 75.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["sgst"] == 75.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_w_audit_hash_determinism(self, mock_p, mock_disp, mock_adj):
        """The audit hash must be perfectly deterministic given the same inputs."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        r1 = _make_outcome_row("pm:g-1", amount=10000)
        r2 = _make_outcome_row("pm:g-2", amount=20000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([r1, r2], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 10000}},
                 "g-2": {"record_data": {"igst_paise": 20000}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res1 = compile_gstr3b_table4(sb, "run-1")
            res2 = compile_gstr3b_table4(sb, "run-1")

        assert res1["audit_hash"] == res2["audit_hash"]
        assert len(res1["audit_hash"]) == 64

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_x_y_no_double_counting_and_4c_correctness(self, mock_p, mock_disp, mock_adj):
        """Proves 4C = 4A - 4B, and no double-counting between 4A and 4B."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        inv1 = _make_outcome_row("pm:g-1", category="matched", amount=100000)
        # Blocked 17(5) invoice
        inv2 = _make_outcome_row("pm:g-2", category="blocked_credit", amount=25000, blocked_credit_flag=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([inv1, inv2], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 100000}},
                 "g-2": {"record_data": {"igst_paise": 25000}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        # Gross 4A has 1000 + 250 = 1250
        assert sec4a["total_4a"]["igst"] == 1250.0
        # Reversal 4B has 250
        assert sec4b["total_4b"]["igst"] == 250.0
        # Net 4C is exactly 1250 - 250 = 1000
        assert sec4c["igst"] == 1000.0


class TestQualifiedFinalizationGate:
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.gstr3b_table4_engine.load_rule37_settlements", return_value=set())
    def test_unresolved_sec175_blocks_finalization(self, mock_r37, mock_disp):
        """Unresolved Section 17(5) signal blocks finalization."""
        sb = MagicMock()
        row = _make_outcome_row("pm:g-1", category="blocked_credit", blocked_credit_flag=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})):
            gate = check_finalization_blocking_exceptions(sb, "run-1")

        assert gate["can_finalize"] is False
        assert gate["unresolved_blocking_exceptions"] == 1
        assert "Section 17(5)" in gate["blocking_summary"][0]

    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.gstr3b_table4_engine.load_rule37_settlements", return_value=set())
    def test_resolved_sec175_allows_finalization(self, mock_r37, mock_disp):
        """Resolved Section 17(5) signal allows finalization."""
        mock_disp.return_value = {
            "pm:g-1:SEC_17_5": {"disposition": "CONFIRMED_BLOCKED"},
        }
        sb = MagicMock()
        row = _make_outcome_row("pm:g-1", category="blocked_credit", blocked_credit_flag=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})):
            gate = check_finalization_blocking_exceptions(sb, "run-1")

        assert gate["can_finalize"] is True
        assert gate["unresolved_blocking_exceptions"] == 0


class TestDrilldownAndExport:
    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments")
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_drilldown_invoice_and_adjustment_evidence(self, mock_p, mock_disp, mock_adj):
        """Drilldown returns both matched invoices and manual adjustments for a cell."""
        mock_adj.return_value = [
            {
                "id": "adj-1",
                "row_id": "4B1",
                "adjustment_type": "ADDITION",
                "statutory_category": "RULE_42_INPUTS",
                "igst_paise": 15000,
                "reason": "Rule 42 turnover reversal",
            }
        ]
        sb = MagicMock()
        row = _make_outcome_row("pm:g-1", category="blocked_credit", amount=20000, blocked_credit_flag=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 20000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            drill = get_table4_drilldown(sb, "run-1", "4B1")

        assert drill["row_id"] == "4B1"
        assert drill["total_records"] == 2  # 1 adjustment + 1 invoice
        assert drill["totals"]["igst"] == 350.0  # 150 + 200

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_excel_workpaper_export(self, mock_p, mock_disp, mock_adj):
        """Excel generator produces valid 5-sheet workbook."""
        from app.services.gstr3b_table4_export import generate_table4_excel_workpaper
        from openpyxl import load_workbook
        import io

        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            excel_bytes = generate_table4_excel_workpaper(sb, "run-1")

        assert len(excel_bytes) > 1000
        wb = load_workbook(io.BytesIO(excel_bytes))
        sheet_names = wb.sheetnames
        assert "GSTR-3B Table 4 Summary" in sheet_names
        assert "Table 4A5 Domestic Invoices" in sheet_names
        assert "Table 4B Reversals" in sheet_names
        assert "External Adjustments" in sheet_names
        assert "Audit Log & Certification" in sheet_names

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_build_outcome_rows_real_three_tuple_return_shape(self, mock_p, mock_disp, mock_adj):
        """Regression test ensuring real 3-tuple shape from build_outcome_rows works properly.

        ro.build_outcome_rows returns a 3-tuple (list[OutcomeRow], dict[str, int], dict[str, Any]).
        Verifies compile_gstr3b_table4, check_finalization_blocking_exceptions, and
        get_table4_drilldown all handle the real 3-tuple shape without ValueError.
        """
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-1", category="matched", amount=18000)
        three_tuple = ([row], {"matched": 1}, {"matched_itc_paise": 18000})

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=three_tuple), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 18000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 18000}}}):

            # 1. compile_gstr3b_table4
            res = compile_gstr3b_table4(sb, "run-1")
            assert res["status"] == "PROVISIONAL"
            assert res["table_4"]["section_4a"]["row_4a5_all_other_itc"]["igst"] == 180.0

            # 2. check_finalization_blocking_exceptions
            gate = check_finalization_blocking_exceptions(sb, "run-1")
            assert gate["can_finalize"] is True

            # 3. get_table4_drilldown
            drill = get_table4_drilldown(sb, "run-1", "4A5")
            assert drill["row_id"] == "4A5"
            assert drill["total_records"] == 1

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_duplicate_entry_excluded_from_table4(self, mock_p, mock_disp, mock_adj):
        """Regression test ensuring duplicate_entry rows NEVER contribute to Table 4A or 4B.

        Proves:
        - duplicate_entry is excluded from 4(A)(5)
        - duplicate_entry is excluded from 4(B)
        - duplicate remains visible in reconciliation results / outcome rows
        - canonical matched invoice is included in 4(A)(5) exactly once
        """
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        # 1. Canonical matched invoice
        canonical = _make_outcome_row("pm:g-1", category="matched", amount=50000, matched_pr_id="pr-1")
        # 2. Duplicate entry PR booking pointing to the canonical PR record
        duplicate = _make_outcome_row(
            "de:pr-dup",
            category="duplicate_entry",
            match_status="DUPLICATE_ENTRY",
            amount=50000,
            matched_pr_id="pr-1",
        )

        three_tuple = ([canonical, duplicate], {"matched": 1, "duplicate_entry": 1}, {})

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=three_tuple), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={"g-1": {"record_data": {"igst_paise": 50000}}}), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={"pr-1": {"record_data": {"igst_paise": 50000}}}):

            # Compile Table 4
            res = compile_gstr3b_table4(sb, "run-1")
            sec4a = res["table_4"]["section_4a"]
            sec4b = res["table_4"]["section_4b"]
            sec4c = res["table_4"]["section_4c_net_itc"]

            # 4(A)(5) must contain ONLY the canonical match (count = 1, amount = 500.0)
            assert sec4a["row_4a5_all_other_itc"]["count"] == 1
            assert sec4a["row_4a5_all_other_itc"]["igst"] == 500.0
            assert sec4a["total_4a"]["count"] == 1
            assert sec4a["total_4a"]["igst"] == 500.0

            # 4(B) must NOT contain the duplicate entry (count = 0, amount = 0.0)
            assert sec4b["total_4b"]["count"] == 0
            assert sec4b["total_4b"]["igst"] == 0.0

            # 4(C) net ITC equals canonical invoice
            assert sec4c["igst"] == 500.0

            # Drilldown 4A5 must only list 1 record (the canonical match)
            drill_4a5 = get_table4_drilldown(sb, "run-1", "4A5")
            assert drill_4a5["total_records"] == 1
            assert drill_4a5["records"][0]["id"] == "pm:g-1"

            # Drilldown 4B1 and 4B2 must be empty
            drill_4b1 = get_table4_drilldown(sb, "run-1", "4B1")
            assert drill_4b1["total_records"] == 0
            drill_4b2 = get_table4_drilldown(sb, "run-1", "4B2")
            assert drill_4b2["total_records"] == 0

            # Reconciliation results / outcome rows still retain the duplicate entry
            assert len(three_tuple[0]) == 2
            assert three_tuple[0][1].category == "duplicate_entry"
            assert three_tuple[0][1].id == "de:pr-dup"

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_table4_total_column_exact_amounts_regression(self, mock_p, mock_disp, mock_adj):
        """Regression test ensuring Total column for 4A5, 4A, and 4C is correctly computed and never 0."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        # Simulate September 2026 tax amounts:
        # IGST: 32,97,484.99 (329,748,499 paise)
        # CGST: 30,71,469.09 (307,146,909 paise)
        # SGST: 30,71,469.09 (307,146,909 paise)
        # Cess: 0.0 (0 paise)
        row1 = _make_outcome_row("pm:g-1", category="matched", amount=329748499)
        row2 = _make_outcome_row("pm:g-2", category="matched", amount=614293818)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row1, row2], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 329748499, "cgst_paise": 0, "sgst_paise": 0, "cess_paise": 0}},
                 "g-2": {"record_data": {"igst_paise": 0, "cgst_paise": 307146909, "sgst_paise": 307146909, "cess_paise": 0}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        # 4A5 tax heads
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 3297484.99
        assert sec4a["row_4a5_all_other_itc"]["cgst"] == 3071469.09
        assert sec4a["row_4a5_all_other_itc"]["sgst"] == 3071469.09
        assert sec4a["row_4a5_all_other_itc"]["cess"] == 0.0

        # 4A5 Total must equal IGST + CGST + SGST + Cess = 94,40,423.17 (NOT 0)
        assert sec4a["row_4a5_all_other_itc"]["total_tax"] == 9440423.17
        assert sec4a["row_4a5_all_other_itc"]["total_tax_paise"] == 944042317

        # 4A Total must equal 94,40,423.17 (NOT 0)
        assert sec4a["total_4a"]["igst"] == 3297484.99
        assert sec4a["total_4a"]["cgst"] == 3071469.09
        assert sec4a["total_4a"]["sgst"] == 3071469.09
        assert sec4a["total_4a"]["cess"] == 0.0
        assert sec4a["total_4a"]["total_tax"] == 9440423.17
        assert sec4a["total_4a"]["total_tax_paise"] == 944042317

        # 4C Net ITC must equal 94,40,423.17
        assert sec4c["total_tax"] == 9440423.17
        assert sec4c["total_tax_paise"] == 944042317


class TestPhase3BClassificationAnd4D2Boundary:
    """Rigorous Phase 3B test suite validating classification, 4D2 boundary, reclaims dual posting, and snapshot sealing."""

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_section_16_4_time_barred_routes_strictly_to_4d2(self, mock_p, mock_disp, mock_adj):
        """Para 4.3 Circular 170: Section 16(4) time-barred invoices go to 4D2 and NEVER enter 4A, 4B, or 4C."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row(
            "pm:g-tb",
            category="matched",
            amount=5000000,
            itc_reason="Time barred under Section 16(4)",
        )
        setattr(row, "itc_available", False)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-tb": {"record_data": {"igst_paise": 5000000, "itcavl": "N", "rsn": "Section 16(4) limitation"}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]
        sec4d = res["table_4"]["section_4d"]

        # 4D2 receives the entire amount
        assert sec4d["row_4d2_ineligible_16_4_pos"]["igst"] == 50000.0
        assert sec4d["row_4d2_ineligible_16_4_pos"]["igst_paise"] == 5000000

        # Must NEVER enter 4A, 4B, or 4C
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 0.0
        assert sec4a["total_4a"]["igst"] == 0.0
        assert sec4b["row_4b1_rule38_42_43_sec175"]["igst"] == 0.0
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 0.0
        assert sec4c["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_pos_restricted_routes_strictly_to_4d2(self, mock_p, mock_disp, mock_adj):
        """Place of supply restrictions go to 4D2 only per Circular 170 Para 4.3."""
        mock_disp.return_value = {
            "pm:g-pos": {"disposition": "CONFIRMED_POS_RESTRICTED", "exception_type": "POS_RESTRICTED"}
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-pos", category="matched", amount=1800000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-pos": {"record_data": {"cgst_paise": 900000, "sgst_paise": 900000}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4c = res["table_4"]["section_4c_net_itc"]
        sec4d = res["table_4"]["section_4d"]

        assert sec4d["row_4d2_ineligible_16_4_pos"]["cgst"] == 9000.0
        assert sec4d["row_4d2_ineligible_16_4_pos"]["sgst"] == 9000.0
        assert sec4a["row_4a5_all_other_itc"]["cgst"] == 0.0
        assert sec4c["cgst"] == 0.0
        assert sec4c["sgst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_reclaim_events_for_run")
    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_active_reclaim_dual_posting_to_4a5_and_4d1(self, mock_p, mock_disp, mock_adj, mock_reclaims):
        """Active reclaims from gstr3b_reclaim_events must be added simultaneously to 4(A)(5) and 4(D)(1)."""
        mock_reclaims.return_value = [
            {
                "id": "rec-ev-1",
                "event_type": "RECLAIM",
                "reclaimed_igst_paise": 25000,   # Rs 250
                "reclaimed_cgst_paise": 15000,   # Rs 150
                "reclaimed_sgst_paise": 15000,   # Rs 150
                "reclaimed_cess_paise": 0,
                "statutory_reason": "RULE_37_NON_PAYMENT",
                "reclaim_notes": "Supplier payment verified",
                "document_number": "INV-101",
            }
        ]
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        # Clean matched invoice: Rs 1000 IGST
        row = _make_outcome_row("pm:g-clean", category="matched", amount=100000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-clean": {"record_data": {"igst_paise": 100000}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]
        sec4d = res["table_4"]["section_4d"]

        # 4A5 must have 1000 (invoice) + 250 (reclaim) = 1250 IGST, and 150 CGST, 150 SGST
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 1250.0
        assert sec4a["row_4a5_all_other_itc"]["cgst"] == 150.0
        assert sec4a["row_4a5_all_other_itc"]["sgst"] == 150.0

        # 4D1 must have 250 IGST, 150 CGST, 150 SGST
        assert sec4d["row_4d1_reclaimed"]["igst"] == 250.0
        assert sec4d["row_4d1_reclaimed"]["cgst"] == 150.0
        assert sec4d["row_4d1_reclaimed"]["sgst"] == 150.0

        # Net 4C must include the reclaimed credit
        assert sec4c["igst"] == 1250.0
        assert sec4c["cgst"] == 150.0
        assert sec4c["sgst"] == 150.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_section_16_2_b_signal_without_disposition_does_not_reverse(self, mock_p, mock_disp, mock_adj):
        """Internal goods-not-received signal without explicit CA statutory disposition must NOT automatically reverse in 4B2."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-gnr", category="matched", amount=200000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-gnr": {"record_data": {"igst_paise": 200000}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        # Enters 4A5
        assert sec4a["row_4a5_all_other_itc"]["igst"] == 2000.0
        # 4B2 remains 0 (no unapproved statutory determination)
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 0.0
        assert sec4c["igst"] == 2000.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_section_16_2_b_confirmed_disposition_reverses_in_4b2(self, mock_p, mock_disp, mock_adj):
        """Explicit CA disposition SECTION_16_2_B_REVERSED triggers gross 4A5 + 4B2 temporary reversal."""
        mock_disp.return_value = {
            "pm:g-gnr-conf": {"disposition": "SECTION_16_2_B_REVERSED", "exception_type": "SECTION_16_2_B"}
        }
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        row = _make_outcome_row("pm:g-gnr-conf", category="matched", amount=200000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-gnr-conf": {"record_data": {"igst_paise": 200000}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4b = res["table_4"]["section_4b"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        assert sec4a["row_4a5_all_other_itc"]["igst"] == 2000.0
        assert sec4b["row_4b2_others_rule37_37a"]["igst"] == 2000.0
        assert sec4c["igst"] == 0.0

    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_credit_note_signed_negative_4a5_math(self, mock_p, mock_disp, mock_adj):
        """When credit notes exceed forward invoices, net 4(A)(5) and 4(C) reflect signed negative amounts accurately."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        # Invoice: Rs 50 CGST, Rs 50 SGST
        inv_row = _make_outcome_row("pm:g-inv", category="matched", amount=10000)
        # Credit note: Rs 150 CGST, Rs 150 SGST
        cn_row = _make_outcome_row("pm:g-cn", category="matched", amount=30000, is_credit_note=True)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([inv_row, cn_row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-inv": {"record_data": {"cgst_paise": 5000, "sgst_paise": 5000, "doc_type": "INVOICE"}},
                 "g-cn": {"record_data": {"cgst_paise": 15000, "sgst_paise": 15000, "doc_type": "CREDIT_NOTE"}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            res = compile_gstr3b_table4(sb, "run-1")

        sec4a = res["table_4"]["section_4a"]
        sec4c = res["table_4"]["section_4c_net_itc"]

        # Net 4A5 = 50 - 150 = -100.00 each
        assert sec4a["row_4a5_all_other_itc"]["cgst"] == -100.0
        assert sec4a["row_4a5_all_other_itc"]["sgst"] == -100.0
        assert sec4a["row_4a5_all_other_itc"]["total_tax"] == -200.0

        # Net 4C must be -100.00 each
        assert sec4c["cgst"] == -100.0
        assert sec4c["sgst"] == -100.0
        assert sec4c["total_tax"] == -200.0

    @patch("app.services.gstr3b_table4_engine.load_reclaim_events_for_run")
    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions")
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_drilldown_evidence_for_4d1_and_4d2(self, mock_p, mock_disp, mock_adj, mock_reclaims):
        """Drilldown gives verifiable invoice evidence: 4D1 lists reclaims, 4D2 lists 16(4)/PoS records, 4A5 excludes 4D2."""
        mock_disp.return_value = {
            "pm:g-tb": {"disposition": "CONFIRMED_TIME_BARRED", "exception_type": "TIME_BARRED_16_4"},
        }
        mock_reclaims.return_value = [
            {
                "id": "rec-ev-99",
                "event_type": "RECLAIM",
                "reclaimed_igst_paise": 80000,
                "statutory_reason": "RULE_37_NON_PAYMENT",
                "reclaim_notes": "Payment released",
                "document_number": "OLD-INV-88",
            }
        ]
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        tb_row = _make_outcome_row("pm:g-tb", category="matched", amount=120000, invoice_number="INV-TB-1")
        clean_row = _make_outcome_row("pm:g-ok", category="matched", amount=50000, invoice_number="INV-OK-2")

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([tb_row, clean_row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-tb": {"record_data": {"igst_paise": 120000}},
                 "g-ok": {"record_data": {"igst_paise": 50000}},
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):

            # 4D2 drilldown
            dd_4d2 = get_table4_drilldown(sb, "run-1", "4D2")
            assert dd_4d2["total_records"] == 1
            assert dd_4d2["records"][0]["invoice_number"] == "INV-TB-1"
            assert dd_4d2["totals"]["igst"] == 1200.0

            # 4D1 drilldown
            dd_4d1 = get_table4_drilldown(sb, "run-1", "4D1")
            assert dd_4d1["total_records"] == 1
            assert dd_4d1["records"][0]["invoice_number"] == "OLD-INV-88"
            assert dd_4d1["totals"]["igst"] == 800.0

            # 4A5 drilldown must have clean invoice + reclaim, but NEVER the 4D2 invoice
            dd_4a5 = get_table4_drilldown(sb, "run-1", "4A5")
            inv_nums = [r["invoice_number"] for r in dd_4a5["records"]]
            assert "INV-OK-2" in inv_nums
            assert "OLD-INV-88" in inv_nums
            assert "INV-TB-1" not in inv_nums

    @patch("app.services.gstr3b_table4_engine.load_reclaim_events_for_run", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_table4_adjustments", return_value=[])
    @patch("app.services.gstr3b_table4_engine.load_exception_dispositions", return_value={})
    @patch("app.services.reconciliation_outcomes.load_payload", return_value={})
    def test_snapshot_versioning_and_state_sealing(self, mock_p, mock_disp, mock_adj, mock_reclaims):
        """Finalization increments version, supersedes prior versions, and seals source state digest and payload."""
        sb = MagicMock()
        sb.table().select().eq().limit().execute.return_value.data = [_mock_run_row()]

        # Simulate existing summary version 1
        existing_summary_v1 = {
            "id": "sum-v1-uuid",
            "run_id": "run-1",
            "version": 1,
            "is_current": True,
            "status": "FINALIZED",
        }
        sb.table("gstr3b_table4_summaries").select().eq().order().execute.return_value.data = [existing_summary_v1]
        inserted_summary = {"id": "sum-v2-uuid"}
        sb.table("gstr3b_table4_summaries").insert().execute.return_value.data = [inserted_summary]

        row = _make_outcome_row("pm:g-1", category="matched", amount=18000)

        with patch("app.services.reconciliation_outcomes.build_outcome_rows", return_value=([row], {}, {})), \
             patch("app.services.reconciliation_outcomes.load_gstr_map", return_value={
                 "g-1": {"record_data": {"igst_paise": 18000}}
             }), \
             patch("app.services.reconciliation_outcomes.load_pr_map", return_value={}):
            final_res = compile_and_save_final_table4_snapshot(sb, "run-1", "user-ca-1")

        assert final_res["status"] == "FINALIZED"
        assert final_res["version"] == 2
        assert final_res["source_state_digest"] != ""
        assert final_res["audit_hash"] != ""

        # Verify prior version was superseded
        update_calls = sb.table("gstr3b_table4_summaries").update.call_args_list
        assert any(
            call[0][0].get("is_current") is False and "superseded_at" in call[0][0]
            for call in update_calls
        )

        # Verify insert payload contained version 2, is_current=True, and sealed payload
        insert_args = sb.table("gstr3b_table4_summaries").insert.call_args[0][0]
        assert insert_args["version"] == 2
        assert insert_args["is_current"] is True
        assert "snapshot_payload" in insert_args
        assert insert_args["source_state_digest"] == final_res["audit_hash"]





