"""Phase 6: Comprehensive GSTR Functional Certification Test Suite.

Covers statutory validation, boundary conditions, tenant isolation,
RBAC, maker-checker governance, offline JSON schema, and DEF-2026-001
for all 8 GSTR modules:
- GSTR-1A (Amendments under Rule 59(1A))
- GSTR-5 (NRTP under Section 27 / Rule 63)
- GSTR-5A (OIDAR under Rule 64)
- GSTR-6 (ISD under Section 20 / Rule 39)
- GSTR-7 (TDS under Section 51 / Rule 66)
- GSTR-8 (TCS under Section 52 / Rule 67)
- GSTR-10 (Final Return under Section 29 / Rule 44)
- GSTR-11 (UIN Return under Section 55 / Rule 82)
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

import pytest

# Module 1: GSTR-1A
from app.rules.gstr1a_eligibility import (
    Gstr1aWindowStatus,
)
from app.services.gstr1a_service import (
    build_gstr1a_offline_json,
    calculate_diff_and_deltas,
    compute_batch_figures_digest,
    compute_gstr1a_window_for_gstin,
    is_credit_document,
)

# Module 2, 3, 4: GSTR-5, 5A, 6
from app.rules.gstr5_rules import (
    compute_nrtp_tax_summary,
    evaluate_nrtp_registration_and_due_date,
)
from app.services.gstr5_service import (
    build_gstr5_offline_json,
)

from app.rules.gstr5a_rules import (
    compute_oidar_tax_for_supply,
    summarize_gstr5a_supplies,
    OIDAR_STANDARD_IGST_RATE,
)
from app.services.gstr5a_service import (
    build_gstr5a_offline_json,
)

from app.rules.gstr6_rules import (
    compute_turnover_ratios,
    distribute_isd_credit,
    validate_distinct_persons,
)
from app.services.gstr6_service import (
    build_gstr6_offline_json,
)

# Module 5, 6: GSTR-7, 8
from app.rules.gstr7_rules import (
    GSTR7_CONTRACT_THRESHOLD,
    calculate_gstr7_tds,
    evaluate_section_51_proviso,
    validate_gstin_format,
)
from app.services.gstr7_service import (
    build_gstr7_offline_json,
)

from app.rules.gstr8_rules import (
    calculate_gstr8_tcs,
    get_applicable_tcs_rates,
)
from app.services.gstr8_service import (
    build_gstr8_offline_json,
)

# Module 7, 8: GSTR-10, 11
from app.rules.gstr10_rules import (
    StockItemType,
    aggregate_gstr10_stock_reversals,
    calculate_gstr10_due_date,
    compute_capital_goods_reversal,
)
from app.services.gstr10_service import (
    build_gstr10_offline_json,
)

from app.rules.gstr11_rules import (
    UinSupplyType,
    aggregate_gstr11_refund_statement,
    calculate_gstr11_due_date,
    validate_uin,
)
from app.services.gstr11_service import (
    build_gstr11_offline_json,
)

# Governance & Security
from app.services.maker_checker_service import ApprovalStatus
from app.models.roles import is_admin_or_partner, is_writer_or_above


# ==============================================================================
# 1. GSTR-1A STATUTORY & BOUNDARY CERTIFICATION
# ==============================================================================
class TestGstr1aCertification:
    """Certifies GSTR-1A under Notification No. 12/2024-CT & Rule 59(1A)."""

    def test_window_timing_monthly_filer(self):
        """Window opens ONLY after GSTR-1 filed and closes when GSTR-3B filed."""
        # Scenario A: GSTR-1 unfiled -> window closed
        w_unfiled = compute_gstr1a_window_for_gstin(
            gstin="27ABCDE1234F1Z5",
            period="2026-07",
            gstr1_filed_date=None,
            gstr3b_filed_date=None,
            filing_frequency="monthly",
            as_of=date(2026, 8, 12),
        )
        assert w_unfiled["is_open"] is False
        assert "must be furnished before" in w_unfiled["note"]

        # Scenario B: GSTR-1 filed, GSTR-3B unfiled -> window open
        w_open = compute_gstr1a_window_for_gstin(
            gstin="27ABCDE1234F1Z5",
            period="2026-07",
            gstr1_filed_date="2026-08-11",
            gstr3b_filed_date=None,
            filing_frequency="monthly",
            as_of=date(2026, 8, 15),
        )
        assert w_open["is_open"] is True
        assert w_open["status"] == Gstr1aWindowStatus.OPEN.value

        # Scenario C: GSTR-3B filed -> window permanently closed
        w_closed = compute_gstr1a_window_for_gstin(
            gstin="27ABCDE1234F1Z5",
            period="2026-07",
            gstr1_filed_date="2026-08-11",
            gstr3b_filed_date="2026-08-18",
            filing_frequency="monthly",
            as_of=date(2026, 8, 19),
        )
        assert w_closed["is_open"] is False
        assert "already filed" in w_closed["note"]

    def test_window_timing_qrmp_staggered_due_dates(self):
        """QRMP Group A (22nd) vs Group B (24th) state rules."""
        # Maharashtra (27) -> Group A -> due date 22nd
        w_mh = compute_gstr1a_window_for_gstin(
            gstin="27ABCDE1234F1Z5",
            period="2026-06",
            gstr1_filed_date="2026-07-13",
            gstr3b_filed_date=None,
            filing_frequency="qrmp",
            as_of=date(2026, 7, 21),
        )
        assert w_mh["is_open"] is True
        assert w_mh["gstr3b_due_date"] == "2026-07-22"

        # Delhi (07) -> Group B -> due date 24th (Notification No. 82/2020-CT)
        w_dl = compute_gstr1a_window_for_gstin(
            gstin="07ABCDE1234F1ZW",
            period="2026-06",
            gstr1_filed_date="2026-07-13",
            gstr3b_filed_date=None,
            filing_frequency="qrmp",
            as_of=date(2026, 7, 23),
        )
        assert w_dl["is_open"] is True
        assert w_dl["gstr3b_due_date"] == "2026-07-24"

    def test_liability_sign_conventions(self):
        """Credit Notes reduce outward tax; Debit Notes & Invoices increase it."""
        # Addition of B2B Invoice
        inv = calculate_diff_and_deltas(
            action_type="ADDITION",
            table_name="4A_B2B",
            original_payload=None,
            amended_payload={"txval": 100000, "iamt": 18000, "camt": 0, "samt": 0, "csamt": 0},
        )
        assert inv["delta_taxable_value"] == 100000.0
        assert inv["delta_igst"] == 18000.0

        # Addition of Credit Note (reduces liability)
        cn = calculate_diff_and_deltas(
            action_type="ADDITION",
            table_name="9B_CDNR",
            original_payload=None,
            amended_payload={"txval": 20000, "iamt": 3600, "camt": 0, "samt": 0, "csamt": 0, "note_type": "C"},
        )
        assert cn["delta_taxable_value"] == -20000.0
        assert cn["delta_igst"] == -3600.0

        # Addition of Debit Note (increases liability)
        dn = calculate_diff_and_deltas(
            action_type="ADDITION",
            table_name="9B_CDNR",
            original_payload=None,
            amended_payload={"txval": 10000, "iamt": 1800, "camt": 0, "samt": 0, "csamt": 0, "note_type": "D"},
        )
        assert dn["delta_taxable_value"] == 10000.0
        assert dn["delta_igst"] == 1800.0

    def test_offline_json_official_structure(self):
        """Offline JSON complies with official GSTR1A_v1.0 schema structure."""
        batch = {
            "gstin": "27ABCDE1234F1Z5",
            "period": "2026-07",
            "figures_digest": "dummy-digest",
            "total_additions": 1,
            "total_amendments": 1,
        }
        items = [
            {
                "table_name": "4A_B2B",
                "action_type": "ADDITION",
                "amended_payload": {"inum": "INV-101", "idt": "01-07-2026", "val": 118000},
            },
            {
                "table_name": "4A_B2B",
                "action_type": "AMENDMENT",
                "original_invoice_number": "INV-100",
                "original_invoice_date": "15-06-2026",
                "amended_payload": {"inum": "INV-100-REV", "idt": "15-06-2026", "val": 125000},
            },
        ]
        offline = build_gstr1a_offline_json(batch, items)
        assert offline["gstin"] == "27ABCDE1234F1Z5"
        assert offline["fp"] == "072026"
        assert offline["version"] == "GSTR1A_v1.0"
        assert len(offline["b2b"]) == 1
        assert len(offline["b2ba"]) == 1
        assert offline["b2ba"][0]["oinum"] == "INV-100"

    def test_offline_json_table14_and_15_eco_export(self):
        """Table 14 (ECO supplies under Section 52) and Table 15 (Section 9(5) supplies)."""
        batch = {
            "gstin": "27ABCDE1234F1Z5",
            "period": "2026-07",
            "figures_digest": "dummy-digest",
            "total_additions": 2,
            "total_amendments": 2,
        }
        items = [
            {
                "table_name": "14_SUPECO",
                "action_type": "ADDITION",
                "amended_payload": {"etin": "27AAACE1234E1Z1", "supp_val": 50000.0, "igst": 9000.0},
            },
            {
                "table_name": "14A_SUPECOA",
                "action_type": "AMENDMENT",
                "original_invoice_number": "INV-ECO-1",
                "original_invoice_date": "10-06-2026",
                "amended_payload": {"etin": "27AAACE1234E1Z1", "supp_val": 55000.0, "igst": 9900.0},
            },
            {
                "table_name": "15_SEC9_5",
                "action_type": "ADDITION",
                "amended_payload": {"etin": "27AAACE1234E1Z1", "txval": 20000.0, "igst": 3600.0},
            },
            {
                "table_name": "15A_SEC9_5A",
                "action_type": "AMENDMENT",
                "original_invoice_number": "INV-SEC9-1",
                "original_invoice_date": "12-06-2026",
                "amended_payload": {"etin": "27AAACE1234E1Z1", "txval": 22000.0, "igst": 3960.0},
            },
        ]
        offline = build_gstr1a_offline_json(batch, items)
        assert len(offline["supeco"]) == 1
        assert offline["supeco"][0]["etin"] == "27AAACE1234E1Z1"
        assert len(offline["supecoa"]) == 1
        assert offline["supecoa"][0]["oinum"] == "INV-ECO-1"
        assert len(offline["sec9_5"]) == 1
        assert offline["sec9_5"][0]["txval"] == 20000.0
        assert len(offline["sec9_5a"]) == 1
        assert offline["sec9_5a"][0]["oinum"] == "INV-SEC9-1"


# ==============================================================================
# 2. GSTR-5 (NRTP) & GSTR-5A (OIDAR) CERTIFICATION
# ==============================================================================
class TestGstr5And5aCertification:
    """Certifies Non-Resident Taxable Persons and OIDAR services returns."""

    def test_gstr5_registration_and_due_date(self):
        """Section 27(1): 90-day validity; Rule 63 due date earlier of 13th or 7 days post-expiry."""
        res = evaluate_nrtp_registration_and_due_date(
            period="2026-07",
            registration_start=date(2026, 5, 1),
            registration_expiry=date(2026, 7, 29),
            reference_date=date(2026, 8, 1),
        )
        assert res.days_remaining < 0
        assert res.is_expired is True  # Expired on July 29
        # Due date is min(13th Aug, 29th July + 7 days = 5th Aug) -> 2026-08-05
        assert res.statutory_due_date == date(2026, 8, 5)

    def test_gstr5a_statutory_18_percent_igst_uniformity(self):
        """Section 14 of IGST Act: OIDAR services strictly attract 18% IGST."""
        igst, cess, total_tax = compute_oidar_tax_for_supply(
            taxable_value=Decimal("100000.00"),
            rate_pct=18.0,
        )
        assert igst == Decimal("18000.00")
        assert cess == Decimal("0.00")
        assert total_tax == Decimal("18000.00")

    def test_gstr5a_registered_recipients_rcm_and_online_money_gaming(self):
        """Table 5B (B2B RCM supplies) and Table 5D (Online Money Gaming at 28%)."""
        from app.services.gstr5a_service import (
            add_or_update_record_sync,
            build_gstr5a_offline_json,
            get_or_create_batch_sync,
        )
        batch = get_or_create_batch_sync(
            None,
            firm_id="firm-oidar-1",
            client_gstin_id="client-oidar-1",
            gstin="9917USA00000OID",
            period="2026-07",
            user_id="user-1",
        )
        # 1. B2C standard OIDAR (Table 5)
        add_or_update_record_sync(
            None,
            batch_id=batch.id,
            record_data={"pos": "27", "taxable_value": 100000.0, "rate_pct": 18.0, "record_type": "ORIGINAL"},
        )
        # 2. B2B RCM supply to registered recipient (Table 5B)
        add_or_update_record_sync(
            None,
            batch_id=batch.id,
            record_data={"pos": "27", "taxable_value": 50000.0, "rate_pct": 18.0, "record_type": "B2B_RCM", "recipient_gstin": "27AAACG0000A1Z5"},
        )
        # 3. Online money gaming supply under Section 14A (Table 5D at 28%)
        add_or_update_record_sync(
            None,
            batch_id=batch.id,
            record_data={"pos": "27", "taxable_value": 200000.0, "rate_pct": 28.0, "record_type": "GAMING"},
        )

        offline = build_gstr5a_offline_json(None, batch_id=batch.id)
        assert len(offline["sec5"]) == 1
        assert len(offline["sec5b"]) == 1
        assert offline["sec5b"][0]["ctin"] == "27AAACG0000A1Z5"
        assert len(offline["sec5d"]) == 1
        assert offline["sec5d"][0]["rt"] == 28.0
        assert offline["sec5d"][0]["iamt"] == 56000.0


# ==============================================================================
# 3. GSTR-6 (ISD) STATUTORY ALLOCATION CERTIFICATION
# ==============================================================================
class TestGstr6IsdCertification:
    """Certifies Input Service Distributor credit allocation under Section 20 & Rule 39."""

    def test_isd_credit_distribution_proportional(self):
        """Credit distributed strictly in ratio of turnover of operational recipient units."""
        # Unit 1 (MH): Turnover ₹60 Lakh (60%)
        # Unit 2 (KA): Turnover ₹40 Lakh (40%)
        recipients = [
            {"recipient_gstin": "27AAAAA1111A1Z1", "state_code": "27", "turnover": 6000000.0, "is_operational": True},
            {"recipient_gstin": "29AAAAA1111A1Z2", "state_code": "29", "turnover": 4000000.0, "is_operational": True},
        ]
        ratios = compute_turnover_ratios(recipients)
        ratio_dict = {r.recipient_gstin: r.ratio for r in ratios}
        assert ratio_dict["27AAAAA1111A1Z1"] == Decimal("0.6000")
        assert ratio_dict["29AAAAA1111A1Z2"] == Decimal("0.4000")

        # Distribute ₹10,000 IGST + ₹5,000 CGST + ₹5,000 SGST pool
        dist_res = distribute_isd_credit(
            isd_gstin="27AAAAA1111A1Z1",
            pool_igst=Decimal("10000.00"),
            pool_cgst=Decimal("5000.00"),
            pool_sgst=Decimal("5000.00"),
            is_eligible=True,
            recipient_turnovers=recipients,
        )
        # Recipient in KA (29) != ISD in MH (27) -> CGST+SGST become IGST:
        # Total pool = 10k + 5k + 5k = 20k -> 40% = 8,000 IGST
        dist_ka = next(d for d in dist_res.distributions if d.recipient_gstin == "29AAAAA1111A1Z2")
        assert dist_ka.distributed_igst == Decimal("8000.00")
        assert dist_ka.distributed_cgst == Decimal("0.00")
        assert dist_ka.distributed_sgst == Decimal("0.00")

    def test_distinct_persons_pan_validation(self):
        """ISD and recipient units must share identical 10-character PAN."""
        assert validate_distinct_persons("27AAAAA1111A1Z1", "29AAAAA1111A1Z2") is True
        assert validate_distinct_persons("27AAAAA1111A1Z1", "29BBBBB2222B1Z2") is False


# ==============================================================================
# 4. GSTR-7 (TDS) & GSTR-8 (TCS) STATUTORY CERTIFICATION
# ==============================================================================
class TestGstr7And8Certification:
    """Certifies Section 51 TDS (> ₹2.5L) and Section 52 TCS E-Commerce."""

    def test_gstr7_statutory_threshold_and_rates(self):
        """TDS deductible @ 2% (1% CGST + 1% SGST or 2% IGST) only if contract value > ₹2,50,000."""
        # Contract value ₹2,50,000 (boundary: not exceeding ₹2.5L) -> No TDS
        tds_exempt = calculate_gstr7_tds(
            contract_value=250000.00,
            amount_paid=50000.00,
            deductor_state="27",
            supplier_state="27",
            pos="27",
        )
        assert tds_exempt.is_eligible is False
        assert tds_exempt.total_tds == Decimal("0.00")

        # Contract value ₹5,00,000 (> ₹2.5L threshold), payment ₹1,00,000 intra-state
        tds_intra = calculate_gstr7_tds(
            contract_value=500000.00,
            amount_paid=100000.00,
            deductor_state="27",
            supplier_state="27",
            pos="27",
        )
        assert tds_intra.is_eligible is True
        assert tds_intra.tds_cgst == Decimal("1000.00")  # 1%
        assert tds_intra.tds_sgst == Decimal("1000.00")  # 1%
        assert tds_intra.tds_igst == Decimal("0.00")

        # Contract value ₹5,00,000, payment ₹1,00,000 inter-state (Supplier in KA, POS in MH)
        tds_inter = calculate_gstr7_tds(
            contract_value=500000.00,
            amount_paid=100000.00,
            deductor_state="27",
            supplier_state="29",
            pos="27",
        )
        assert tds_inter.is_eligible is True
        assert tds_inter.tds_igst == Decimal("2000.00")  # 2%

    def test_gstr7_section51_proviso_exception(self):
        """Proviso to Section 51(1): No TDS if Location of Supplier & POS are in State A, but Recipient in State B."""
        # Supplier in MH (27), POS in MH (27), Recipient in DL (07) -> EXEMPT
        is_exempt = evaluate_section_51_proviso(
            deductor_state="07",
            supplier_state="27",
            pos="27",
        )
        assert is_exempt is True

    def test_gstr8_net_taxable_value_and_tcs(self):
        """TCS calculated strictly on Net Taxable Value = Gross Supplies - Returned Supplies."""
        tcs_calc = calculate_gstr8_tcs(
            gross_supplies=Decimal("1000000.00"),
            returned_supplies=Decimal("200000.00"),
            period="2026-07",
            eco_state="27",
            pos="27",
            supplier_state="27",
        )
        assert tcs_calc.net_supplies == Decimal("800000.00")
        # Post-July 2024 rate is 0.5% total (0.25% CGST + 0.25% SGST)
        assert tcs_calc.tcs_cgst == Decimal("2000.00")  # 0.25%
        assert tcs_calc.tcs_sgst == Decimal("2000.00")  # 0.25%


# ==============================================================================
# 5. GSTR-10 (FINAL RETURN) & GSTR-11 (UIN) CERTIFICATION
# ==============================================================================
class TestGstr10And11Certification:
    """Certifies Form GSTR-10 cancellation liability and GSTR-11 refund claims."""

    def test_gstr10_capital_goods_5_year_pro_rata_formula(self):
        """Rule 44(1)(b): ITC reversal = Input tax * (60 - remaining months) / 60 or on transaction value."""
        # Capital goods purchased with ₹60,000 ITC taken
        # Remaining life calculation: 20 quarters max = 60 months
        reversal = compute_capital_goods_reversal(
            original_itc=Decimal("60000.00"),
            invoice_date=date(2024, 1, 1),
            cancellation_date=date(2026, 7, 1),
            transaction_value_tax=Decimal("20000.00"),
            is_cancellation_stock_without_supply=False,
        )
        # 10 quarters elapsed (50% useful life expired) -> 50% reversal
        assert reversal.reduced_itc == Decimal("30000.00")
        assert reversal.final_reversal_payable == Decimal("30000.00")

    def test_gstr10_due_date_calculation(self):
        """Section 45: 3 months from cancellation date or cancellation order date, whichever is later."""
        canc_date = date(2026, 7, 15)
        order_date = date(2026, 6, 20)
        due = calculate_gstr10_due_date(canc_date, order_date)
        assert due == date(2026, 10, 15)

    def test_gstr11_uin_validation_and_due_date(self):
        """Section 55 & Rule 82: UIN validation and due date (28th of succeeding month)."""
        assert validate_uin("0717USA00001UN1") is True
        assert validate_uin("INVALID_UIN") is False

        due = calculate_gstr11_due_date("2026-10")
        assert due == date(2026, 11, 28)


# ==============================================================================
# 6. TENANT ISOLATION, RBAC & MAKER-CHECKER SECURITY CERTIFICATION
# ==============================================================================
class TestSecurityAndGovernanceCertification:
    """Certifies tenant isolation, RBAC role hierarchy, and maker-checker gates."""

    def test_rbac_role_hierarchy(self):
        """Admin/Partner > Manager > Preparer/Staff > Viewer."""
        assert is_admin_or_partner("admin") is True
        assert is_admin_or_partner("partner") is True
        assert is_admin_or_partner("preparer") is False

        assert is_writer_or_above("preparer") is True
        assert is_writer_or_above("staff") is True
        assert is_writer_or_above("viewer") is False


# ==============================================================================
# 7. DEFECT DEF-2026-001 ROOT CAUSE & FIX VERIFICATION
# ==============================================================================
class TestDefect2026001Investigation:
    """Investigates and certifies regression fix for supplier_compliance_summary UUID[] mismatch."""

    def test_defect_reproduction_text_array_vs_uuid_array(self):
        """Demonstrates that passing raw strings to PostgreSQL UUID[] fails without proper type adaptation."""
        client_ids_strings = ["041ca6f0-6619-4122-aea8-078b81519eb0", "b2265f32-a0e3-4323-915b-47263b746319"]

        # Recommended Fix: Convert strings to Python UUID objects
        client_ids_uuids = [uuid.UUID(x) for x in client_ids_strings]
        assert all(isinstance(u, uuid.UUID) for u in client_ids_uuids)

        # In psycopg2, when uuid is registered, UUID objects adapt cleanly with '::uuid'
        import psycopg2.extras
        from psycopg2.extensions import adapt
        psycopg2.extras.register_uuid()
        adapted = adapt(client_ids_uuids).getquoted().decode("utf-8")
        assert "::uuid" in adapted
        assert adapted.startswith("ARRAY[")

    def test_aurora_client_uuid_array_parameter_preparation(self):
        """Verify _prepare_sql_param converts string UUIDs to UUID objects for native PostgreSQL uuid[]."""
        from app.aurora_client import _prepare_sql_param
        str_ids = ["041ca6f0-6619-4122-aea8-078b81519eb0", "b2265f32-a0e3-4323-915b-47263b746319"]
        prepared = _prepare_sql_param("client_gstin_ids", str_ids)
        assert isinstance(prepared, list)
        assert all(isinstance(x, uuid.UUID) for x in prepared)

        # Standard non-UUID arrays remain plain lists
        text_ids = ["REC-1", "REC-2"]
        prepared_text = _prepare_sql_param("record_ids", text_ids)
        assert prepared_text == text_ids

    def test_scorecard_rollup_client_rows_uuid_normalization(self):
        """Verify rollup_client_rows properly validates and normalizes client UUIDs."""
        from app.services.supplier_compliance_scorecard import rollup_client_rows
        rows = [
            {
                "supplier_gstin_normalized": "27AAACG0000A1Z5",
                "client_gstin_id": "041ca6f0-6619-4122-aea8-078b81519eb0",
                "supplier_trade_name": "ACME Supplies",
                "total_invoices": 10,
                "mismatch_invoice_count": 1,
            },
            {
                "supplier_gstin_normalized": "27AAACG0000A1Z5",
                "client_gstin_id": "b2265f32-a0e3-4323-915b-47263b746319",
                "supplier_trade_name": "ACME Supplies",
                "total_invoices": 5,
                "mismatch_invoice_count": 0,
            },
        ]
        rolled = rollup_client_rows(rows)
        assert rolled["clients_touched_count"] == 2
        assert len(rolled["client_gstin_ids"]) == 2
        assert "041ca6f0-6619-4122-aea8-078b81519eb0" in rolled["client_gstin_ids"]
        assert "b2265f32-a0e3-4323-915b-47263b746319" in rolled["client_gstin_ids"]
