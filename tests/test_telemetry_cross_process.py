"""WP3-hotfix acceptance: cross-process sidecar telemetry via the shared
Redis store.

The v1.16.2 telemetry defect was that `sidecar.py::_telemetry_cache` was
process-local and refreshed ONLY by the API process scheduler, so the Celery
worker process could never acquire a slot or resolve a provider/model (fail
closed forever). This test proves the hotfix:

1. an API/scheduler-style process publishes telemetry to the shared Redis
   store (real Postgres + Redis, docker-compose.test.yml, bounded stub
   sidecar probe);
2. a DISTINCT worker-style process (fresh Python process with an empty
   process-local cache) can acquire a slot and resolve the provider/model
   from the shared store — with NO process-local cache injection;
3. absent / stale / unhealthy / no-model telemetry fails closed;
4. worker restart/reload behavior: a fresh process re-reads the shared
   store.

Skipped when Postgres or Redis are unreachable.
"""

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db",
)
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"


def _postgres_reachable(url: str) -> bool:
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except OperationalError:
        return False


def _redis_reachable(url: str) -> bool:
    try:
        import redis as _redis

        client = _redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not (_postgres_reachable(DATABASE_URL) and _redis_reachable(REDIS_URL)),
    reason="requires real Postgres + Redis (docker-compose.test.yml)",
)


# ---------------------------------------------------------------------------
# Bounded stub sidecar: a tiny HTTP server that speaks the vLLM-shaped
# /v1/models + /metrics endpoints, configurable per test.
# ---------------------------------------------------------------------------
class StubSidecar:
    def __init__(self, models=("stub-model",), healthy=True):
        self.models = list(models)
        self.healthy = healthy

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path.rstrip("/").endswith("/v1/models"):
                    if not self.server.sidecar.healthy:  # type: ignore[attr-defined]
                        self.send_response(500)
                        self.end_headers()
                        return
                    body = json.dumps(
                        {"data": [{"id": m} for m in self.server.sidecar.models]}  # type: ignore[attr-defined]
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.rstrip("/").endswith("/metrics"):
                    body = (
                        "vllm:num_requests_running 0\n"
                        "vllm:num_requests_waiting 0\n"
                    ).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.sidecar = self  # type: ignore[attr-defined]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _fresh_schema():
    """Drop/recreate the public schema and migrate to head (like the other
    PG integration tests)."""
    from alembic import command
    from alembic.config import Config

    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(cfg, "head")
    engine.dispose()


def _flush_telemetry_keys():
    import redis as _redis

    client = _redis.from_url(REDIS_URL, decode_responses=True)
    for key in client.scan_iter("vidistiller:sidecar-telemetry:*"):
        client.delete(key)


@pytest.fixture()
def cross_process_env(stub_sidecar):
    """Migrated DB with a registered sidecar + slot, plus the shared env for
    both subprocess roles. Uses an EXPLICIT engine bound to DATABASE_URL for
    parent-process seeding (never the global app SessionLocal, which may be
    bound to SQLite in the test process)."""
    _fresh_schema()
    _flush_telemetry_keys()

    from app.db.models import Base, ResourceSlot, Sidecar, User
    from app.services.auth import AuthService

    seed_engine = create_engine(DATABASE_URL)
    SeedSession = sessionmaker(bind=seed_engine, expire_on_commit=False)
    db = SeedSession()
    try:
        user = User(
            username="telemetry_share",
            email="telemetry_share@test.local",
            password_hash=AuthService.hash_password("SharePass123"),
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(
            Sidecar(
                registered_id="primary",
                label="Primary (stub)",
                base_url=stub_sidecar.base_url,
                capabilities=["text"],
                enabled=True,
            )
        )
        db.add(ResourceSlot(sidecar_id="primary", slot_index=0, enabled=True))
        db.commit()
        user_id = user.id
    finally:
        db.close()
        seed_engine.dispose()

    env = dict(os.environ)
    env["DATABASE_URL"] = DATABASE_URL
    env["REDIS_URL"] = REDIS_URL
    env["ENVIRONMENT"] = "testing"
    env["JWT_SECRET_KEY"] = "TestSecretKey123!@#abcDEF_development_onlyx"
    env["PYTHONPATH"] = str(BACKEND_DIR)
    env["ADMISSION_GLOBAL_ACTIVE_LIMIT"] = "100"
    env["ADMISSION_PER_USER_ACTIVE_LIMIT"] = "100"
    env["SIDECAR_SLOTS"] = "1"
    env["WORKER_USER_ID"] = str(user_id)
    yield {"env": env, "user_id": user_id, "stub": stub_sidecar}
    _flush_telemetry_keys()


@pytest.fixture()
def stub_sidecar():
    with StubSidecar() as stub:
        yield stub


# ---------------------------------------------------------------------------
# Subprocess roles. Each role runs in its OWN fresh Python process so the
# process-local `_telemetry_cache` starts EMPTY — any telemetry the worker
# role sees MUST come from the shared Redis store.
# ---------------------------------------------------------------------------
API_ROLE = r"""
import json, sys
from app.db.session import SessionLocal
from app.services.sidecar import refresh_telemetry_cache

db = SessionLocal()
try:
    refresh_telemetry_cache(db)  # probes the stub sidecar, publishes to Redis
finally:
    db.close()
print("published", flush=True)
"""

WORKER_ROLE = r"""
import json, os, sys, uuid
from app.db.session import SessionLocal
from app.services.lease import acquire_slot
from app.services.sidecar import _telemetry_cache
from app.tasks import _resolve_provider_for_slot
from app.db.models import ProcessingJob

# Fresh process: the local cache MUST be empty before any acquire (no
# process-local injection).
assert not _telemetry_cache, "worker process-local cache must start empty"

from app.services.job_steps import seed_job_steps

user_id = int(os.environ["WORKER_USER_ID"])

db = SessionLocal()
try:
    job = ProcessingJob(
        job_id=str(uuid.uuid4()),
        status="pending",
        video_url="https://example.com/v",
        user_id=user_id,
        processing_mode="slide_aware",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    seed_job_steps(db, job, extract_snapshots=False, is_slide_mode=True)
    db.commit()

    slot = acquire_slot(db, job, exec_uuid=str(uuid.uuid4()))
    if slot is None:
        print(
            json.dumps({
                "slot": None,
                "local_cache": {k: (v.healthy, list(v.served_models)) for k, v in _telemetry_cache.items()},
            }),
            flush=True,
        )
        sys.exit(0)
    provider, model = _resolve_provider_for_slot(db, slot)
    # VLLMProvider stores the endpoint on the OpenAI client.
    provider_url = None
    try:
        provider_url = str(getattr(provider.client, "base_url", ""))
    except Exception:
        provider_url = None
    print(
        json.dumps({
            "slot": slot.sidecar_id,
            "slot_index": slot.slot_index,
            "model": model,
            "provider_base_url": provider_url,
            "local_cache": {k: (v.healthy, list(v.served_models)) for k, v in _telemetry_cache.items()},
        }),
        flush=True,
    )
finally:
    db.close()
"""


def _run_role(role_code: str, env: dict) -> str:
    proc = subprocess.run(
        [sys.executable, "-c", role_code],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"role failed:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return proc.stdout.strip()


def test_worker_process_acquires_slot_and_resolves_model_via_shared_store(cross_process_env):
    """API role publishes telemetry to Redis; a DISTINCT worker process (empty
    local cache) acquires the slot and resolves provider/model from the shared
    store — proving the cross-process fix without cache injection."""
    env = cross_process_env["env"]

    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    out_worker = _run_role(WORKER_ROLE, env)
    result = json.loads(out_worker.splitlines()[-1])
    assert result["slot"] == "primary"
    assert result["model"] == "stub-model"
    # Provider bound to the LEASED sidecar's registry URL (not the declared
    # model, not any fallback): must equal the stub's base URL with /v1
    # appended (VLLMProvider normalizes to the OpenAI-compatible path).
    expected_url = cross_process_env["stub"].base_url.rstrip("/") + "/v1"
    assert result["provider_base_url"].rstrip("/") == expected_url, \
        f"provider bound to {result['provider_base_url']!r}, expected {expected_url!r}"
    # The worker's own local cache was populated via the shared store, not
    # injected: it must contain the stub's served model.
    assert result["local_cache"].get("primary") is not None


def test_absent_telemetry_fails_closed(cross_process_env):
    """No API publish: the worker process must fail closed (no slot)."""
    env = cross_process_env["env"]
    out_worker = _run_role(WORKER_ROLE, env)
    result = json.loads(out_worker.splitlines()[-1])
    assert result["slot"] is None


def test_stale_telemetry_fails_closed(cross_process_env):
    """Publish a snapshot with an old observed_at: the worker must reject it."""
    import redis as _redis
    from app.services.sidecar import _telemetry_key

    env = cross_process_env["env"]
    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    client = _redis.from_url(REDIS_URL, decode_responses=True)
    raw = json.loads(client.get(_telemetry_key("primary")))
    raw["observed_at"] = time.time() - 3600
    client.setex(_telemetry_key("primary"), 120, json.dumps(raw))

    out_worker = _run_role(WORKER_ROLE, env)
    result = json.loads(out_worker.splitlines()[-1])
    assert result["slot"] is None


def test_unhealthy_telemetry_fails_closed(cross_process_env):
    """Stub reports unhealthy: published telemetry healthy=False -> no slot."""
    env = cross_process_env["env"]
    # Flip the stub to unhealthy and re-publish.
    cross_process_env["stub"].healthy = False
    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    out_worker = _run_role(WORKER_ROLE, env)
    result = json.loads(out_worker.splitlines()[-1])
    assert result["slot"] is None


def test_no_model_telemetry_fails_closed(cross_process_env):
    """Stub serves no models: telemetry healthy but served_models empty ->
    fail closed."""
    env = cross_process_env["env"]
    cross_process_env["stub"].models = []
    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    out_worker = _run_role(WORKER_ROLE, env)
    result = json.loads(out_worker.splitlines()[-1])
    assert result["slot"] is None


def test_worker_restart_reload_reads_shared_store(cross_process_env):
    """Two distinct worker processes (simulating a worker restart) both
    acquire from the SAME published snapshot; a third fresh process after the
    store is cleared fails closed."""
    env = cross_process_env["env"]

    _run_role(API_ROLE, env)

    out1 = _run_role(WORKER_ROLE, env)
    assert json.loads(out1.splitlines()[-1])["slot"] == "primary"

    # Worker restart: a brand-new process, same published snapshot.
    out2 = _run_role(WORKER_ROLE, env)
    assert json.loads(out2.splitlines()[-1])["slot"] == "primary"

    # Shared store cleared -> fresh worker fails closed (no cached data).
    import redis as _redis

    client = _redis.from_url(REDIS_URL, decode_responses=True)
    for key in client.scan_iter("vidistiller:sidecar-telemetry:*"):
        client.delete(key)

    out3 = _run_role(WORKER_ROLE, env)
    assert json.loads(out3.splitlines()[-1])["slot"] is None


def _publish_raw(payload: dict) -> None:
    """Write an arbitrary (possibly malformed) payload under the primary
    telemetry key, bypassing the strict serializer."""
    import redis as _redis

    client = _redis.from_url(REDIS_URL, decode_responses=True)
    client.set(
        f"vidistiller:sidecar-telemetry:primary",
        json.dumps(payload, allow_nan=True),
        ex=120,
    )


def _valid_payload(**overrides) -> dict:
    payload = {
        "registered_id": "primary",
        "label": "Primary",
        "base_url": "http://127.0.0.1:1",
        "declared_model": "stub-model",
        "capabilities": ["text"],
        "healthy": True,
        "served_models": ["stub-model"],
        "running_requests": 0,
        "waiting_requests": 0,
        "vram_used_mib": None,
        "vram_total_mib": None,
        "cache_hit_rate": None,
        "reserved_slots": 0,
        "total_slots": 1,
        "observed_at": time.time(),
    }
    payload.update(overrides)
    return payload


def test_no_redis_io_while_row_locks_held(cross_process_env):
    """Proof of the no-network-I/O-under-lock invariant: with a supplied
    snapshot and an EMPTY local cache, acquire_slot must complete without ANY
    Redis read (the read path is patched to raise, so any read-through would
    fail the acquire while locks are held)."""
    import redis as _redis
    from app.services.sidecar import (
        _get_redis,
        _read_telemetry_from_redis,
        _telemetry_cache,
        _telemetry_key,
        _telemetry_local_ts,
        _telemetry_lock,
        prefetch_sidecar_telemetry,
    )

    env = cross_process_env["env"]
    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    from app.db.models import ProcessingJob
    from app.services.lease import acquire_slot

    seed_engine = create_engine(DATABASE_URL)
    SeedSession = sessionmaker(bind=seed_engine, expire_on_commit=False)
    db = SeedSession()
    try:
        # Build the snapshot exactly like a task would (empty local cache ->
        # prefetch reads Redis once, BEFORE any lock).
        snapshot = prefetch_sidecar_telemetry(db)
        assert snapshot.get("primary") is not None

        # Empty the local cache AND break every Redis read path: if the
        # locked section attempted any read-through, it would raise.
        with _telemetry_lock:
            _telemetry_cache.clear()
            _telemetry_local_ts.clear()
        real_get = _get_redis().get
        real_read = _read_telemetry_from_redis

        def _boom(*a, **k):
            raise AssertionError("Redis read attempted while row locks held")

        _get_redis().get = _boom  # type: ignore[method-assign]
        import app.services.sidecar as _sc

        _sc._read_telemetry_from_redis = _boom  # type: ignore[assignment]
        try:
            job = ProcessingJob(
                job_id="noio-lock-proof",
                status="pending",
                video_url="https://example.com/v",
                user_id=cross_process_env["user_id"],
                processing_mode="slide_aware",
            )
            db.add(job)
            db.commit()
            # Pass the snapshot explicitly: lock-held paths never prefetch.
            slot = acquire_slot(
                db, job, exec_uuid="exec-noio", telemetry_snapshot=snapshot
            )
            db.commit()
            assert slot is not None, "acquire_slot must use the supplied snapshot only"
        finally:
            _get_redis().get = real_get  # type: ignore[method-assign]
            _sc._read_telemetry_from_redis = real_read  # type: ignore[assignment]
    finally:
        db.close()
        seed_engine.dispose()


def test_resolve_provider_fails_closed_on_stale_telemetry(cross_process_env):
    """A leased slot whose telemetry is STALE must yield NO provider (fail
    closed) — the summarize/slide path must not fabricate capacity from an
    aged snapshot."""
    import redis as _redis
    from app.db.models import ProcessingJob
    from app.services.lease import acquire_slot, release_slot
    from app.services.sidecar import _telemetry_key
    from app.tasks import _resolve_provider_for_slot

    env = cross_process_env["env"]
    out_api = _run_role(API_ROLE, env)
    assert "published" in out_api

    seed_engine = create_engine(DATABASE_URL)
    SeedSession = sessionmaker(bind=seed_engine, expire_on_commit=False)
    db = SeedSession()
    try:
        job = ProcessingJob(
            job_id="resolve-fail-closed",
            status="pending",
            video_url="https://example.com/v",
            user_id=cross_process_env["user_id"],
            processing_mode="slide_aware",
        )
        db.add(job)
        db.commit()
        slot = acquire_slot(db, job, exec_uuid="exec-resolve")
        db.commit()
        assert slot is not None

        # Age the snapshot past staleness: provider resolution must fail
        # closed even though a slot is held. Clear this process's local
        # cache first so the resolve path reads the (aged) shared store —
        # exactly what a fresh worker process would do.
        client = _redis.from_url(REDIS_URL, decode_responses=True)
        raw = json.loads(client.get(_telemetry_key("primary")))
        raw["observed_at"] = time.time() - 3600
        client.setex(_telemetry_key("primary"), 120, json.dumps(raw))

        from app.services.sidecar import (
            _telemetry_cache,
            _telemetry_local_ts,
            _telemetry_lock,
        )

        with _telemetry_lock:
            _telemetry_cache.clear()
            _telemetry_local_ts.clear()

        provider, model = _resolve_provider_for_slot(db, slot)
        db.commit()
        assert provider is None and model is None
        release_slot(db, slot.id, "exec-resolve", slot.generation)
        db.commit()
    finally:
        db.close()
        seed_engine.dispose()


def test_malformed_telemetry_fails_closed(cross_process_env):
    """Strict deserialization: any shape/type violation fails closed (no
    coercion). Each malformed variant must produce NO slot in a fresh worker
    process."""
    env = cross_process_env["env"]
    malformed = [
        {"healthy": "false"},  # string not bool — must not coerce to True
        {"served_models": "stub-model"},  # string not list
        {"served_models": [""]},  # empty model id
        {"served_models": [123]},  # non-string model id
        {"observed_at": "NaN"},  # non-finite timestamp must be rejected
        {"observed_at": "123"},  # string timestamp — no coercion
        {"registered_id": "other"},  # mismatched registered id
        {"capabilities": "text"},  # string not list
        {"capabilities": [""]},  # empty capability
        {"label": 123},  # wrong type
        {"base_url": None},  # wrong type
        {"declared_model": 42},  # non-string declared model
        {"running_requests": "2"},  # string int — must reject, not coerce
        {"running_requests": True},  # bool is not an int
        {"reserved_slots": "1"},  # string int
        {"total_slots": 1.5},  # float int
        {"vram_used_mib": "abc"},  # string for nullable int
        {"cache_hit_rate": "0.9"},  # string for nullable float
        {"vram_total_mib": True},  # bool for nullable int
        {"cache_hit_rate": float("nan")},  # actual NaN float
        {"cache_hit_rate": float("inf")},  # positive infinity
        {"cache_hit_rate": float("-inf")},  # negative infinity
        {"capabilities": None},  # capabilities REQUIRED, not null
        {"capabilities": []},  # empty capabilities list
        {"cache_hit_rate": 10**400},  # oversized int -> OverflowError on float()
        {"observed_at": 10**400},  # oversized observed_at int
    ]
    for overrides in malformed:
        _publish_raw(_valid_payload(**overrides))
        out_worker = _run_role(WORKER_ROLE, env)
        result = json.loads(out_worker.splitlines()[-1])
        assert result["slot"] is None, f"malformed payload {overrides} did not fail closed"


def test_malformed_telemetry_with_valid_shape_still_requires_healthy_model(cross_process_env):
    """A well-typed but semantically empty/unhealthy snapshot still fails
    closed (strictness is on top of the existing fail-closed gates)."""
    env = cross_process_env["env"]
    for overrides in ({"healthy": False}, {"served_models": []}, {"observed_at": time.time() - 3600}):
        _publish_raw(_valid_payload(**overrides))
        out_worker = _run_role(WORKER_ROLE, env)
        result = json.loads(out_worker.splitlines()[-1])
        assert result["slot"] is None, f"payload {overrides} did not fail closed"


def test_deserializer_strict_contract_unit():
    """Direct unit test of the strict deserializer contract (no subprocess):
    EVERY malformed payload must yield None, including overflow cases that
    raise OverflowError during float() conversion."""
    from app.services.sidecar import _telemetry_from_dict

    base = _valid_payload()
    malformed = [
        {"cache_hit_rate": 10**400},
        {"observed_at": 10**400},
        {"cache_hit_rate": float("nan")},
        {"cache_hit_rate": float("inf")},
        {"observed_at": float("-inf")},
        {"capabilities": None},
        {"capabilities": []},
        {"healthy": "false"},
        {"served_models": [""]},
        {"running_requests": "2"},
        {"declared_model": 42},
    ]
    for overrides in malformed:
        payload = dict(base)
        payload.update(overrides)
        assert _telemetry_from_dict(payload) is None, f"{overrides} must fail closed"
    # Control: the valid payload deserializes.
    assert _telemetry_from_dict(base) is not None
