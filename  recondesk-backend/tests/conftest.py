from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import get_settings
from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    """Valid HS256 token using configured JWT secret (for endpoint tests that expect auth)."""
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=1)
    tok = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000001",
            "email": "test@example.com",
            "exp": exp,
        },
        s.jwt_signing_key,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {tok}"}
