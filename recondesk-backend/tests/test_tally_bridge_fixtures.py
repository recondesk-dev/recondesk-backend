"""Synthetic XML fixture tests for Tally Bridge — adversarial edge cases.

Each test builds raw XML, runs it through the agent parsers and the sync
service, and asserts the rebuilt logic handles it correctly.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from tally_bridge.tally_bridge_agent import (
    parse_outstanding_records,
    parse_payment_records,
    run_once,
)
from app.services.tally_bridge_sync import (
    _PARTY_AUTO_SETTLE_MIN,
    _UNIQUE_GAP_UNCLEAR_PARTY,
    apply_tally_bridge_sync,
    party_clears_autosettle_gate,
    score_bill_ref_against_invoice,
)


# ---------------------------------------------------------------------------
# XML fixtures
# ---------------------------------------------------------------------------

# Fixture 1: Two different suppliers with overlapping invoice numbers
OUTSTANDING_OVERLAPPING_SUPPLIERS = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <BILLOUTSTANDINGS.LIST>
    <LEDGERNAME>Sunrise Exports Pvt Ltd</LEDGERNAME>
    <BILLALLOCATIONS.LIST>
     <NAME>INV/2024/001</NAME>
     <AMOUNT>-50000.00</AMOUNT>
     <BILLDATE>20240115</BILLDATE>
    </BILLALLOCATIONS.LIST>
   </BILLOUTSTANDINGS.LIST>
   <BILLOUTSTANDINGS.LIST>
    <LEDGERNAME>Moonrise Industries LLP</LEDGERNAME>
    <BILLALLOCATIONS.LIST>
     <NAME>INV/2024/001</NAME>
     <AMOUNT>-75000.00</AMOUNT>
     <BILLDATE>20240220</BILLDATE>
    </BILLALLOCATIONS.LIST>
   </BILLOUTSTANDINGS.LIST>
  </DATA>
 </BODY>
</ENVELOPE>
"""

PAYMENTS_OVERLAPPING_SUPPLIERS = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <TALLYMESSAGE>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240601</DATE>
     <VOUCHERNUMBER>PMT-101</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Sunrise Exports Pvt Ltd</LEDGERNAME>
      <AMOUNT>-50000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>INV/2024/001</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-50000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240610</DATE>
     <VOUCHERNUMBER>PMT-102</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Moonrise Industries LLP</LEDGERNAME>
      <AMOUNT>-75000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>INV/2024/001</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-75000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </TALLYMESSAGE>
  </DATA>
 </BODY>
</ENVELOPE>
"""

# Fixture 2: Partial payment (7 500 of 10 000)
OUTSTANDING_PARTIAL = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <BILLOUTSTANDINGS.LIST>
    <LEDGERNAME>Delta Traders</LEDGERNAME>
    <BILLALLOCATIONS.LIST>
     <NAME>SALE/26/078</NAME>
     <AMOUNT>-2500.00</AMOUNT>
     <BILLDATE>20240301</BILLDATE>
    </BILLALLOCATIONS.LIST>
   </BILLOUTSTANDINGS.LIST>
  </DATA>
 </BODY>
</ENVELOPE>
"""

PAYMENTS_PARTIAL = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <TALLYMESSAGE>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240501</DATE>
     <VOUCHERNUMBER>PMT-200</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Delta Traders</LEDGERNAME>
      <AMOUNT>-7500.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>SALE/26/078</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-7500.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </TALLYMESSAGE>
  </DATA>
 </BODY>
</ENVELOPE>
"""

# Fixture 3: Payment voucher with no party name at all
PAYMENTS_NO_PARTY = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <TALLYMESSAGE>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240701</DATE>
     <VOUCHERNUMBER>PMT-300</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <AMOUNT>-20000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>INV-2024-555</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-20000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </TALLYMESSAGE>
  </DATA>
 </BODY>
</ENVELOPE>
"""

# Fixture 4: Bill refs with unusual formatting (leading zeros, slashes, dashes)
PAYMENTS_UNUSUAL_BILL_REFS = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <TALLYMESSAGE>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240801</DATE>
     <VOUCHERNUMBER>PMT-400</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Omega Solutions Pvt Ltd</LEDGERNAME>
      <AMOUNT>-15000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>DS/0026/00078</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-15000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240815</DATE>
     <VOUCHERNUMBER>PMT-401</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Omega Solutions Pvt Ltd</LEDGERNAME>
      <AMOUNT>-8000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>0INV-24-25-5024</NAME>
       <BILLTYPE>Agst Ref</BILLTYPE>
       <AMOUNT>-8000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </TALLYMESSAGE>
  </DATA>
 </BODY>
</ENVELOPE>
"""

# Fixture 5: Outstandings with rows that have NO payment voucher at all
OUTSTANDING_UNPAID_ONLY = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <BILLOUTSTANDINGS.LIST>
    <LEDGERNAME>Alpha Corp</LEDGERNAME>
    <BILLALLOCATIONS.LIST>
     <NAME>ALPHA/INV/001</NAME>
     <AMOUNT>-100000.00</AMOUNT>
     <BILLDATE>20231201</BILLDATE>
    </BILLALLOCATIONS.LIST>
   </BILLOUTSTANDINGS.LIST>
   <BILLOUTSTANDINGS.LIST>
    <LEDGERNAME>Beta Enterprises</LEDGERNAME>
    <BILLALLOCATIONS.LIST>
     <NAME>BETA-2024-999</NAME>
     <AMOUNT>-35000.00</AMOUNT>
     <BILLDATE>20240101</BILLDATE>
    </BILLALLOCATIONS.LIST>
   </BILLOUTSTANDINGS.LIST>
  </DATA>
 </BODY>
</ENVELOPE>
"""

PAYMENTS_EMPTY = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
  </DATA>
 </BODY>
</ENVELOPE>
"""

# Fixture 6: Empty/near-empty exports
OUTSTANDING_EMPTY = """\
<?xml version="1.0"?>
<ENVELOPE><BODY/></ENVELOPE>
"""

# Non-Agst-Ref allocations that should be ignored
PAYMENTS_ON_ACCOUNT_ONLY = """\
<?xml version="1.0"?>
<ENVELOPE>
 <BODY>
  <DATA>
   <TALLYMESSAGE>
    <VOUCHER>
     <VOUCHERTYPENAME>Payment</VOUCHERTYPENAME>
     <DATE>20240601</DATE>
     <VOUCHERNUMBER>PMT-999</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME>Alpha Corp</LEDGERNAME>
      <AMOUNT>-50000.00</AMOUNT>
      <BILLALLOCATIONS.LIST>
       <NAME>On Account</NAME>
       <BILLTYPE>On Account</BILLTYPE>
       <AMOUNT>-50000.00</AMOUNT>
      </BILLALLOCATIONS.LIST>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </TALLYMESSAGE>
  </DATA>
 </BODY>
</ENVELOPE>
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _open_row(
    invoice_number: str = "INV/2024/001",
    supplier_name: str = "Acme Traders Pvt Ltd",
    invoice_amount: float = 10000.0,
    **overrides: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "run-1",
        "record_id": f"r37:pr-{invoice_number.replace('/', '-')}",
        "pr_id": f"pr-{invoice_number.replace('/', '-')}",
        "invoice_number": invoice_number,
        "invoice_date": "2024-01-15",
        "supplier_gstin": "27AABCU9603R1ZM",
        "supplier_name": supplier_name,
        "invoice_amount": invoice_amount,
        "client_gstin_id": "client-1",
    }
    row.update(overrides)
    return row


def _run_sync(
    outstanding: list[dict[str, Any]],
    payments: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], MagicMock]:
    upsert = MagicMock()
    with (
        patch(
            "app.services.tally_bridge_sync.load_open_rule37_for_account",
            return_value=list(open_rows),
        ),
        patch(
            "app.routers.reconciliation_api._upsert_rule37_action",
            upsert,
        ),
        patch(
            "app.routers.reconciliation_api._rule37_payment_coverage",
            side_effect=lambda paid, inv: "full" if paid + 0.005 >= inv else "partial",
        ),
    ):
        result = apply_tally_bridge_sync(
            MagicMock(),
            account_id="acct-1",
            outstanding=outstanding,
            payments=payments,
            company_name="Test Co",
            key_id="key-1",
        )
    return result, upsert


# ---------------------------------------------------------------------------
# 1. Two suppliers with overlapping invoice numbers
# ---------------------------------------------------------------------------

class TestOverlappingSupplierInvoices:
    """INV/2024/001 appears for both Sunrise Exports and Moonrise Industries.

    The party gate must route each payment to the correct open invoice
    (by party match) and block the wrong supplier from settling.
    """

    def test_parse_both_xml(self):
        outstanding = parse_outstanding_records(OUTSTANDING_OVERLAPPING_SUPPLIERS)
        payments = parse_payment_records(PAYMENTS_OVERLAPPING_SUPPLIERS)
        assert len(outstanding) == 2
        assert len(payments) == 2
        parties = {r["party"] for r in payments}
        assert "Sunrise Exports Pvt Ltd" in parties
        assert "Moonrise Industries LLP" in parties

    def test_correct_supplier_settles_wrong_supplier_blocked(self):
        open_rows = [
            _open_row(
                invoice_number="INV/2024/001",
                supplier_name="Sunrise Exports Pvt Ltd",
                invoice_amount=50000.0,
                record_id="r37:pr-sunrise",
            ),
            _open_row(
                invoice_number="INV/2024/001",
                supplier_name="Moonrise Industries LLP",
                invoice_amount=75000.0,
                record_id="r37:pr-moonrise",
                supplier_gstin="27BBCDE1234F1Z5",
            ),
        ]
        payments = parse_payment_records(PAYMENTS_OVERLAPPING_SUPPLIERS)
        result, upsert = _run_sync([], payments, open_rows)

        assert result["settled_count"] == 2
        assert result["needs_manual_confirmation_count"] == 0

        calls = upsert.call_args_list
        settled_records = {c.kwargs["record_id"] for c in calls}
        assert "r37:pr-sunrise" in settled_records
        assert "r37:pr-moonrise" in settled_records

        for call in calls:
            kwargs = call.kwargs
            if kwargs["record_id"] == "r37:pr-sunrise":
                assert kwargs["amount_paid"] == 50000.0
            elif kwargs["record_id"] == "r37:pr-moonrise":
                assert kwargs["amount_paid"] == 75000.0

    def test_wrong_party_goes_to_manual_confirmation(self):
        """Only Sunrise open but Moonrise's payment tries to settle it."""
        open_rows = [
            _open_row(
                invoice_number="INV/2024/001",
                supplier_name="Sunrise Exports Pvt Ltd",
                invoice_amount=50000.0,
            ),
        ]
        moonrise_payment = [
            {
                "party": "Moonrise Industries LLP",
                "bill_ref": "INV/2024/001",
                "amount": 75000.0,
                "payment_date": "2024-06-10",
            }
        ]
        result, upsert = _run_sync([], moonrise_payment, open_rows)
        upsert.assert_not_called()
        assert result["settled_count"] == 0
        assert result["needs_manual_confirmation_count"] == 1
        assert (
            result["needs_manual_confirmation"][0]["reason"]
            == "party_confidence_below_gate"
        )


# ---------------------------------------------------------------------------
# 2. Partial payment
# ---------------------------------------------------------------------------

class TestPartialPayment:
    """Payment is 7500 against a 10000 invoice; outstanding shows 2500 pending."""

    def test_parse_partial_fixtures(self):
        outstanding = parse_outstanding_records(OUTSTANDING_PARTIAL)
        payments = parse_payment_records(PAYMENTS_PARTIAL)
        assert len(outstanding) == 1
        assert outstanding[0]["amount"] == 2500.0
        assert len(payments) == 1
        assert payments[0]["amount"] == 7500.0

    def test_partial_coverage_computed_correctly(self):
        open_rows = [
            _open_row(
                invoice_number="SALE/26/078",
                supplier_name="Delta Traders",
                invoice_amount=10000.0,
            ),
        ]
        outstanding = parse_outstanding_records(OUTSTANDING_PARTIAL)
        payments = parse_payment_records(PAYMENTS_PARTIAL)
        result, upsert = _run_sync(outstanding, payments, open_rows)

        assert result["settled_count"] == 1
        upsert.assert_called_once()
        kwargs = upsert.call_args.kwargs
        assert kwargs["amount_paid"] == 7500.0
        assert kwargs["remaining_unpaid_amount"] == 2500.0
        assert kwargs["payment_coverage"] == "partial"
        assert kwargs["tds_confirmed"] is False
        assert kwargs["tds_deducted"] == 0.0


# ---------------------------------------------------------------------------
# 3. Payment voucher with no party name
# ---------------------------------------------------------------------------

class TestNoPartyName:
    """LEDGERNAME is missing — party gate must block auto-settle."""

    def test_parse_extracts_empty_party(self):
        payments = parse_payment_records(PAYMENTS_NO_PARTY)
        assert len(payments) == 1
        assert payments[0]["party"] == ""
        assert payments[0]["amount"] == 20000.0

    def test_no_party_routes_to_manual_confirmation(self):
        open_rows = [
            _open_row(
                invoice_number="INV-2024-555",
                supplier_name="Some Known Supplier",
                invoice_amount=20000.0,
            ),
        ]
        payments = parse_payment_records(PAYMENTS_NO_PARTY)
        result, upsert = _run_sync([], payments, open_rows)
        upsert.assert_not_called()
        assert result["settled_count"] == 0
        assert result["needs_manual_confirmation_count"] == 1
        mc = result["needs_manual_confirmation"][0]
        assert mc["reason"] == "party_confidence_below_gate"
        assert mc["party_sim"] == 0.0


# ---------------------------------------------------------------------------
# 4. Unusual bill ref formatting (leading zeros, slashes, dashes)
# ---------------------------------------------------------------------------

class TestUnusualBillRefFormat:
    """Bill refs DS/0026/00078 and 0INV-24-25-5024 should fuzzy-match."""

    def test_parse_unusual_refs(self):
        payments = parse_payment_records(PAYMENTS_UNUSUAL_BILL_REFS)
        assert len(payments) == 2
        refs = {r["bill_ref"] for r in payments}
        assert "DS/0026/00078" in refs
        assert "0INV-24-25-5024" in refs

    def test_format_variant_matching(self):
        score1 = score_bill_ref_against_invoice("DS/0026/00078", "DS/26/78")
        assert score1 >= 0.85, f"DS/0026/00078 vs DS/26/78 scored {score1}"

        score2 = score_bill_ref_against_invoice("0INV-24-25-5024", "INV/24-25/5024")
        assert score2 >= 0.85, f"0INV-24-25-5024 vs INV/24-25/5024 scored {score2}"

    def test_unusual_refs_settle_with_strong_party(self):
        open_rows = [
            _open_row(
                invoice_number="DS/26/78",
                supplier_name="Omega Solutions Pvt Ltd",
                invoice_amount=15000.0,
                record_id="r37:pr-ds",
            ),
            _open_row(
                invoice_number="INV/24-25/5024",
                supplier_name="Omega Solutions Pvt Ltd",
                invoice_amount=8000.0,
                record_id="r37:pr-inv5024",
                supplier_gstin="27ZZZZZ9999Z1Z1",
            ),
        ]
        payments = parse_payment_records(PAYMENTS_UNUSUAL_BILL_REFS)
        result, upsert = _run_sync([], payments, open_rows)

        assert result["settled_count"] == 2
        settled_ids = {s["record_id"] for s in result["settled"]}
        assert "r37:pr-ds" in settled_ids
        assert "r37:pr-inv5024" in settled_ids


# ---------------------------------------------------------------------------
# 5. Outstandings with NO payment voucher — must stay unpaid
# ---------------------------------------------------------------------------

class TestOutstandingsOnlyNeverSettle:
    """Two outstanding invoices, zero payments. Nothing should settle."""

    def test_parse_outstanding_only(self):
        outstanding = parse_outstanding_records(OUTSTANDING_UNPAID_ONLY)
        payments = parse_payment_records(PAYMENTS_EMPTY)
        assert len(outstanding) == 2
        assert len(payments) == 0

    def test_outstanding_only_never_calls_upsert(self):
        open_rows = [
            _open_row(
                invoice_number="ALPHA/INV/001",
                supplier_name="Alpha Corp",
                invoice_amount=100000.0,
                record_id="r37:pr-alpha",
            ),
            _open_row(
                invoice_number="BETA-2024-999",
                supplier_name="Beta Enterprises",
                invoice_amount=35000.0,
                record_id="r37:pr-beta",
            ),
        ]
        outstanding = parse_outstanding_records(OUTSTANDING_UNPAID_ONLY)
        payments = parse_payment_records(PAYMENTS_EMPTY)
        result, upsert = _run_sync(outstanding, payments, open_rows)

        upsert.assert_not_called()
        assert result["settled_count"] == 0
        assert result["still_outstanding_count"] == 2
        pending_amounts = {r["bill_ref"]: r["pending_due"] for r in result["still_outstanding"]}
        assert pending_amounts.get("ALPHA/INV/001") == 100000.0
        assert pending_amounts.get("BETA-2024-999") == 35000.0

    def test_on_account_payment_does_not_settle(self):
        """On Account bill type must be ignored — not settle evidence."""
        open_rows = [
            _open_row(
                invoice_number="ALPHA/INV/001",
                supplier_name="Alpha Corp",
                invoice_amount=100000.0,
            ),
        ]
        payments = parse_payment_records(PAYMENTS_ON_ACCOUNT_ONLY)
        assert len(payments) == 0, "On Account should not parse as Agst Ref"
        result, upsert = _run_sync([], payments, open_rows)
        upsert.assert_not_called()
        assert result["settled_count"] == 0


# ---------------------------------------------------------------------------
# 6. Empty / near-empty exports (--test warning coverage)
# ---------------------------------------------------------------------------

class TestEmptyExports:
    """Zero-row exports must parse cleanly and trigger warnings in --test."""

    def test_empty_outstanding_parses_to_zero(self):
        assert parse_outstanding_records(OUTSTANDING_EMPTY) == []

    def test_empty_payments_parses_to_zero(self):
        assert parse_payment_records(PAYMENTS_EMPTY) == []

    def test_empty_both_sides_no_settle(self):
        open_rows = [_open_row()]
        result, upsert = _run_sync([], [], open_rows)
        upsert.assert_not_called()
        assert result["settled_count"] == 0
        assert result["still_outstanding_count"] == 0
        assert result["needs_manual_confirmation_count"] == 0

    def test_agent_test_mode_warns_on_empty(self):
        """--test mode must exit 0 but log warnings for zero-row exports."""
        import logging

        cfg = {
            "api_key": "rdb_x",
            "recondesk_endpoint": "https://example.com/api/tally-sync/outstanding",
            "tally_host": "localhost",
            "tally_port": 9000,
            "sync_interval_minutes": 60,
            "lookback_days": 200,
            "company_name": "Empty Co",
        }
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            logger = logging.getLogger("tally_bridge_fixture_test")
            logger.handlers.clear()
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)

            warnings_seen: list[str] = []
            orig_warning = logger.warning

            def capture_warning(msg, *args):
                warnings_seen.append(msg % args if args else msg)
                orig_warning(msg, *args)

            logger.warning = capture_warning

            with patch(
                "tally_bridge.tally_bridge_agent.fetch_tally_xml",
                side_effect=[OUTSTANDING_EMPTY, PAYMENTS_EMPTY],
            ):
                code = run_once(cfg, logger, test_mode=True, out_dir=out)

            assert code == 0
            assert any("parsed 0 rows" in w for w in warnings_seen), (
                f"Expected zero-row warning in: {warnings_seen}"
            )
            jsons = list(out.glob("tally_bridge_*.json"))
            assert len(jsons) == 1
            payload = json.loads(jsons[0].read_text())
            assert payload["outstanding"] == []
            assert payload["payments"] == []

    def test_one_side_empty_other_populated(self):
        """Outstanding rows but no payments — nothing settles, outstanding reported."""
        open_rows = [
            _open_row(
                invoice_number="ALPHA/INV/001",
                supplier_name="Alpha Corp",
                invoice_amount=100000.0,
            ),
        ]
        outstanding = parse_outstanding_records(OUTSTANDING_UNPAID_ONLY)
        result, upsert = _run_sync(outstanding, [], open_rows)
        upsert.assert_not_called()
        assert result["settled_count"] == 0
        assert result["still_outstanding_count"] >= 1
