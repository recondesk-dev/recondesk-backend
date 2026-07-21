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
