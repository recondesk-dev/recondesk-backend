import pytest
import sys
import os

# Add tally_bridge directory to path for direct import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tally_bridge"))
from tally_bridge_agent import _normalize_date, parse_purchase_register_records, parse_sales_register_records


class TestNormalizeDate:
    """Tests for _normalize_date() Tally date string normalisation."""

    def test_yyyymmdd(self):
        assert _normalize_date("20260401") == "2026-04-01"

    def test_iso_format(self):
        assert _normalize_date("2026-04-01") == "2026-04-01"

    def test_iso_with_time(self):
        assert _normalize_date("2026-04-01T12:00:00") == "2026-04-01"

    def test_d_mon_yy(self):
        assert _normalize_date("1-Apr-26") == "2026-04-01"

    def test_dd_mon_yyyy(self):
        assert _normalize_date("01-Apr-2026") == "2026-04-01"

    def test_d_m_yy_slash(self):
        assert _normalize_date("1/4/26") == "2026-04-01"

    def test_dd_mm_yyyy_dot(self):
        assert _normalize_date("01.04.2026") == "2026-04-01"

    def test_d_m_yyyy_dash(self):
        assert _normalize_date("1-4-2026") == "2026-04-01"

    def test_space_separated_d_mon_yyyy(self):
        """Tally can output space-separated dates like '1 Apr 2026'."""
        assert _normalize_date("1 Apr 2026") == "2026-04-01"

    def test_space_separated_dd_mon_yy(self):
        """Tally can output space-separated dates like '01 Apr 26'."""
        assert _normalize_date("01 Apr 26") == "2026-04-01"

    def test_space_separated_numeric(self):
        """Space-separated numeric date like '1 4 2026'."""
        assert _normalize_date("1 4 2026") == "2026-04-01"

    def test_empty_returns_none(self):
        assert _normalize_date("") is None

    def test_none_returns_none(self):
        assert _normalize_date(None) is None

    def test_garbage_returns_none(self):
        assert _normalize_date("not-a-date") is None

    def test_partial_date_returns_none(self):
        assert _normalize_date("2026-04") is None


class TestCmpInfoPhantomRows:
    """Tests that CMPINFO metadata <VOUCHER> elements don't produce phantom rows."""

    CMPINFO_ONLY_XML = '''<ENVELOPE>
 <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
 <BODY>
  <DESC>
   <CMPINFO>
    <COMPANY>0</COMPANY>
    <VOUCHER>0</VOUCHER>
   </CMPINFO>
  </DESC>
  <DATA>
   <COLLECTION ISCMPDEPTYPE="Yes">   </COLLECTION>
  </DATA>
 </BODY>
</ENVELOPE>
'''

    CMPINFO_PLUS_REAL_VOUCHER_XML = '''<ENVELOPE>
 <HEADER><VERSION>1</VERSION><STATUS>1</STATUS></HEADER>
 <BODY>
  <DESC>
   <CMPINFO>
    <COMPANY>0</COMPANY>
    <VOUCHER>1</VOUCHER>
   </CMPINFO>
  </DESC>
  <DATA>
   <COLLECTION ISCMPDEPTYPE="Yes">
    <VOUCHER REMOTEID="abc-123" VCHKEY="key-1" VCHTYPE="Purchase" OBJVIEW="Accounting Voucher View">
     <DATE TYPE="Date">20260401</DATE>
     <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
     <PARTYLEDGERNAME TYPE="String">Test Supplier</PARTYLEDGERNAME>
     <VOUCHERNUMBER>INV-001</VOUCHERNUMBER>
     <ALLLEDGERENTRIES.LIST>
      <LEDGERNAME TYPE="String">Test Supplier</LEDGERNAME>
      <AMOUNT TYPE="Amount">-1000.00</AMOUNT>
     </ALLLEDGERENTRIES.LIST>
    </VOUCHER>
   </COLLECTION>
  </DATA>
 </BODY>
</ENVELOPE>
'''

    def test_cmpinfo_only_produces_zero_rows_purchase(self):
        rows = parse_purchase_register_records(self.CMPINFO_ONLY_XML)
        assert len(rows) == 0, f"Expected 0 rows, got {len(rows)}: {rows}"

    def test_cmpinfo_only_produces_zero_rows_sales(self):
        rows = parse_sales_register_records(self.CMPINFO_ONLY_XML)
        assert len(rows) == 0, f"Expected 0 rows, got {len(rows)}: {rows}"

    def test_cmpinfo_plus_real_voucher_produces_one_row_purchase(self):
        rows = parse_purchase_register_records(self.CMPINFO_PLUS_REAL_VOUCHER_XML)
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}: {rows}"
        assert rows[0]["Inv Date"] == "2026-04-01"
        assert rows[0]["Inv No."] == "INV-001"

    def test_cmpinfo_plus_real_voucher_produces_one_row_sales(self):
        rows = parse_sales_register_records(self.CMPINFO_PLUS_REAL_VOUCHER_XML)
        assert len(rows) == 1, f"Expected 1 row, got {len(rows)}: {rows}"
        assert rows[0]["Inv Date"] == "2026-04-01"
