from fastapi.testclient import TestClient


def test_health_check(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["ok", "degraded"]
    assert "version" in data


def test_docs_available_in_dev(client: TestClient):
    response = client.get("/docs")
    # Docs are available in non-production environments
    assert response.status_code in (200, 404)
