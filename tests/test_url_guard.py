"""Tests for SSRF guards on user-supplied URLs the backend fetches itself."""

import pytest

from app.core.url_guard import validate_fetch_target, validate_llm_endpoint


class TestValidateFetchTarget:
    """video_url: private destinations are denied outright."""

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x.mp4",
            "http://localhost/x.mp4",
            "http://10.0.181.20:8000/api",
            "http://192.168.1.1/",
            "http://172.16.0.1/",
            # Cloud instance metadata, the classic SSRF payload.
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/x",
            "http://0.0.0.0/",
        ],
    )
    def test_internal_destinations_rejected(self, url):
        with pytest.raises(ValueError):
            validate_fetch_target(url)

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://127.0.0.1:6379/_INFO",
            "dict://127.0.0.1:11211/stat",
            "ftp://example.com/x",
            "javascript:alert(1)",
            "not-a-url",
            "",
        ],
    )
    def test_non_http_schemes_rejected(self, url):
        with pytest.raises(ValueError):
            validate_fetch_target(url)

    def test_public_url_allowed(self):
        assert validate_fetch_target("https://www.youtube.com/watch?v=abc")

    def test_error_does_not_disclose_resolved_address(self):
        with pytest.raises(ValueError) as exc:
            validate_fetch_target("http://10.0.181.20/x")
        assert "10.0.181" not in str(exc.value)


class TestValidateLlmEndpoint:
    """LLM endpoints: private is expected, so an allowlist governs instead."""

    def test_allowlisted_private_host_permitted(self):
        # The local-first path must keep working.
        assert validate_llm_endpoint(
            "http://localhost:11434", ["localhost", "127.0.0.1"]
        )

    def test_non_allowlisted_host_rejected(self):
        with pytest.raises(ValueError):
            validate_llm_endpoint("http://169.254.169.254/", ["localhost"])

    def test_non_allowlisted_private_host_rejected(self):
        with pytest.raises(ValueError):
            validate_llm_endpoint("http://10.0.181.20:8000/", ["localhost"])

    def test_operator_can_widen_allowlist(self):
        assert validate_llm_endpoint(
            "http://10.0.150.36:8100", ["localhost", "10.0.150.36"]
        )

    def test_empty_allowlist_rejects_everything(self):
        with pytest.raises(ValueError):
            validate_llm_endpoint("http://localhost:11434", [])
