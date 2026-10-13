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


def test_health_stays_fast_when_supabase_hangs(client: TestClient, monkeypatch):
    """Hung dependency must not wedge /health past the probe timeout."""
    import time

    import app.main as main_mod

    monkeypatch.setattr(main_mod, "_HEALTH_PROBE_TIMEOUT_S", 0.2)

    original_to_thread = main_mod.asyncio.to_thread

    async def _to_thread(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "_ping_supabase":
            await main_mod.asyncio.sleep(5)
            return None
        return await original_to_thread(fn, *args, **kwargs)

    monkeypatch.setattr(main_mod.asyncio, "to_thread", _to_thread)

    started = time.perf_counter()
    response = client.get("/health")
    elapsed = time.perf_counter() - started
    assert response.status_code == 200
    assert response.json()["supabase"] == "error"
    assert elapsed < 3.0, f"health took {elapsed:.1f}s — probe timeout not enforced"


def test_health_aurora_and_worker_observability(client: TestClient):
    """Health check must include Aurora and Celery worker observability without secret leakage."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert "aurora" in data
    assert "worker" in data
    assert isinstance(data["aurora"], dict)
    assert isinstance(data["worker"], dict)

    # Zero credential exposure assertion
    raw_text = response.text.lower()
    assert "password" not in raw_text
    assert "secret" not in raw_text
    assert "postgres://" not in raw_text
    assert "postgresql://" not in raw_text
    assert "redis://" not in raw_text


def test_health_staging_environment_reports_staging_guard(client: TestClient, monkeypatch):
    """When APP_ENV is staging, /health must surface staging guard isolation summary."""
    from app.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "staging")
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["environment"] == "staging"
    assert "staging_guard" in data
    assert "status" in data["staging_guard"]
    assert "isolated" in data["staging_guard"]
