"""Regression tests for previously shipped safety defects."""

from pathlib import Path


def test_redis_healthcheck_never_puts_password_in_docker_event_command():
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "redis-cli -a ${REDIS_PASSWORD}" not in compose
    assert "REDISCLI_AUTH=$$REDIS_PASSWORD redis-cli ping" in compose
