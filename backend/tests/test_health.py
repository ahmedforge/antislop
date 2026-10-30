from fastapi.testclient import TestClient

from app.main import create_app


def test_health(monkeypatch):
    monkeypatch.setenv("APP_NAME", "AntiSlop test API")
    monkeypatch.setenv("ENVIRONMENT", "test")
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.title == "AntiSlop test API"
    assert app.state.settings.environment == "test"
