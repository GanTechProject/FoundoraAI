from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from foundora.main import app


def test_liveness_and_correlation_id() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live", headers={"X-Correlation-ID": "test-request-1"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Correlation-ID"] == "test-request-1"


def test_readiness_reports_real_probe_results() -> None:
    with (
        patch(
            "foundora.api.health.probe_database", new=AsyncMock(return_value=(True, "Reachable"))
        ),
        patch(
            "foundora.api.health.probe_redis", new=AsyncMock(return_value=(False, "Unavailable"))
        ),
        TestClient(app) as client,
    ):
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {
            "postgresql": {"status": "up", "detail": "Reachable"},
            "redis": {"status": "down", "detail": "Unavailable"},
        },
    }


def test_invalid_incoming_correlation_id_is_replaced() -> None:
    with TestClient(app) as client:
        response = client.get("/health/live", headers={"X-Correlation-ID": "not valid\nvalue"})

    assert response.status_code == 200
    assert response.headers["X-Correlation-ID"] != "not valid\nvalue"
