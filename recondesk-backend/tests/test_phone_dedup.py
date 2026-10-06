from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException

from app.utils.phone import (
    assert_phone_not_registered,
    normalize_phone,
)


def test_normalize_phone():
    assert normalize_phone("+91 98765-43210") == "9876543210"
    assert normalize_phone("09876543210") == "9876543210"
    assert normalize_phone("9876543210") == "9876543210"
    assert normalize_phone("+919876543210") == "9876543210"
    assert normalize_phone("") == ""
    assert normalize_phone(None) == ""


def test_assert_phone_not_registered_passes_when_unique():
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    # Should not raise
    assert_phone_not_registered("9876543210", db=mock_db)


def test_assert_phone_not_registered_raises_409_when_duplicate():
    mock_db = MagicMock()
    mock_db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": "user-123"}
    ]

    with pytest.raises(HTTPException) as exc_info:
        assert_phone_not_registered("9876543210", db=mock_db)

    assert exc_info.value.status_code == 409
    assert "mobile number already exists" in exc_info.value.detail
