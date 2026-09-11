"""Tests for GSTR-2A vs GSTR-2B Delta Reconciliation module.

Covers:
1. test_parser_parses_b2b_record
2. test_parser_cdna_negative_values
3. test_delta_in_both
4. test_delta_late_filed
5. test_delta_filed_not_reflected
6. test_delta_in_2b_not_2a
7. test_delta_value_mismatch
8. test_summary_counts
"""

import pytest
from app.parsers.gstr2a_parser import parse_gstr2a
from app.services.gstr2a_vs_2b import (
    FILED_NOT_REFLECTED,
    IN_2B_NOT_2A,
    IN_BOTH,
    LATE_FILED,
    VALUE_MISMATCH,
    reconcile_2a_vs_2b,
)


def test_parser_parses_b2b_record():
    """Test standard B2B invoice parsed correctly from raw GSTR-2A JSON."""
    raw_2a = {
        "b2b": [
            {
                "ctin": "27AABCU9603R1ZM",
                "cfs": "Y",
                "cfs3b": "Y",
                "inv": [
                    {
                        "inum": "INV-1001",
                        "idt": "10-06-2026",
                        "val": 11800.0,
                        "pos": "27",
                        "rchrg": "N",
                        "inv_typ": "R",
                        "fldtr1": "10-06-2026",
                        "itms": [
                            {
                                "num": 1,
                                "itm_det": {
                                    "rt": 18.0,
                                    "txval": 10000.0,
                                    "iamt": 0.0,
                                    "camt": 900.0,
                                    "samt": 900.0,
                                    "csamt": 0.0,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }

    records = parse_gstr2a(raw_2a)
    assert len(records) == 1
    rec = records[0]

    assert rec["supplier_gstin"] == "27AABCU9603R1ZM"
    assert rec["invoice_number"] == "INV-1001"
    assert rec["invoice_date"] == "2026-06-10"
    assert rec["filing_date"] == "2026-06-10"
    assert rec["taxable_amount_paise"] == 1000000  # ₹10,000.00
    assert rec["cgst_paise"] == 90000              # ₹900.00
    assert rec["sgst_paise"] == 90000              # ₹900.00
    assert rec["igst_paise"] == 0
    assert rec["cess_paise"] == 0
    assert rec["total_tax_paise"] == 180000         # ₹1,800.00
    assert rec["doc_type"] == "INVOICE"


def test_parser_cdna_negative_values():
    """Test credit note values are inverted to negative amounts."""
    raw_2a = {
        "cdna": [
            {
                "ctin": "27AABCU9603R1ZM",
                "cfs": "Y",
                "nt": [
                    {
                        "nt_num": "CRN-501",
                        "nt_dt": "15-06-2026",
                        "ntty": "C",
                        "val": 5900.0,
                        "fldtr1": "16-06-2026",
                        "itms": [
                            {
                                "num": 1,
                                "itm_det": {
                                    "rt": 18.0,
                                    "txval": 5000.0,
                                    "iamt": 900.0,
                                    "camt": 0.0,
                                    "samt": 0.0,
                                    "csamt": 0.0,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }

    records = parse_gstr2a(raw_2a)
    assert len(records) == 1
    rec = records[0]

    assert rec["supplier_gstin"] == "27AABCU9603R1ZM"
    assert rec["invoice_number"] == "CRN-501"
    assert rec["doc_type"] == "CREDIT_NOTE"
    assert rec["taxable_amount_paise"] == -500000   # Negative ₹5,000.00
    assert rec["igst_paise"] == -90000              # Negative ₹900.00
    assert rec["total_tax_paise"] == -90000         # Negative ₹900.00
    assert rec["filing_date"] == "2026-06-16"


def test_delta_in_both():
    """Test invoice filed before cutoff present in both 2A and 2B -> IN_BOTH."""
    records_2a = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-001",
            "invoice_date": "2026-06-05",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        }
    ]
    records_2b = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-001",
            "invoice_date": "2026-06-05",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        }
    ]

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 1
    res = results[0]
    assert res["category"] == IN_BOTH
    assert res["supplier_gstin"] == "27AABCU9603R1ZM"
    assert res["invoice_number"] == "INV-001"
    assert "eligible this month" in res["decision_what"].lower()
    assert summary["in_both_count"] == 1
    assert summary["deferred_itc_paise"] == 0
    assert summary["unresolved_itc_paise"] == 0


def test_delta_late_filed():
    """Test invoice filed on 16th (after 13th cutoff) present in 2A only -> LATE_FILED.

    Must calculate days_late=3 and next_month_2b='2026-07'.
    """
    records_2a = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-002",
            "invoice_date": "2026-06-08",
            "filing_date": "2026-06-16",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        }
    ]
    records_2b = []

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 1
    res = results[0]
    assert res["category"] == LATE_FILED
    assert res["days_late"] == 3
    assert res["next_month_2b"] == "2026-07"
    assert res["itc_at_risk_paise"] == 180000
    assert "deferred to 2026-07" in res["decision_what"].lower()
    assert "3 days after cutoff" in res["decision_what"].lower()
    assert "invoices filed after the 13th are excluded" in res["decision_why"].lower()

    assert summary["late_filed_count"] == 1
    assert summary["deferred_itc_paise"] == 180000
    assert summary["deferred_itc_rupees"] == 1800.0


def test_delta_filed_not_reflected():
    """Test invoice filed on 10th (before cutoff) present in 2A only -> FILED_NOT_REFLECTED."""
    records_2a = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-003",
            "invoice_date": "2026-06-05",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 2000000,
            "total_tax_paise": 360000,
        }
    ]
    records_2b = []

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 1
    res = results[0]
    assert res["category"] == FILED_NOT_REFLECTED
    assert res["days_late"] == 0
    assert res["itc_at_risk_paise"] == 360000
    assert "portal" in res["decision_why"].lower() or "delay" in res["decision_why"].lower()

    assert summary["filed_not_reflected_count"] == 1
    assert summary["unresolved_itc_paise"] == 360000
    assert summary["unresolved_itc_rupees"] == 3600.0


def test_delta_in_2b_not_2a():
    """Test invoice present in 2B but absent from 2A -> IN_2B_NOT_2A."""
    records_2a = []
    records_2b = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-004",
            "invoice_date": "2026-06-05",
            "taxable_amount_paise": 1500000,
            "total_tax_paise": 270000,
        }
    ]

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 1
    res = results[0]
    assert res["category"] == IN_2B_NOT_2A
    assert res["taxable_value_2b"] == 15000.0
    assert res["taxable_value_2a"] is None
    assert "amend" in res["decision_why"].lower() or "cancel" in res["decision_why"].lower()

    assert summary["in_2b_not_2a_count"] == 1
    assert summary["unresolved_itc_paise"] == 270000
    assert summary["unresolved_itc_rupees"] == 2700.0


def test_delta_value_mismatch():
    """Test invoice present in both but taxable amount differs > 1% -> VALUE_MISMATCH."""
    records_2a = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-005",
            "invoice_date": "2026-06-05",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 1000000,  # ₹10,000.00
            "total_tax_paise": 180000,        # ₹1,800.00
        }
    ]
    records_2b = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-005",
            "invoice_date": "2026-06-05",
            "taxable_amount_paise": 1500000,  # ₹15,000.00 (50% difference > 1%)
            "total_tax_paise": 270000,        # ₹2,700.00
        }
    ]

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 1
    res = results[0]
    assert res["category"] == VALUE_MISMATCH
    assert res["taxable_value_2a"] == 10000.0
    assert res["taxable_value_2b"] == 15000.0
    assert res["tax_value_2a"] == 1800.0
    assert res["tax_value_2b"] == 2700.0
    assert res["itc_at_risk_paise"] == 90000  # |2700 - 1800| = ₹900 (90000 paise)
    assert "taxable value mismatch" in res["decision_what"].lower()

    assert summary["value_mismatch_count"] == 1
    assert summary["unresolved_itc_paise"] == 90000
    assert summary["unresolved_itc_rupees"] == 900.0


def test_summary_counts():
    """Verify total counts, deferred ITC, and unresolved ITC in summary output."""
    records_2a = [
        # 1. IN_BOTH
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-101",
            "invoice_date": "2026-06-02",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        },
        # 2. LATE_FILED (tax: ₹2,000 / 200000 paise)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-102",
            "invoice_date": "2026-06-05",
            "filing_date": "2026-06-18",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 200000,
        },
        # 3. FILED_NOT_REFLECTED (tax: ₹3,000 / 300000 paise)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-103",
            "invoice_date": "2026-06-06",
            "filing_date": "2026-06-11",
            "taxable_amount_paise": 1500000,
            "total_tax_paise": 300000,
        },
        # 4. VALUE_MISMATCH (2A tax: ₹1,800, 2B tax: ₹2,800 -> diff ₹1,000 / 100000 paise)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-104",
            "invoice_date": "2026-06-08",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        },
    ]

    records_2b = [
        # For INV-101
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-101",
            "invoice_date": "2026-06-02",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        },
        # For INV-104 (Value mismatch)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-104",
            "invoice_date": "2026-06-08",
            "taxable_amount_paise": 1500000,
            "total_tax_paise": 280000,
        },
        # 5. IN_2B_NOT_2A (tax: ₹1,500 / 150000 paise)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-105",
            "invoice_date": "2026-06-10",
            "taxable_amount_paise": 800000,
            "total_tax_paise": 150000,
        },
    ]

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    assert len(results) == 5
    assert summary["total_records"] == 5
    assert summary["in_both_count"] == 1
    assert summary["late_filed_count"] == 1
    assert summary["filed_not_reflected_count"] == 1
    assert summary["in_2b_not_2a_count"] == 1
    assert summary["value_mismatch_count"] == 1

    # Deferred ITC: only LATE_FILED (₹2,000)
    assert summary["deferred_itc_paise"] == 200000
    assert summary["deferred_itc_rupees"] == 2000.0

    # Unresolved ITC: FILED_NOT_REFLECTED (300000) + IN_2B_NOT_2A (150000) + VALUE_MISMATCH (100000) = 550000
    assert summary["unresolved_itc_paise"] == 550000
    assert summary["unresolved_itc_rupees"] == 5500.0


def test_router_run_delta_endpoint():
    """Verify POST /api/gstr2a-delta/run endpoint through FastAPI TestClient."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test", "role": "admin"}
    test_client = TestClient(app)

    with patch("app.routers.gstr2a_delta._assert_client_access"), \
         patch("app.routers.gstr2a_delta.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        payload = {
            "client_gstin_id": "00000000-0000-0000-0000-000000000001",
            "period": "2026-06",
            "gstr2a_records": [
                {
                    "supplier_gstin": "27AABCU9603R1ZM",
                    "invoice_number": "INV-001",
                    "invoice_date": "2026-06-05",
                    "filing_date": "2026-06-10",
                    "taxable_amount_paise": 1000000,
                    "total_tax_paise": 180000,
                }
            ],
            "gstr2b_records": [
                {
                    "supplier_gstin": "27AABCU9603R1ZM",
                    "invoice_number": "INV-001",
                    "invoice_date": "2026-06-05",
                    "taxable_amount_paise": 1000000,
                    "total_tax_paise": 180000,
                }
            ],
        }

        resp = test_client.post("/api/gstr2a-delta/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["client_gstin_id"] == "00000000-0000-0000-0000-000000000001"
        assert data["summary"]["in_both_count"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["category"] == "IN_BOTH"


def test_router_get_endpoints():
    """Verify GET /api/gstr2a-delta/{client_id}/{period} and summary endpoint."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test", "role": "admin"}
    test_client = TestClient(app)

    with patch("app.routers.gstr2a_delta._assert_client_access"), \
         patch("app.routers.gstr2a_delta.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_sb.table.return_value.select.return_value.eq.return_value.in_.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "id": "res-1",
                    "client_gstin_id": "00000000-0000-0000-0000-000000000001",
                    "period": "2026-06",
                    "cutoff_date": "2026-06-13",
                    "reconciled_at": "2026-06-14T10:00:00Z",
                    "summary": {"in_both_count": 1, "total_records": 1},
                    "results": [
                        {
                            "category": "IN_BOTH",
                            "supplier_gstin": "27AABCU9603R1ZM",
                            "invoice_number": "INV-001",
                        }
                    ],
                }
            ]
        )

        resp = test_client.get("/api/gstr2a-delta/00000000-0000-0000-0000-000000000001/2026-06")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_records"] == 1
        assert len(data["results"]) == 1

        resp_sum = test_client.get("/api/gstr2a-delta/00000000-0000-0000-0000-000000000001/2026-06/summary")
        assert resp_sum.status_code == 200
        data_sum = resp_sum.json()
        assert data_sum["summary"]["in_both_count"] == 1


def test_router_auto_fetch_calls_ensure_fresh_gstn_token():
    """Verify auto-fetch invokes ensure_fresh_gstn_token(sb, client_row) with 2 arguments."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test", "role": "admin"}
    test_client = TestClient(app)

    with patch("app.routers.gstr2a_delta._assert_client_access"), \
         patch("app.routers.gstr2a_delta.get_supabase") as mock_get_sb, \
         patch("app.routers.gstr2a_delta.load_client_gstin") as mock_load_client, \
         patch("app.routers.gstr2a_delta.ensure_fresh_gstn_token") as mock_ensure_token, \
         patch("app.routers.gstr2a_delta.gstr2a_fetch.fetch") as mock_fetch:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_client_row = {"id": "cid", "gstin": "27AABCU9603R1ZM", "gstn_access_token": "tok"}
        mock_load_client.return_value = mock_client_row
        mock_ensure_token.return_value = "fresh_tok"
        mock_fetch.return_value = {"b2b": []}
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        payload = {
            "client_gstin_id": "00000000-0000-0000-0000-000000000001",
            "period": "2026-06",
        }

        resp = test_client.post("/api/gstr2a-delta/run", json=payload)
        assert resp.status_code == 200
        mock_ensure_token.assert_called_once_with(mock_sb, mock_client_row)


def test_router_with_gstr2b_raw():
    """Verify router parses both gstr2a_raw and gstr2b_raw when provided."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test", "role": "admin"}
    test_client = TestClient(app)

    with patch("app.routers.gstr2a_delta._assert_client_access"), \
         patch("app.routers.gstr2a_delta.get_supabase") as mock_get_sb:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_sb.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        payload = {
            "client_gstin_id": "00000000-0000-0000-0000-000000000001",
            "period": "2026-06",
            "gstr2a_raw": {
                "b2b": [
                    {
                        "ctin": "27AABCU9603R1ZM",
                        "inv": [
                            {
                                "inum": "INV-001",
                                "idt": "10-06-2026",
                                "val": 11800.0,
                                "itms": [{"num": 1, "itm_det": {"txval": 10000.0, "iamt": 1800.0}}],
                            }
                        ],
                    }
                ]
            },
            "gstr2b_raw": {
                "data": {
                    "gstin": "27AABCU9603R1ZM",
                    "rtnprd": "062026",
                    "b2b": [
                        {
                            "ctin": "27AABCU9603R1ZM",
                            "inv": [
                                {
                                    "inum": "INV-001",
                                    "dt": "10-06-2026",
                                    "val": 11800.0,
                                    "pos": "27",
                                    "rev": "N",
                                    "itcavl": "Y",
                                    "itms": [
                                        {
                                            "num": 1,
                                            "itm_det": {
                                                "rt": 18.0,
                                                "txval": 10000.0,
                                                "igst": 1800.0,
                                                "cgst": 0.0,
                                                "sgst": 0.0,
                                                "cess": 0.0,
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            },
        }

        resp = test_client.post("/api/gstr2a-delta/run", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"]["in_both"] == 1


def test_router_sources_endpoint():
    """Verify GET /api/gstr2a-delta/{client_id}/{period}/sources reports 2B DB availability."""
    from unittest.mock import MagicMock, patch
    from fastapi.testclient import TestClient
    from app.main import app
    from app.auth import get_current_active_user

    app.dependency_overrides[get_current_active_user] = lambda: {"id": "user-test", "role": "admin"}
    test_client = TestClient(app)

    with patch("app.routers.gstr2a_delta._assert_client_access"), \
         patch("app.routers.gstr2a_delta.get_supabase") as mock_get_sb, \
         patch("app.routers.gstr2a_delta._resolve_latest_2b_run") as mock_resolve, \
         patch("app.routers.gstr2a_delta._fetch_2b_records_from_db") as mock_fetch_2b:
        mock_sb = MagicMock()
        mock_get_sb.return_value = mock_sb
        mock_resolve.return_value = {"has_2b_in_db": True, "records_2b_count": 1}
        mock_fetch_2b.return_value = [{"supplier_gstin": "27AABCU9603R1ZM", "invoice_number": "INV-1"}]

        resp = test_client.get("/api/gstr2a-delta/00000000-0000-0000-0000-000000000001/2026-06/sources")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_2b_in_db"] is True
        assert data["records_2b_count"] == 1


def test_resolve_latest_2b_run():
    """Verify _resolve_latest_2b_run picks latest non-deleted run with enriched file metadata."""
    from unittest.mock import MagicMock
    from app.routers.gstr2a_delta import _resolve_latest_2b_run

    sb = MagicMock()
    # Mock reconciliation_run query returning 2 candidate runs
    runs_query = MagicMock()
    runs_query.select.return_value = runs_query
    runs_query.eq.return_value = runs_query
    runs_query.in_.return_value = runs_query
    runs_query.gt.return_value = runs_query
    runs_query.not_.in_.return_value = runs_query
    runs_query.order.return_value = runs_query
    runs_query.limit.return_value = runs_query
    runs_query.execute.return_value.data = [
        {
            "id": "run-latest-deleted",
            "client_gstin_id": "client-1",
            "period": "2026-07",
            "status": "COMPLETED",
            "gstr_records_imported": 500,
            "created_at": "2026-09-01T10:00:00Z",
        },
        {
            "id": "run-older-active",
            "client_gstin_id": "client-1",
            "period": "2026-07",
            "status": "COMPLETED",
            "gstr_records_imported": 972,
            "created_at": "2026-08-27T10:00:00Z",
        },
    ]

    # Mock reconciliation_import_runs query
    import_query = MagicMock()
    import_query.select.return_value = import_query
    import_query.in_.return_value = import_query
    import_query.execute.return_value.data = [
        {
            "id": "run-latest-deleted",
            "gstr2b_file_name": "GSTR2B_deleted.xlsx",
            "gstr2b_file_size": 50000,
            "gstr2b_uploaded_at": "2026-09-01T10:00:00Z",
            "gstr2b_deleted_at": "2026-09-02T10:00:00Z",
            "gstr2b_record_count": 500,
        },
        {
            "id": "run-older-active",
            "gstr2b_file_name": "GSTR2B_1000inv.xlsx",
            "gstr2b_file_size": 91811,
            "gstr2b_uploaded_at": "2026-08-27T10:41:51Z",
            "gstr2b_deleted_at": None,
            "gstr2b_record_count": 972,
        },
    ]

    def table_router(table_name):
        if table_name == "reconciliation_run":
            return runs_query
        if table_name == "reconciliation_import_runs":
            return import_query
        return MagicMock()

    sb.table.side_effect = table_router

    resolved = _resolve_latest_2b_run(sb, "client-1", "2026-07")
    assert resolved is not None
    # run-latest-deleted should be skipped due to gstr2b_deleted_at
    assert resolved["run_id"] == "run-older-active"
    assert resolved["file_name"] == "GSTR2B_1000inv.xlsx"
    assert resolved["source_type"] == "excel_recon"
    assert resolved["record_count"] == 972


def test_fetch_2b_records_for_run_pagination_and_validation():
    """Verify _fetch_2b_records_for_run paginates and filters buyer_gstin mismatch."""
    from unittest.mock import MagicMock
    from app.routers.gstr2a_delta import _fetch_2b_records_for_run

    sb = MagicMock()
    gstr_query = MagicMock()
    gstr_query.select.return_value = gstr_query
    gstr_query.eq.return_value = gstr_query
    gstr_query.order.return_value = gstr_query

    # Create page 1 with 1,000 valid invoices and 1 mismatch, and page 2 with 50 credit notes
    page1 = [
        {
            "id": f"rec-{i}",
            "record_data": {
                "buyer_gstin": "27ISKPK1273H1ZF",
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": f"INV-{i}",
                "doc_type": "INVOICE",
                "taxable_value": 10000,
                "igst_paise": 180000,
            },
        }
        for i in range(1000)
    ]
    # Add one row with wrong buyer GSTIN to page 1
    page1.append({
        "id": "rec-mismatch",
        "record_data": {
            "buyer_gstin": "06AAAAA0000A1Z5",  # Mismatch
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-MISMATCH",
            "doc_type": "INVOICE",
        },
    })

    page2 = [
        {
            "id": f"note-{i}",
            "record_data": {
                "buyer_gstin": "27ISKPK1273H1ZF",
                "supplier_gstin": "27AABCU9603R1ZM",
                "invoice_number": f"CN-{i}",
                "doc_type": "CREDIT_NOTE",
                "section": "cdnr",
                "taxable_value": 5000,
                "igst_paise": 90000,
            },
        }
        for i in range(50)
    ]

    def range_side_effect(start, end):
        mock_res = MagicMock()
        if start == 0:
            mock_res.execute.return_value.data = page1
        elif start == len(page1):
            mock_res.execute.return_value.data = page2
        else:
            mock_res.execute.return_value.data = []
        return mock_res

    gstr_query.range.side_effect = range_side_effect
    sb.table.return_value = gstr_query

    records, doc_types = _fetch_2b_records_for_run(
        sb, "run-123", expected_gstin="27ISKPK1273H1ZF"
    )

    # 1,000 invoices + 50 credit notes = 1,050 (mismatch record excluded)
    assert len(records) == 1050
    assert doc_types["INVOICE"] == 1000
    assert doc_types["CREDIT_NOTE"] == 50


def test_reconcile_preserves_document_types():
    """Verify reconcile_2a_vs_2b carries doc_type, section, and is_amendment into results and summary."""
    from app.services.gstr2a_vs_2b import reconcile_2a_vs_2b

    records_2a = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-101",
            "doc_type": "CREDIT_NOTE",
            "section": "cdnr",
            "taxable_value_paise": 500000,
            "igst_paise": 90000,
            "filing_date": "2026-07-10",
        },
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-201",
            "doc_type": "INVOICE",
            "section": "b2b",
            "taxable_value_paise": 1000000,
            "igst_paise": 180000,
            "filing_date": "2026-07-10",
        },
    ]

    records_2b = [
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "CN-101",
            "doc_type": "CREDIT_NOTE",
            "section": "cdnr",
            "taxable_value_paise": 500000,
            "igst_paise": 90000,
        },
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "2B-ONLY-301",
            "doc_type": "DEBIT_NOTE",
            "section": "cdnr",
            "taxable_value_paise": 200000,
            "igst_paise": 36000,
        },
    ]

    results, summary = reconcile_2a_vs_2b(records_2a, records_2b, period="2026-07")

    by_inv = {r["invoice_number"]: r for r in results}
    assert by_inv["CN-101"]["category"] == "IN_BOTH"
    assert by_inv["CN-101"]["doc_type"] == "CREDIT_NOTE"
    assert by_inv["CN-101"]["section"] == "cdnr"

    assert by_inv["INV-201"]["category"] == "FILED_NOT_REFLECTED"
    assert by_inv["INV-201"]["doc_type"] == "INVOICE"

    assert by_inv["2B-ONLY-301"]["category"] == "IN_2B_NOT_2A"
    assert by_inv["2B-ONLY-301"]["doc_type"] == "DEBIT_NOTE"

    assert summary["doc_type_breakdown"]["CREDIT_NOTE"] == 1
    assert summary["doc_type_breakdown"]["INVOICE"] == 1
    assert summary["doc_type_breakdown"]["DEBIT_NOTE"] == 1


def test_overlapping_categories_and_unique_union_count():
    """Verify that Value Mismatch is a subset of records present in both,
    and total_records represents the unique union count without double-counting.
    """
    # 2A: 4 invoices (2 clean match, 1 value mismatch, 1 missing in 2B) = 4 invoices
    records_2a = [
        # Present in both (clean match)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-MATCH-1",
            "invoice_date": "2026-06-01",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        },
        # Present in both (clean match)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-MATCH-2",
            "invoice_date": "2026-06-02",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 2000000,
            "total_tax_paise": 360000,
        },
        # Present in both, but value differs (Value Mismatch)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-DIFF-1",
            "invoice_date": "2026-06-03",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 3000000,
            "total_tax_paise": 540000,
        },
        # In 2A, not in 2B (Filed Not Reflected)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-2A-ONLY-1",
            "invoice_date": "2026-06-04",
            "filing_date": "2026-06-10",
            "taxable_amount_paise": 4000000,
            "total_tax_paise": 720000,
        },
    ]

    # 2B: 4 invoices (2 clean match, 1 value mismatch, 1 2B-only) = 4 invoices
    records_2b = [
        # Present in both (clean match)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-MATCH-1",
            "invoice_date": "2026-06-01",
            "taxable_amount_paise": 1000000,
            "total_tax_paise": 180000,
        },
        # Present in both (clean match)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-MATCH-2",
            "invoice_date": "2026-06-02",
            "taxable_amount_paise": 2000000,
            "total_tax_paise": 360000,
        },
        # Present in both, but value differs (Value Mismatch)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-DIFF-1",
            "invoice_date": "2026-06-03",
            "taxable_amount_paise": 3500000,  # differs from 2A
            "total_tax_paise": 630000,
        },
        # In 2B, not in 2A (In 2B Not 2A)
        {
            "supplier_gstin": "27AABCU9603R1ZM",
            "invoice_number": "INV-2B-ONLY-1",
            "invoice_date": "2026-06-05",
            "taxable_amount_paise": 5000000,
            "total_tax_paise": 900000,
        },
    ]

    results, summary = reconcile_2a_vs_2b(
        gstr2a_records=records_2a,
        gstr2b_records=records_2b,
        period="2026-06",
        cutoff_date="2026-06-13",
    )

    # 1. Total unique union count is 5 (MATCH-1, MATCH-2, DIFF-1, 2A-ONLY-1, 2B-ONLY-1)
    assert len(results) == 5
    assert summary["total_records"] == 5
    assert summary["unique_union_count"] == 5
    assert summary["total_2a"] == 4
    assert summary["total_2b"] == 4

    # 2. Category counts
    assert summary["in_both_count"] == 2
    assert summary["value_mismatch_count"] == 1
    assert summary["filed_not_reflected_count"] == 1
    assert summary["in_2b_not_2a_count"] == 1
    assert summary["late_filed_count"] == 0

    # 3. Subset relationship: Every VALUE_MISMATCH record is present in both 2A and 2B
    value_mismatches = [r for r in results if r["category"] == "VALUE_MISMATCH"]
    assert len(value_mismatches) == 1
    vm = value_mismatches[0]
    assert vm["raw_2a_record"] is not None
    assert vm["raw_2b_record"] is not None
    assert vm["taxable_value_2a"] == 30000.0
    assert vm["taxable_value_2b"] == 35000.0

    # 4. Metadata confirms subset relationship
    assert summary["value_mismatch_is_subset"] is True
    assert "1 of the 2 invoices present in both have value differences." in summary["subset_note"]

    # 5. Non-additive invariant:
    # Unique union = in_both (clean) + value_mismatch + filed_not_reflected + in_2b_not_2a + late_filed
    # 2 + 1 + 1 + 1 + 0 = 5.
    # It must NOT be (in_both_total + value_mismatch) as separate unique items if in_both already counts all matches.
    assert (
        summary["in_both"]
        + summary["value_mismatch"]
        + summary["filed_not_reflected"]
        + summary["in_2b_not_2a"]
        + summary["late_filed"]
        == summary["total_records"]
    )





