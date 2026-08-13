"""Smoke checks for startup configuration and primary API availability."""


def test_application_health_smoke(client):
    assert client.get("/health").status_code == 200
