"""Deployment templates keep fleet topology and image ownership external."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_uses_generic_images_and_external_manifest_mount():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "VIDISTILLER_BACKEND_IMAGE_REF" in compose
    assert "VIDISTILLER_FRONTEND_IMAGE_REF" in compose
    assert "VIDISTILLER_IMAGE_TAG:-latest" not in compose
    assert "LLM_MODEL_PROFILES_HOST_DIR" in compose
    assert ":/etc/vidistiller:ro" in compose
    assert "./alembic.ini:/app/alembic.ini:ro" in compose
    assert "./migrations:/app/migrations:ro" in compose
    assert "healthcheck:" in compose.split("  pgadmin:", 1)[1]


def test_production_compose_forwards_sidecar_config_path_to_api_and_worker():
    """SIDECAR_CONFIG_PATH must reach both services that seed/route sidecars.

    Regression: the env var and its :/etc/vidistiller:ro mount target were
    documented in .env.example but never added to either service's
    `environment:` block, so setting it on the host had no effect — the app
    would silently fall back to the committed placeholder registry on every
    deploy, in the one direction (real config -> ignored) that never surfaces
    as an error.
    """
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert compose.count("SIDECAR_CONFIG_PATH: ${SIDECAR_CONFIG_PATH:-}") == 2, (
        "SIDECAR_CONFIG_PATH must be forwarded in both the api and "
        "celery_worker environment blocks"
    )


def test_production_pgadmin_disables_optional_postfix_under_no_new_privileges():
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    pgadmin = compose.split("  pgadmin:", 1)[1]

    assert 'PGADMIN_DISABLE_POSTFIX: "true"' in pgadmin


def test_example_keeps_operator_specific_routing_values_unset():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "VLLM_PRIMARY_URL=https://" in example
    assert "LLM_MODEL_PROFILES_PATH=/etc/vidistiller/" in example
    assert "SIDECAR_CONFIG_PATH=/etc/vidistiller/" in example
    assert "VIDISTILLER_BACKEND_IMAGE_REF=example-org/" in example


def test_non_production_database_and_cache_ports_bind_to_loopback():
    for name in ("docker-compose.test.yml", "docker-compose.e2e.yml", "docker-compose.staging.yml"):
        compose = (ROOT / name).read_text(encoding="utf-8")
        assert '"127.0.0.1:' in compose


def test_deploy_builds_and_signs_candidate_drafts():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")

    assert "build-candidate" in workflow
    assert "cosign sign --yes" in workflow
    assert "cosign attest --yes" in workflow
    assert "release_candidate.py create" in workflow
    assert "gh release create" in workflow and "--draft" in workflow
    assert "--target" in workflow  # draft target_commitish = the candidate commit


def test_promotion_verifies_immutable_image_references_with_cosign():
    workflow = (ROOT / ".github" / "workflows" / "promote-release.yml").read_text(
        encoding="utf-8"
    )

    assert "VIDISTILLER_BACKEND_IMAGE_REF" in workflow
    assert "VIDISTILLER_FRONTEND_IMAGE_REF" in workflow
    assert "cosign verify --certificate-identity-regexp" in workflow
    # Promotion reuses the recorded digests; it must never rebuild.
    assert "docker buildx imagetools create" in workflow
    assert "build-push-action" not in workflow


def test_staging_overlay_pins_immutable_digests():
    overlay = (ROOT / "docker-compose.staging-images.yml").read_text(encoding="utf-8")

    assert overlay.count("${VIDISTILLER_BACKEND_IMAGE_REF:?") == 2
    assert overlay.count("${VIDISTILLER_FRONTEND_IMAGE_REF:?") == 1
    assert "${VIDISTILLER_BACKEND_IMAGE_REF:?" in overlay


def test_dockerignore_excludes_test_and_editor_build_context_files():
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")

    for entry in ("tests/", ".vscode/", ".idea/"):
        assert entry in dockerignore

    frontend_dockerignore = (ROOT / "frontend" / ".dockerignore").read_text(
        encoding="utf-8"
    )
    for entry in (".env", "node_modules", ".next", "__tests__"):
        assert entry in frontend_dockerignore


def test_development_compose_keeps_migrations_read_only_and_pgadmin_observable():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "./alembic.ini:/app/alembic.ini:ro" in compose
    assert "./migrations:/app/migrations:ro" in compose
    assert "pgadmin:" in compose and "misc/ping" in compose


def test_ansible_template_keeps_redis_secret_out_of_healthcheck_and_checks_workers():
    template = (
        ROOT / "deploy" / "ansible" / "roles" / "vidistiller" / "templates" / "docker-compose.yml.j2"
    ).read_text(encoding="utf-8")

    assert 'REDISCLI_AUTH=$$REDIS_PASSWORD redis-cli ping' in template
    assert 'redis-cli", "-a", "${REDIS_PASSWORD}"' not in template
    assert "celery_worker:" in template and "celery -A app.tasks inspect ping" in template
    assert "pgadmin:" in template and "misc/ping" in template


def test_ansible_deployment_requires_verified_immutable_image_references():
    role_dir = ROOT / "deploy" / "ansible" / "roles" / "vidistiller"
    defaults = (role_dir / "defaults" / "main.yml").read_text(encoding="utf-8")
    tasks = (role_dir / "tasks" / "main.yml").read_text(encoding="utf-8")
    template = (role_dir / "templates" / "docker-compose.yml.j2").read_text(encoding="utf-8")

    assert "backend_image_ref" in defaults
    assert "frontend_image_ref" in defaults
    assert "@sha256:" in tasks
    assert "      - cosign" in tasks
    assert "      - verify" in tasks
    assert "image: {{ backend_image_ref }}" in template
    assert "image: {{ frontend_image_ref }}" in template
