"""Tests for Correlation / Request ID tracing middleware."""

import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.utils.context import get_correlation_id

client = TestClient(app)


def test_request_generates_correlation_id():
    response = client.get("/health")
    assert response.status_code == 200

    corr_id = response.headers.get("x-correlation-id")
    req_id = response.headers.get("x-request-id")

    assert corr_id is not None
    assert req_id is not None
    assert corr_id == req_id
    # Must be valid UUID string
    assert uuid.UUID(corr_id)


def test_request_preserves_custom_correlation_id():
    custom_cid = "custom-cid-12345-enterprise"
    response = client.get("/health", headers={"X-Correlation-ID": custom_cid})
    assert response.status_code == 200

    assert response.headers.get("x-correlation-id") == custom_cid
    assert response.headers.get("x-request-id") == custom_cid


def test_request_preserves_custom_request_id():
    custom_rid = "custom-rid-98765-gateway"
    response = client.get("/health", headers={"X-Request-ID": custom_rid})
    assert response.status_code == 200

    assert response.headers.get("x-correlation-id") == custom_rid
    assert response.headers.get("x-request-id") == custom_rid
