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


@pytest.fixture(autouse=True)
def clean_dependency_overrides():
    """Ensure FastAPI dependency overrides don't leak across tests."""
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def mock_default_admin_profile(monkeypatch):
    """Ensure default test user 00000000-0000-0000-0000-000000000001 has an admin profile in tests."""
    from app import database
    original_get_user_profile = database.get_user_profile

    def patched_get_user_profile(user_id: str):
        if str(user_id) == "00000000-0000-0000-0000-000000000001":
            return {
                "id": "00000000-0000-0000-0000-000000000001",
                "email": "test@example.com",
                "role": "admin",
                "is_active": True,
            }
        return original_get_user_profile(user_id)

    monkeypatch.setattr(database, "get_user_profile", patched_get_user_profile)
    from app import auth
    monkeypatch.setattr(auth, "get_user_profile", patched_get_user_profile)

