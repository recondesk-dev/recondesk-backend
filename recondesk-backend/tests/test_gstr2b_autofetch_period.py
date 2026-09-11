import pytest
from unittest.mock import patch, MagicMock
from app.routers.gstr2b_autofetch_routes import FetchGstr2bRequest
from app.integrations.gstr2b_autofetch import get_gstr2b


def test_fetch_gstr2b_request_mmyyyy():
    req = FetchGstr2bRequest(ret_period="082026")
    assert req.year == "2026"
    assert req.month == "08"
    assert req.ret_period == "082026"


def test_fetch_gstr2b_request_year_month_strings():
    req = FetchGstr2bRequest(year="2026", month="8")
    assert req.year == "2026"
    assert req.month == "08"
    assert req.ret_period == "082026"


def test_fetch_gstr2b_request_year_month_padded():
    req = FetchGstr2bRequest(year="2026", month="08")
    assert req.year == "2026"
    assert req.month == "08"
    assert req.ret_period == "082026"


def test_fetch_gstr2b_request_iso_period():
    req = FetchGstr2bRequest(period="2026-08-01")
    assert req.year == "2026"
    assert req.month == "08"
    assert req.ret_period == "082026"


def test_fetch_gstr2b_request_hyphenated_ret_period():
    req = FetchGstr2bRequest(ret_period="08-2026")
    assert req.year == "2026"
    assert req.month == "08"
    assert req.ret_period == "082026"


def test_fetch_gstr2b_request_invalid_month():
    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        FetchGstr2bRequest(ret_period="132026")

    with pytest.raises(ValueError, match="month must be between 1 and 12"):
        FetchGstr2bRequest(year="2026", month="0")


def test_fetch_gstr2b_request_invalid_year():
    with pytest.raises(ValueError, match="year must be between 2000 and 2100"):
        FetchGstr2bRequest(year="1995", month="5")


def test_fetch_gstr2b_request_empty():
    with pytest.raises(ValueError, match="year and month"):
        FetchGstr2bRequest()


@patch("httpx.get")
def test_get_gstr2b_with_ret_period(mock_get):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": {"b2b": []}}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    data = get_gstr2b(
        access_token="test-token",
        gstin="27AABCU9603R1ZM",
        ret_period="082026",
    )
    assert data == {"b2b": []}
    mock_get.assert_called_once()
    called_url = mock_get.call_args[0][0]
    assert called_url.endswith("/gstr-2b/2026/08")
