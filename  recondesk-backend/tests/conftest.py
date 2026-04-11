import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_headers() -> dict:
    """
    Returns mock auth headers. In real tests replace with a fixture that
    registers / logs in a test user and returns a real JWT.
    """
    return {"Authorization": "Bearer test-token"}
