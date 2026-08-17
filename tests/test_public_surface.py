"""Public attack-surface hardening.

Two findings from the 2026-08-17 public-repo audit:

- ``/docs``, ``/redoc`` and ``/openapi.json`` were served unconditionally, so a
  production deployment published its full API schema to anyone who asked.
- ``backend/app/core/sidecars.json`` is the committed default registry and was
  therefore also the production config, which put real host topology into a
  public repository.
"""

import json
from pathlib import Path

from app.main import _api_doc_urls
from app.services.sidecar import load_sidecar_config


class TestApiDocsGating:
    def test_docs_served_in_development(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        urls = _api_doc_urls()
        assert urls["docs_url"] == "/docs"
        assert urls["openapi_url"] == "/openapi.json"

    def test_docs_disabled_in_production(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        urls = _api_doc_urls()
        assert urls["docs_url"] is None
        assert urls["redoc_url"] is None
        assert urls["openapi_url"] is None

    def test_docs_can_be_re_enabled_explicitly_in_production(self, monkeypatch):
        """An operator who genuinely wants public schema must opt in by name."""
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_DOCS_ENABLED", "true")
        urls = _api_doc_urls()
        assert urls["docs_url"] == "/docs"

    def test_unknown_environment_defaults_to_serving_docs(self, monkeypatch):
        """Only "production" disables docs; a typo must not silently harden."""
        monkeypatch.setenv("ENVIRONMENT", "staging")
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        assert _api_doc_urls()["docs_url"] == "/docs"

    def test_production_match_is_case_and_space_insensitive(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "  PRODUCTION  ")
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        assert _api_doc_urls()["docs_url"] is None


class TestSidecarConfigPath:
    def test_env_var_overrides_default_config_path(self, monkeypatch, tmp_path):
        """Operators must be able to keep real topology outside the repository."""
        external = tmp_path / "sidecars.json"
        external.write_text(json.dumps({
            "sidecars": [{
                "registered_id": "operator-host",
                "label": "Operator Host",
                "base_url": "http://192.0.2.99:8000",
                "capabilities": ["text"],
                "declared_model": "some-model",
                "enabled": True,
            }]
        }))
        monkeypatch.setenv("SIDECAR_CONFIG_PATH", str(external))
        entries = load_sidecar_config()
        assert [e["registered_id"] for e in entries] == ["operator-host"]

    def test_explicit_path_argument_wins_over_env_var(self, monkeypatch, tmp_path):
        explicit = tmp_path / "explicit.json"
        explicit.write_text(json.dumps({
            "sidecars": [{"registered_id": "explicit", "label": "Explicit"}]
        }))
        monkeypatch.setenv("SIDECAR_CONFIG_PATH", str(tmp_path / "nonexistent.json"))
        entries = load_sidecar_config(str(explicit))
        assert [e["registered_id"] for e in entries] == ["explicit"]


class TestCommittedSidecarConfigIsGeneric:
    """The committed default ships in a public repo; it must not describe real hosts."""

    def _config_text(self) -> str:
        path = (
            Path(__file__).parent.parent
            / "backend" / "app" / "core" / "sidecars.json"
        )
        return path.read_text(encoding="utf-8")

    def test_no_real_host_identifiers(self):
        text = self._config_text().lower()
        for marker in ("vm913", "vm903", "vm901", "vm2900"):
            assert marker not in text, f"committed sidecar config names a real host: {marker}"

    def test_no_gpu_inventory(self):
        text = self._config_text().lower()
        for marker in ("rtx", "3090", "3080"):
            assert marker not in text, f"committed sidecar config leaks GPU inventory: {marker}"

    def test_still_valid_and_uses_documentation_ips(self):
        payload = json.loads(self._config_text())
        sidecars = payload["sidecars"]
        assert sidecars, "config must still ship usable defaults"
        for entry in sidecars:
            assert entry["base_url"].startswith("http://192.0.2."), (
                f"{entry['registered_id']} must use the RFC 5737 documentation range"
            )
