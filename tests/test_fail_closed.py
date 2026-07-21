"""Redis-outage behaviour for the two security dependencies.

Both used to fail OPEN: if Redis raised, the rate limiter let the request
through and the import-ownership check skipped verification. That silently
disables brute-force protection and cross-user authz during a Redis outage.
These tests pin the fail-CLOSED contract: a Redis error denies, it does not
wave the request past a security control.
"""

from unittest.mock import patch, MagicMock

import pytest

from app.exceptions import RateLimitException, ResourceNotFoundException


class TestRateLimiterFailsClosed:
    @patch("app.core.rate_limit._get_redis")
    def test_redis_error_denies_request(self, mock_get_redis):
        from app.core.rate_limit import _check_rate_limit

        mock_get_redis.side_effect = ConnectionError("redis down")
        with pytest.raises(RateLimitException):
            _check_rate_limit("rate:test:1.2.3.4", max_requests=10, window_seconds=60)

    @patch("app.core.rate_limit._get_redis")
    def test_incr_error_denies_request(self, mock_get_redis):
        from app.core.rate_limit import _check_rate_limit

        client = MagicMock()
        client.incr.side_effect = TimeoutError("redis timeout")
        mock_get_redis.return_value = client
        with pytest.raises(RateLimitException):
            _check_rate_limit("rate:test:1.2.3.4", max_requests=10, window_seconds=60)

    @patch("app.core.rate_limit._get_redis")
    def test_under_limit_still_allowed(self, mock_get_redis):
        from app.core.rate_limit import _check_rate_limit

        client = MagicMock()
        client.incr.return_value = 1
        mock_get_redis.return_value = client
        # No exception: a healthy Redis under the limit lets the request through.
        _check_rate_limit("rate:test:1.2.3.4", max_requests=10, window_seconds=60)


class TestImportOwnershipFailsClosed:
    @patch("app.routes.jobs.redis" if False else "redis.from_url")
    def test_redis_error_denies_access(self, mock_from_url):
        from app.routes.jobs import verify_import_task_ownership
        from app.db.models import User

        mock_from_url.side_effect = ConnectionError("redis down")
        user = User(id=1, username="u", email="u@example.com")
        with pytest.raises(ResourceNotFoundException):
            verify_import_task_ownership("task-123", current_user=user)

    @patch("redis.from_url")
    def test_owner_still_allowed(self, mock_from_url):
        from app.routes.jobs import verify_import_task_ownership
        from app.db.models import User

        client = MagicMock()
        client.get.return_value = "1"
        mock_from_url.return_value = client
        user = User(id=1, username="u", email="u@example.com")
        # No exception: the real owner passes.
        verify_import_task_ownership("task-123", current_user=user)

    @patch("redis.from_url")
    def test_non_owner_denied(self, mock_from_url):
        from app.routes.jobs import verify_import_task_ownership
        from app.db.models import User

        client = MagicMock()
        client.get.return_value = "2"
        mock_from_url.return_value = client
        user = User(id=1, username="u", email="u@example.com")
        with pytest.raises(ResourceNotFoundException):
            verify_import_task_ownership("task-123", current_user=user)
