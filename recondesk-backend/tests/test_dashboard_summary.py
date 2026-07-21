"""Unit tests for dashboard summary aggregation (no DB)."""

from app.routers.dashboard import _build_summary, _map_ui_status, _priority_score


def test_map_ui_status():
    assert _map_ui_status("COMPLETED") == "COMPLETE"
    assert _map_ui_status("FINAL") == "FINALIZED"
    assert _map_ui_status("PROCESSING") == "MATCHING"
    assert _map_ui_status("UPLOADING") == "IMPORTING"


def test_priority_failed_highest():
    assert _priority_score("FAILED", 0, None) == 95
    assert _priority_score(None, None, None) == 10
    assert _priority_score("FINALIZED", 999999, "CRITICAL") == 0


def test_build_summary_stats_and_attention():
    clients = [
        {"id": "c1", "trade_name": "Acme", "gstin": "27A"},
        {"id": "c2", "trade_name": "Beta", "gstin": "27B"},
        {"id": "c3", "trade_name": "Gamma", "gstin": "27C"},
    ]
    runs = [
        {
            "id": "r1",
            "client_gstin_id": "c1",
            "period": "2026-04",
            "status": "FAILED",
            "created_at": "2026-04-10T00:00:00Z",
            "itc_at_risk": 100_00,
            "wrongful_itc": 0,
            "run_summary": {},
        },
        {
            "id": "r2",
            "client_gstin_id": "c2",
            "period": "2026-04",
            "status": "COMPLETED",
            "created_at": "2026-04-11T00:00:00Z",
            "itc_at_risk": 200_00,
            "wrongful_itc": 0,
            "run_summary": {},
        },
        {
            "id": "r3",
            "client_gstin_id": "c3",
            "period": "2026-04",
            "status": "FINAL",
            "created_at": "2026-04-12T00:00:00Z",
            "itc_at_risk": 0,
            "wrongful_itc": 0,
            "run_summary": {"matched_itc_paise": 500_00},
        },
        {
            "id": "r4",
            "client_gstin_id": "c3",
            "period": "2026-03",
            "status": "PENDING",
            "created_at": "2026-03-01T00:00:00Z",
            "itc_at_risk": 0,
            "wrongful_itc": 0,
            "run_summary": {},
        },
    ]
    s = _build_summary(clients, runs, team_members=4)
    assert s["total_clients"] == 3
    assert s["pending_this_month"] == 1  # older PENDING on c3
    assert s["ready_for_review"] == 1
    assert s["failed_client_count"] == 1
    assert s["total_itc_protected"] == 500.0
    assert s["itc_protected_has_data"] is True
    assert s["itc_at_risk"] == 300.0  # 100 + 200 from latest of c1/c2
    assert s["team_members"] == 4
    assert s["attention"][0]["client_id"] == "c1"
    assert s["attention"][0]["status"] == "FAILED"
    # FINALIZED latest run excluded from attention; no-run would be included
    ids = {a["client_id"] for a in s["attention"]}
    assert "c3" not in ids
    assert "c2" in ids
