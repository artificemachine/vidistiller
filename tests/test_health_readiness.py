"""Liveness vs readiness.

/health is a static liveness probe (process up). /readyz verifies the
dependencies a request needs (DB, Redis) and returns 503 when one is down, so an
orchestrator stops routing to a pod whose database is unreachable instead of
trusting a always-'healthy' response.
"""

from unittest.mock import patch

from fastapi.testclient import TestClient


class TestHealthLiveness:
    def test_health_is_static_ok(self, client: TestClient):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


class TestReadiness:
    @patch("app.main.health_check", return_value=True)
    @patch("redis.from_url")
    def test_ready_when_all_up(self, mock_redis, mock_db, client: TestClient):
        mock_redis.return_value.ping.return_value = True
        r = client.get("/readyz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] is True
        assert body["checks"]["redis"] is True

    @patch("app.main.health_check", return_value=False)
    @patch("redis.from_url")
    def test_not_ready_returns_503_when_db_down(self, mock_redis, mock_db, client: TestClient):
        mock_redis.return_value.ping.return_value = True
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["checks"]["database"] is False

    @patch("app.main.health_check", return_value=True)
    @patch("redis.from_url", side_effect=ConnectionError("redis down"))
    def test_not_ready_returns_503_when_redis_down(self, mock_redis, mock_db, client: TestClient):
        r = client.get("/readyz")
        assert r.status_code == 503
        assert r.json()["checks"]["redis"] is False


class TestConfigNotFrozenAtImport:
    def test_env_read_at_settings_construction_not_import(self, monkeypatch):
        """Every sub-settings field uses default_factory, so a value set before
        Settings() is constructed is picked up — not frozen at module import."""
        from app.core.config import Settings

        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        s = Settings()
        assert s.logging.LOG_LEVEL == "DEBUG"
