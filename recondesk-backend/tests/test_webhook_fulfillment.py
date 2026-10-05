"""Tests for Razorpay webhook idempotency, deduplication, and asynchronous fulfillment."""

import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.database import supabase_client
from app.services.payment_webhook_service import (
    fulfill_razorpay_payment_captured,
    record_webhook_event,
    verify_razorpay_webhook_signature,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def override_db():
    app.dependency_overrides[supabase_client] = lambda: MagicMock()
    yield
    app.dependency_overrides.pop(supabase_client, None)


def test_verify_razorpay_webhook_signature():
    with patch.object(settings, "RAZORPAY_KEY_SECRET", "test_secret_key_123"):
        body = b'{"event":"payment.captured"}'
        valid_sig = hmac.new(b"test_secret_key_123", body, hashlib.sha256).hexdigest()
        assert verify_razorpay_webhook_signature(body, valid_sig) is True
        assert verify_razorpay_webhook_signature(body, "invalid_sig") is False


def test_record_webhook_event_deduplication():
    mock_sb = MagicMock()
    # First query: existing processed event
    mock_sb.table().select().eq().eq().limit().execute.return_value.data = [
        {"id": "ev-1", "status": "processed"}
    ]

    is_new, status = record_webhook_event(
        mock_sb,
        provider="razorpay",
        event_id="evt_duplicate_123",
        event_type="payment.captured",
        payload={},
    )
    assert is_new is False
    assert status == "already_processed"


def test_record_webhook_event_new():
    mock_sb = MagicMock()
    mock_sb.table().select().eq().limit().execute.return_value.data = []
    mock_sb.table().insert().execute.return_value.data = [{"id": "ev-new"}]

    is_new, status = record_webhook_event(
        mock_sb,
        provider="razorpay",
        event_id="evt_new_456",
        event_type="payment.captured",
        payload={},
    )
    assert is_new is True


@pytest.mark.asyncio
async def test_fulfill_razorpay_payment_captured():
    mock_sb = MagicMock()
    # Payments table check: not yet recorded
    mock_sb.table().select().eq().limit().execute.return_value.data = []

    payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_123",
                    "order_id": "order_test_456",
                    "amount": 299900,
                    "notes": {
                        "user_id": "firm-owner-uuid-1",
                        "run_id": "run-uuid-1",
                        "plan": "starter",
                        "billing_period": "yearly",
                    },
                }
            }
        },
    }

    with patch("app.services.payment_webhook_service.activate_subscription", new_callable=AsyncMock) as mock_activate, \
         patch("app.services.payment_webhook_service.invalidate_user_dashboard") as mock_invalidate:
        res = await fulfill_razorpay_payment_captured(mock_sb, payload)

        assert res["status"] == "fulfilled"
        assert res["payment_id"] == "pay_test_123"
        assert res["firm_owner_id"] == "firm-owner-uuid-1"

        # Verify payments insert was invoked
        mock_sb.table().insert.assert_called()
        # Verify subscription was activated
        mock_activate.assert_called_once()
        # Verify run was marked paid
        mock_sb.table("reconciliation_run").update.assert_called()
        # Verify dashboard cache was invalidated
        mock_invalidate.assert_called_with("firm-owner-uuid-1")


def test_razorpay_webhook_replay_returns_200():
    with patch.object(settings, "RAZORPAY_KEY_SECRET", "test_secret_123"), \
         patch("app.routers.webhooks.record_webhook_event", return_value=(False, "already_processed")):
        body = json.dumps({"event": "payment.captured", "id": "evt_replay_1"}).encode("utf-8")
        sig = hmac.new(b"test_secret_123", body, hashlib.sha256).hexdigest()

        response = client.post(
            "/api/v1/webhooks/razorpay",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json() == {"received": True, "duplicate": True}


def test_payments_webhook_replay_returns_200():
    with patch.object(settings, "RAZORPAY_KEY_SECRET", "test_secret_123"), \
         patch("app.routers.payments.record_webhook_event", return_value=(False, "already_processed")):
        body = json.dumps({"event": "payment.captured", "id": "evt_replay_2"}).encode("utf-8")
        sig = hmac.new(b"test_secret_123", body, hashlib.sha256).hexdigest()

        response = client.post(
            "/api/payments/webhook",
            content=body,
            headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json() == {"received": True, "duplicate": True}
